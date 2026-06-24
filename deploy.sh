#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

GH="$(command -v gh || true)"
if [ -z "$GH" ] && [ -x /tmp/gh/gh_2.65.0_macOS_amd64/bin/gh ]; then
  GH=/tmp/gh/gh_2.65.0_macOS_amd64/bin/gh
fi

if [ -z "$GH" ]; then
  echo "Install GitHub CLI: brew install gh"
  exit 1
fi

if ! "$GH" auth status >/dev/null 2>&1; then
  echo "Logging into GitHub..."
  "$GH" auth login --hostname github.com --git-protocol https --web
fi

REPO_NAME="odessa-crude-tank-app"
USER="$("$GH" api user -q .login)"
REMOTE="https://github.com/${USER}/${REPO_NAME}.git"

if "$GH" repo view "${USER}/${REPO_NAME}" >/dev/null 2>&1; then
  git remote remove origin 2>/dev/null || true
  git remote add origin "$REMOTE"
  git push -u origin main
else
  "$GH" repo create "$REPO_NAME" --public --source=. --remote=origin --push
fi

echo ""
echo "Deployed to: https://github.com/${USER}/${REPO_NAME}"
echo "Next: https://share.streamlit.io → New app → ${REPO_NAME} → crude_tank_app.py"
open "https://share.streamlit.io"