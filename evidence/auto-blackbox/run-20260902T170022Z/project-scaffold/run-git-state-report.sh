#!/usr/bin/env bash
set -u
PROJ="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJ" || exit 1
REL=".codebuddy/bridge/artifacts"
mkdir -p "$REL"
HEAD="$(git rev-parse --verify HEAD 2>/dev/null | tr -d '\r\n' || true)"
test -n "$HEAD" || HEAD="unknown"
DIRTY="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
test "$HEAD" != "unknown" && VERDICT="PASS" || VERDICT="FAIL"
"C:/Users/34718/.workbuddy/binaries/python/versions/3.13.12/python.exe" - "$REL/git-state-report.json" "$HEAD" "$DIRTY" "$VERDICT" <<'PY'
import json, sys, time
out, head, dirty, verdict = sys.argv[1:5]
json.dump({"verdict": verdict, "git_head": head, "dirty_files": int(dirty),
           "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("git-state-report written verdict=" + verdict, "head=", head[:12])
PY
echo "exit=$?"
ls -l "$REL/git-state-report.json"
