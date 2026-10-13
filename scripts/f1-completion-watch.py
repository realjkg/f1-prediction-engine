#!/usr/bin/env python3
"""Quiet, evidence-gated F1 completion check with a one-time GitHub issue alert.

Runs on the default branch only. Nothing is reported as complete because a
PR merged, a Vercel deployment says READY, or the UI animates a car.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

REPO = "realjkg/f1-prediction-engine"
PR_NUMBER = 47
DEFAULT_ORIGIN = "https://f1-pitwall-demo.vercel.app"
SENTINEL = "<!-- f1-pitwall-verified-completion-v1 -->"
MAX_RESPONSE = 5_000_000


class NotReady(Exception):
    """An expected incomplete or unverified production gate."""


class AssetScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.js_paths: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        values = dict(attrs)
        src = values.get("src")
        if src and re.fullmatch(r"/assets/[a-zA-Z0-9._-]+\\.js", src):
            self.js_paths.append(src)


def _utc(raw: object) -> datetime:
    if not isinstance(raw, str):
        raise NotReady("A required provider timestamp is missing")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise NotReady("A required provider timestamp is invalid") from error
    if value.tzinfo is None:
        raise NotReady("A provider timestamp lacks its UTC offset")
    return value.astimezone(UTC)


def _fresh(raw: object, now: datetime, *, seconds: int = 120) -> bool:
    age = now - _utc(raw)
    return timedelta(seconds=-5) <= age <= timedelta(seconds=seconds)


def verify_qualified_live(
    status: dict, trace: dict, scenario: dict, accuracy: dict,
    *, year: int, race: str, now: datetime,
) -> None:
    """Require genuine live collection plus qualified, evidence-bound inference."""
    if (status.get("season"), status.get("raceId")) != (year, race):
        raise NotReady("Live source identity does not match the verified session")
    if status.get("feedState") != "connected":
        raise NotReady("OpenF1 MQTT collector is not reporting a connected feed")
    if status.get("mqttTlsVersion") != "TLSv1.3":
        raise NotReady("Collector has not attested the negotiated TLS 1.3 session")
    if status.get("evidenceState") != "fresh-checkpoint":
        raise NotReady("There is no fresh source-verified lap checkpoint")
    if status.get("sourceType") != "licensed-live":
        raise NotReady("Lap source is not licensed-live OpenF1")
    if status.get("inferenceState") not in ("qualified", "production-qualified"):
        raise NotReady("Live inference remains experimental or unavailable")
    if status.get("qualifiedForProduction") is not True or status.get("modelPromoted") is not True:
        raise NotReady("The in-race model has not passed the production promotion gate")
    if not _fresh(status.get("lastMessageAt"), now) or not _fresh(
        status.get("lastCheckpointAt"), now
    ):
        raise NotReady("OpenF1 messages or lap inference are stale")
    lap = status.get("lap")
    distance = status.get("totalLaps")
    if type(lap) is not int or type(distance) is not int or not 2 <= lap <= distance:
        raise NotReady("A complete live lap identity is missing")
    digest = status.get("checkpointSha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise NotReady("Verified checkpoint identity is missing")

    checkpoint = trace.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise NotReady("The live lap trace is unavailable")
    if (
        trace.get("recordSha256") != digest
        or checkpoint.get("sourceType") != "licensed-live"
        or checkpoint.get("provider") != "openf1"
        or checkpoint.get("season") != year
        or checkpoint.get("raceId") != race
        or checkpoint.get("lap") != lap
        or checkpoint.get("totalLaps") != distance
        or not checkpoint.get("rightsEvidence")
    ):
        raise NotReady("Live trace does not match source and checkpoint identity")
    if not _fresh(checkpoint.get("observedAt"), now):
        raise NotReady("Checkpoint's provider capture time is stale")
    if (
        scenario.get("checkpointSha256") != digest
        or scenario.get("sourceType") != "licensed-live"
        or scenario.get("status") != "scenario"
        or scenario.get("modelReady") is not True
        or not isinstance(scenario.get("scenario"), dict)
    ):
        raise NotReady("Qualified inference is not bound to this verified OpenF1 lap")
    if accuracy.get("researchOnly") is not False or accuracy.get("modelPromotionAllowed") is not True:
        raise NotReady("Forward accuracy and calibration do not authorize production use")
    if not isinstance(accuracy.get("reportSha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", accuracy["reportSha256"]
    ):
        raise NotReady("An immutable, verified evaluation report is missing")


class Client:
    def __init__(self, origin: str, github_token: str, bypass: str) -> None:
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise NotReady("The configured release origin must be an HTTPS hostname")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise NotReady("The release origin may not contain a path or query")
        self.origin = origin.rstrip("/")
        self.github_token = github_token
        self.bypass = bypass

    def get(self, url: str, *, github: bool = False) -> bytes:
        headers = {"User-Agent": "f1-pitwall-completion-watcher/1", "Accept": "application/json"}
        if github:
            headers.update({
                "Authorization": "Bearer " + self.github_token,
                "X-GitHub-Api-Version": "2022-11-28",
            })
        elif self.bypass:
            headers["x-vercel-protection-bypass"] = self.bypass
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                body = response.read(MAX_RESPONSE + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise NotReady("Release endpoint or GitHub verification is unavailable") from error
        if len(body) > MAX_RESPONSE:
            raise NotReady("A verification response exceeds the allowed size")
        return body

    def json(self, path: str, *, github: bool = False) -> dict:
        base = "https://api.github.com" if github else self.origin
        try:
            value = json.loads(self.get(base + path, github=github))
        except (ValueError, UnicodeError) as error:
            raise NotReady("A release contract returned invalid JSON") from error
        if not isinstance(value, dict):
            raise NotReady("A release contract returned a non-object")
        return value

    def verify_game(self) -> None:
        html = self.get(self.origin + "/").decode("utf-8")
        if 'id="root"' not in html:
            raise NotReady("Vercel production is not serving the expected game application")
        assets = AssetScripts()
        assets.feed(html)
        if not assets.js_paths:
            raise NotReady("Game JavaScript assets are missing from production HTML")
        found_game = False
        for path in assets.js_paths[:8]:
            script = self.get(self.origin + path).decode("utf-8")
            if "START CHALLENGE" in script and "Race the AI. Win the podium." in script:
                found_game = True
                break
        if not found_game:
            raise NotReady("The Grand Prix Challenge UI is not present in production")
        config = self.json("/api/config")
        if not config.get("engineVersion"):
            raise NotReady("The production prediction engine is not responding")
        races = self.json("/api/races").get("races")
        if not isinstance(races, list) or not races:
            raise NotReady("No historical race catalog is available")
        race = next((row for row in races if isinstance(row, dict) and row.get("completed")), None)
        if not race:
            raise NotReady("No completed playable race was served")
        slug, year = race.get("raceId"), race.get("season")
        if not isinstance(slug, str) or type(year) is not int:
            raise NotReady("Historical game race identity is missing")
        escaped_slug = urllib.parse.quote(slug, safe="")
        result = self.json(f"/api/races/{escaped_slug}/result?season={year}")
        podium = result.get("podium")
        if not isinstance(podium, list) or len(podium) != 3 or not all(
            isinstance(driver, str) for driver in podium
        ):
            raise NotReady("The server did not supply a classified podium")
        qs = urllib.parse.urlencode({
            "call": ",".join(podium), "streak_before": 0, "season": year,
        })
        score = self.json(f"/api/races/{escaped_slug}/score?{qs}")
        round_score = score.get("round")
        if not isinstance(round_score, dict) or type(round_score.get("totalPoints")) not in (int, float):
            raise NotReady("The game scoring endpoint is not functional")

    def verify_live(self, year: int, race: str, now: datetime) -> dict:
        params = urllib.parse.urlencode({"season": year, "race_id": race})
        status = self.json(f"/api/live/status?{params}")
        lap = status.get("lap")
        if type(lap) is not int or lap < 2:
            raise NotReady("The deployed API has no active lap inference")
        escaped = urllib.parse.quote(race, safe="")
        params = urllib.parse.urlencode({"season": year, "lap": lap})
        trace = self.json(f"/api/races/{escaped}/lap-trace?{params}")
        scenario = self.json(f"/api/races/{escaped}/lap-scenario?{params}")
        accuracy = self.json("/api/inrace/accuracy")
        verify_qualified_live(
            status, trace, scenario, accuracy, year=year, race=race, now=now,
        )
        return {"lap": lap, "checkpoint": status["checkpointSha256"], "accuracy": accuracy["reportSha256"]}

    def already_notified(self) -> bool:
        for page in range(1, 6):
            items = json.loads(self.get(
                f"https://api.github.com/repos/{REPO}/issues?state=all&per_page=100&page={page}",
                github=True,
            ))
            if not isinstance(items, list):
                raise NotReady("Cannot verify existing completion notices")
            if any(isinstance(item, dict) and SENTINEL in item.get("body", "") for item in items):
                return True
            if len(items) < 100:
                break
        return False

    def create_notice(self, body: str) -> None:
        if self.already_notified():
            print("Completion already notified via GitHub Issue; no repeat.")
            return
        url = f"https://api.github.com/repos/{REPO}/issues"
        payload = json.dumps({
            "title": "F1 Pit Wall complete: playable game and qualified OpenF1 inference",
            "body": SENTINEL + "\n" + body,
            "assignees": ["realjkg"],
        }).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST", headers={
            "Authorization": "Bearer " + self.github_token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "f1-pitwall-completion-watcher/1",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(request, timeout=12) as response:
            notice = json.load(response)
        print("GitHub completion notice created: " + str(notice.get("html_url", "(URL unavailable)")))


def main() -> int:
    origin = os.getenv("F1_PITWALL_ORIGIN", DEFAULT_ORIGIN).strip()
    token = os.getenv("GITHUB_TOKEN", "")
    bypass = os.getenv("VERCEL_AUTOMATION_BYPASS_SECRET", "")
    year_input = os.getenv("F1_LIVE_SEASON", "")
    race = os.getenv("F1_LIVE_RACE_ID", "").strip()
    rights_approved = os.getenv("F1_OPENF1_PUBLIC_RIGHTS_APPROVED", "").strip()
    try:
        if not token:
            raise NotReady("GitHub issue permission is not configured")
        if rights_approved != "true":
            raise NotReady("Public live-data rights have not been explicitly approved")
        if not re.fullmatch(r"20[0-9]{2}", year_input) or not re.fullmatch(r"[a-z0-9_-]{1,100}", race):
            raise NotReady("Verified live season and race ID have not been configured")
        client = Client(origin, token, bypass)
        pull = client.json(f"/repos/{REPO}/pulls/{PR_NUMBER}", github=True)
        if pull.get("merged_at") is None:
            raise NotReady("The Grand Prix Challenge PR is not yet merged")
        client.verify_game()
        proof = client.verify_live(int(year_input), race, datetime.now(UTC))
        body = (
            "Both release gates were verified against the deployed production site.\n\n"
            f"- **Production site:** {client.origin}\n"
            f"- **Game:** Start Challenge UI, completed races and scoring endpoint verified\n"
            f"- **Live:** OpenF1 MQTT TLS 1.3, session {year_input}/{race}, lap {proof['lap']}\n"
            f"- **Checkpoint SHA-256:** \`{proof['checkpoint']}\`\n"
            f"- **Forward evaluation SHA-256:** \`{proof['accuracy']}\`\n"
            "- **Model:** production qualified and promoted according to the engine contract\n\n"
            "Confirm licensing and source provenance again before externally announcing the release.\n"
        )
        client.create_notice(body)
    except NotReady as error:
        print("No completion alert: " + str(error))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # In particular, issue creation failure must be visible as a failed
        # workflow rather than a false claim of notification.
        print("Notification delivery failed; see GitHub Actions error status.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
