# F1 completion notification (GitHub, not ChatGPT Tasks)

This repository includes a **quiet one-time notification** mechanism. It does
not use a ChatGPT Task or affect the ChatGPT task limit. GitHub Actions runs
`.github/workflows/f1-completion-watch.yml` once daily and after relevant
production-branch pushes. When **every** checked release criterion succeeds,
it creates **one GitHub issue assigned to `realjkg`**. GitHub can deliver
notifications for assigned issues according to the account's GitHub
notification settings. This is a GitHub notification, **not** a ChatGPT push
notification or a promised email delivery.

## What must be true before notification

1. The playable Grand Prix Challenge PR #47 is merged.
2. The Vercel production alias serves the updated `Start Challenge` game
   bundle, engine configuration, completed-round catalog, classified result,
   and functioning engine-scored game endpoint.
3. The chosen current race is configured, and real OpenF1 MQTT packets are
   reaching the private collector over a verified TLS 1.3 connection.
4. The backend reports a fresh, fully identified licensed-live lap checkpoint,
   with exact matching season/race/lap/digest across source trace and scenario.
5. Its inference is production-qualified and promoted — not merely an
   experimental green-pace simulation. A forward accuracy/calibration report
   must permit promotion and provide a SHA-256 evidence digest.
6. The operator has affirmatively recorded that the live-data rights permit
   this production-public exposure. A string in the collector's trace alone
   is not a substitute for contractual approval.

No report is sent for a merged PR alone, a successful Vercel build, a painted
animation, stale historical replay, or a missing licensed subscription. The
watcher never connects to OpenF1 itself and does not receive OpenF1 passwords.

## One-time settings in the GitHub repository

Under **Settings → Secrets and variables → Actions**, configure the following
repository **variables** using verified production settings:

| Variable | Value |
| --- | --- |
| `F1_PITWALL_ORIGIN` | `https://f1-pitwall-demo.vercel.app` |
| `F1_LIVE_SEASON` | The actual live session year |
| `F1_LIVE_RACE_ID` | The active live backend's verified race slug |
| `F1_OPENF1_PUBLIC_RIGHTS_APPROVED` | `true` **only after written rights approval** |

If production is protected by Vercel Deployment Protection, configure the
repo **secret** `VERCEL_AUTOMATION_BYPASS_SECRET` (the matching bypass secret
from Vercel). Do not copy that secret into issues, logs, chats, commits or
browser-side environment variables. Without sufficient access, the watcher
refuses completion instead of bypassing protection.

The GITHUB_TOKEN is automatically provided to the workflow and has only
`issues: write`, `pull-requests: read`, and `contents: read` permissions.
No personal access token is needed. Review repository rules that may restrict
GitHub Actions from creating issues or assigning maintainers.

## Where the completion notice goes

A GitHub issue titled
`F1 Pit Wall complete: playable game and qualified OpenF1 inference`,
assigned to `realjkg`, containing the verified live session, deployed site
and proof digests. A unique marker prevents duplicate issues across scheduled
checks. To receive an **email**, enable GitHub email notifications for
assignment and repository activity in your GitHub notification preferences.

## Current limitations

At the time of this change, PR #47 is not merged, the public Vercel
deployment uses older code, and production-qualified OpenF1 inference is
**not running**. The current live API also does **not** expose a negotiated
`mqttTlsVersion` or a true production model promotion flag. Future engine
work must implement and verify those fields before this alert can fire.

The scheduled check does not install dependencies, train models, deploy
infrastructure, issue forecasts, or spend on inference. Each run uses a
limited GitHub Actions job; it may count against GitHub Actions minutes.

Manual test: **GitHub → Actions → F1 verified completion alert → Run workflow**
after merging the workflow to the default branch. The check exits normally
and prints a concise **No completion alert** reason while incomplete.
