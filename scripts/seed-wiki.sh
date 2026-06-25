#!/usr/bin/env bash
# Seed (or update) the GitHub wiki from docs/wiki/.
#
# ONE-TIME PREREQUISITE: GitHub does not expose an API to create the *first* wiki page, and the
# .wiki.git repo does not exist until one page exists. So once, in the browser:
#     https://github.com/3MagicLabs/Grandplan/wiki  ->  "Create the first page"  ->  save anything.
# That initializes the wiki repo. After that, this script pushes every page in docs/wiki/ and can be
# re-run any time to keep the wiki in sync with the repo.
#
# Usage:  scripts/seed-wiki.sh [owner/repo]   (default: 3MagicLabs/Grandplan)
set -euo pipefail

REPO="${1:-3MagicLabs/Grandplan}"
SRC="$(cd "$(dirname "$0")/../docs/wiki" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! git clone --quiet "https://github.com/${REPO}.wiki.git" "$TMP" 2>/dev/null; then
  echo "error: cannot clone ${REPO}.wiki.git — create the first wiki page in the browser first" >&2
  echo "       https://github.com/${REPO}/wiki" >&2
  exit 1
fi

cp "$SRC"/*.md "$TMP"/
git -C "$TMP" add -A
if git -C "$TMP" diff --cached --quiet; then
  echo "wiki already up to date with docs/wiki/"
  exit 0
fi
git -C "$TMP" -c user.name=wimaan3 -c user.email=imaansoltan@gmail.com \
  commit --quiet -m "Sync wiki from docs/wiki/"
git -C "$TMP" push --quiet
echo "wiki updated -> https://github.com/${REPO}/wiki"
