#!/usr/bin/env bash
# Real git-state report produced while FOLLOWING the git-state-change-regression
# skill flow (the model must genuinely load that skill first, per CLAUDE.md).
set -u
PROJ="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJ" || exit 1
REL=".codebuddy/bridge/artifacts"
mkdir -p "$REL"
HEAD="$(git rev-parse --verify HEAD 2>/dev/null | tr -d '\r\n' || true)"
test -n "$HEAD" || HEAD="unknown"
DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
test "$HEAD" != "unknown" && VERDICT="PASS" || VERDICT="FAIL"
"C:/Users/34718/.workbuddy/binaries/python/versions/3.13.12/python.exe" - "$REL/git-state-skill-report.json" "$HEAD" "$DIRTY" "$VERDICT" <<'PY'
import json, sys, time
out, head, dirty, verdict = sys.argv[1:5]
json.dump({"verdict": verdict, "git_head": head, "dirty_files": int(dirty),
           "skill": "git-state-change-regression",
           "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("git-state-skill-report written verdict=" + verdict)
PY
echo "exit=$?"
ls -l "$REL/git-state-skill-report.json"
