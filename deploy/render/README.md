# Pit Wall on Render (free demo)

`render.yaml` deploys the same image as the Vercel demo: the React app, the
read-only API, the frozen historical ledger, and the synthetic `demo-synthetic`
race in the Live Lab. Nothing is live and nothing needs a secret.

## Deploy

1. In Render, choose New > Blueprint and select `realjkg/f1-prediction-engine`.
2. Pick the reviewed branch or commit. Auto-deploy is off; deploy manually.
3. When it is up, check it over the network: `python3 scripts/check-public-demo.py https://<your-service>.onrender.com`

## What the free plan means

Per Render's documentation at the time of writing: a free web service sleeps
after 15 minutes without traffic and takes about a minute to wake, has no
persistent disk, and shares 750 free instance hours a month across the
workspace. Outbound traffic is blocked only on the mail ports (25, 465, 587),
so MQTT on 8883 is not blocked by policy. Recheck these limits before relying on them.

Because it sleeps and cannot keep files, the free plan cannot run the live
ingest. For a real session, move to a paid instance with a disk (the API and
ingest must share one) and the private collector settings in
`docs/GAME_AND_LIVE_SERVICE.md`. Watch memory during a dry run: the API alone
uses about 230 MB, and the smallest paid plan has 512 MB.

## Boundaries

Render terminates HTTPS at its edge, so browser TLS 1.3-only cannot be
enforced here, the same accepted boundary as Vercel. The data licenses in
`data/snapshot/DATA_LICENSE.md` still apply: non-commercial.
