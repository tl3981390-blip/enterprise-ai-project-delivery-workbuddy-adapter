#!/usr/bin/env bash
# POSIX-safe path handling: Git Bash strips backslashes in unquoted
# assignments, so all embedded Windows paths use forward slashes and quotes.
set -u
ADAPTER="C:/Users/34718/WorkBuddy/2026-09-02-19-07-11/enterprise-ai-project-delivery-workbuddy-adapter"
PROJ="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJ" || exit 1
REL=".codebuddy/bridge/artifacts"
mkdir -p "$REL"
( cd "$ADAPTER" && "C:/Users/34718/.workbuddy/binaries/python/versions/3.13.12/python.exe" -B -m pytest -q ) 2>&1 | tee "$REL/canonical-pytest.log"
echo "canonical-pytest log: $REL/canonical-pytest.log"
