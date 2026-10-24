#!/bin/sh
# Vercel "Ignored Build Step" contract:
#   exit 0 -> skip this deployment; exit 1 -> perform this deployment.
# Only f1-pitwall-demo is the approved unified F1 app deployment.
# CI still tests Dependabot changes; merging to main creates a new build.
set -eu

branch=${VERCEL_GIT_COMMIT_REF:-}
case "$branch" in
  dependabot/*|renovate/*)
    printf '%s\n' 'Skip preview: automated dependency update is validated in GitHub CI.'
    exit 0
    ;;
  '')
    printf '%s\n' 'Skip preview: Git branch metadata is unavailable.'
    exit 0
    ;;
  *)
    printf 'Proceed with canonical F1 deployment for branch: %s\n' "$branch"
    exit 1
    ;;
esac
