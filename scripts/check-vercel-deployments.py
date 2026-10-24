#!/usr/bin/env python3
"""Catch broken or unexpected Vercel deployments of one commit.

Vercel reports each project's build back to GitHub as a commit status named
"Vercel – <project>". This script waits until those statuses settle, then
compares them with deploy/vercel/projects.json:

* an expected project that failed is an error;
* any project not in the manifest is flagged: a failing one is an error (it
  breaks the commit's checks), a succeeding one is a warning (it may publish a
  half-working copy, for example a frontend with no engine behind it);
* an expected project that never reported is a warning;
* a status still pending at the deadline is an error.

With VERCEL_TOKEN (and VERCEL_TEAM_ID for team projects) set, each failed
deployment's Vercel error code and message are fetched and explained. Without
them the check still works from the GitHub statuses alone. Standard library
only; tokens are read from the environment and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "deploy" / "vercel" / "projects.json"
CONTEXT = re.compile(r"^Vercel\s+[–-]\s+(?P<project>[A-Za-z0-9._-]+)$")
DEPLOYMENT_ID = re.compile(r"\b(dpl_[A-Za-z0-9]+)\b")
MAX_BODY = 2_000_000

# Known Vercel build error codes and what they mean for this repository.
EXPLANATIONS: dict[str, str] = {
    "FASTAPI_ENTRYPOINT_NOT_FOUND": (
        "The project uses Vercel's FastAPI preset, which looks for app.py, main.py and "
        "similar files. This repository deploys as a container from Dockerfile.vercel. "
        "Set the project's framework preset to the container (Dockerfile) option, or "
        "disconnect the project if it is a duplicate."
    ),
    "BUILD_FAILED": "The build command failed; read the build log for the first error.",
    "NO_OUTPUT_DIRECTORY": (
        "The preset expected a static output directory. This repository's web build "
        "needs the engine API, so a static-only project cannot serve a working app."
    ),
}


@dataclass(frozen=True)
class Status:
    project: str
    state: str  # success | failure | error | pending
    description: str
    target_url: str


@dataclass
class Finding:
    level: str  # error | warning
    project: str
    message: str
    detail: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    statuses: list[Status] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(f.level == "error" for f in self.findings)


def latest_vercel_statuses(raw: list[dict]) -> list[Status]:
    """Keep the newest status per Vercel context (the API lists newest first)."""
    seen: dict[str, Status] = {}
    for item in raw:
        match = CONTEXT.match(str(item.get("context", "")))
        if not match or match["project"] in seen:
            continue
        seen[match["project"]] = Status(
            project=match["project"],
            state=str(item.get("state", "")),
            description=str(item.get("description") or ""),
            target_url=str(item.get("target_url") or ""),
        )
    return sorted(seen.values(), key=lambda s: s.project)


def deployment_id(status: Status) -> str | None:
    for text in (status.description, status.target_url):
        found = DEPLOYMENT_ID.search(text)
        if found:
            return found[1]
    tail = status.target_url.rstrip("/").rsplit("/", 1)[-1]
    return f"dpl_{tail}" if re.fullmatch(r"[A-Za-z0-9]{20,40}", tail) else None


def classify(
    statuses: list[Status],
    expected: dict[str, dict],
    details: dict[str, tuple[str, str]] | None = None,
) -> Report:
    """Turn settled statuses into findings. `details` maps project -> (code, message)."""
    details = details or {}
    report = Report(statuses=statuses)
    reported = {s.project for s in statuses}
    for status in statuses:
        code, vercel_message = details.get(status.project, ("", ""))
        explanation = EXPLANATIONS.get(code, "")
        extra = " ".join(part for part in (
            f"Vercel error {code}: {vercel_message}" if code else "",
            explanation,
            f"Logs: {status.target_url}" if status.target_url else "",
        ) if part)
        known = status.project in expected
        if status.state == "pending":
            report.findings.append(Finding(
                "error", status.project, "deployment did not finish before the deadline", extra))
        elif status.state in ("failure", "error"):
            message = "expected deployment failed" if known else (
                "unexpected Vercel project is building this repository and failing; "
                "disconnect it or add it to deploy/vercel/projects.json with its preset")
            report.findings.append(Finding("error", status.project, message, extra))
        elif not known:
            report.findings.append(Finding(
                "warning", status.project,
                "unexpected Vercel project deploys this repository; it may publish a "
                "copy that is not the reviewed demo (for example a frontend with no engine)",
                extra,
            ))
    for project in sorted(set(expected) - reported):
        report.findings.append(Finding(
            "warning", project, "expected Vercel project did not report a deployment"))
    return report


# ------------------------------------------------------------------ network

def _get_json(url: str, token: str) -> object:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "f1-prediction-engine-deploy-check",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ValueError("response too large")
    return json.loads(body)


def fetch_statuses(repo: str, sha: str, token: str) -> list[dict]:
    raw: list[dict] = []
    for page in range(1, 6):
        url = (f"https://api.github.com/repos/{repo}/commits/{urllib.parse.quote(sha)}"
               f"/statuses?per_page=100&page={page}")
        batch = _get_json(url, token)
        if not isinstance(batch, list) or not batch:
            break
        raw.extend(batch)
    return raw


def fetch_vercel_error(deployment: str, token: str, team_id: str | None) -> tuple[str, str]:
    query = f"?teamId={urllib.parse.quote(team_id)}" if team_id else ""
    data = _get_json(f"https://api.vercel.com/v13/deployments/{deployment}{query}", token)
    if not isinstance(data, dict):
        return "", ""
    return str(data.get("errorCode") or ""), str(data.get("errorMessage") or "")


def render(report: Report, sha: str) -> str:
    lines = [f"## Vercel deployments for `{sha[:10]}`", ""]
    lines += ["| Project | State |", "| --- | --- |"]
    lines += [f"| {s.project} | {s.state} |" for s in report.statuses]
    lines.append("")
    if not report.findings:
        lines.append("All Vercel deployments are expected and succeeded.")
    for finding in report.findings:
        lines.append(f"- **{finding.level.upper()}** `{finding.project}`: {finding.message}.")
        if finding.detail:
            lines.append(f"  {finding.detail}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    cli.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    cli.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    cli.add_argument("--wait-seconds", type=int, default=900)
    cli.add_argument("--poll-seconds", type=int, default=30)
    args = cli.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not (args.repo and args.sha and token):
        cli.error("--repo, --sha and GITHUB_TOKEN are required")
    expected = json.loads(args.manifest.read_text(encoding="utf-8"))["projects"]

    deadline = time.monotonic() + args.wait_seconds
    while True:
        statuses = latest_vercel_statuses(fetch_statuses(args.repo, args.sha, token))
        pending = [s for s in statuses if s.state == "pending"]
        settled = statuses and not pending and set(expected) <= {s.project for s in statuses}
        if settled or time.monotonic() >= deadline:
            break
        time.sleep(args.poll_seconds)

    details: dict[str, tuple[str, str]] = {}
    vercel_token = os.environ.get("VERCEL_TOKEN", "")
    if vercel_token:
        for status in statuses:
            deployment = deployment_id(status) if status.state in ("failure", "error") else None
            if deployment:
                try:
                    details[status.project] = fetch_vercel_error(
                        deployment, vercel_token, os.environ.get("VERCEL_TEAM_ID") or None)
                except (urllib.error.URLError, ValueError, OSError):
                    details[status.project] = ("", "error details unavailable from the Vercel API")

    report = classify(statuses, expected, details)
    text = render(report, args.sha)
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    for finding in report.findings:
        kind = "error" if finding.level == "error" else "warning"
        print(f"::{kind} title=Vercel {finding.project}::{finding.message}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
