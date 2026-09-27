#!/usr/bin/env bash
# Run the UI scripts in this folder, one after another, against an app that is running.
#
#   frontend/tests/run.sh                    every script
#   frontend/tests/run.sh stands insights    only these
#
#   BASE_URL           the app as Vite serves it (it passes /api on)   [http://127.0.0.1:5173]
#   API_URL            the API itself, for map-offline                  [http://127.0.0.1:8000]
#   PLAYWRIGHT_MODULE  where Playwright is, as require() takes it       [playwright]
#   PW_CHANNEL         a browser channel (msedge, chrome); empty, the default, is
#                      Playwright's own Chromium
#   UI_TIMEOUT         seconds one script may take                      [300]
#   UI_LOGS            where each script's output goes                  [a temp folder]
#
# Most scripts answer /api themselves with a fake server, so any running Vite will do.
# access and sit-reports-live sign in to the real API as the demo data's people
# (backend/scripts/demo_data.py); map-offline and never-blank serve the BUILT app, so
# run `npm run build` first. CI does all of it (.github/workflows/ci.yml); README.md
# has the steps for a laptop.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/.."
export BASE_URL="${BASE_URL:-http://127.0.0.1:5173}"
export API_URL="${API_URL:-http://127.0.0.1:8000}"
export PW_CHANNEL="${PW_CHANNEL:-}"
export PLAYWRIGHT_MODULE="${PLAYWRIGHT_MODULE:-playwright}"
limit="${UI_TIMEOUT:-300}"
logs="${UI_LOGS:-$(mktemp -d)}"
mkdir -p "$logs"

if [ $# -gt 0 ]; then names=("$@"); else names=(); for f in tests/*.cjs; do names+=("$(basename "$f" .cjs)"); done; fi
if [ ! -f dist/index.html ]; then
  echo "note: no dist/ (npm run build): map-offline and never-blank will fail"
fi

passed=(); failed=()
for name in "${names[@]}"; do
  start=$(date +%s)
  if timeout "$limit" node "tests/$name.cjs" > "$logs/$name.log" 2>&1; then
    passed+=("$name"); echo "pass  $name ($(( $(date +%s) - start ))s)"
  else
    failed+=("$name"); echo "FAIL  $name ($(( $(date +%s) - start ))s) - $logs/$name.log"
    tail -n 15 "$logs/$name.log" | sed 's/^/      /'
  fi
done
echo
echo "${#passed[@]} passed, ${#failed[@]} failed (logs in $logs)"
[ ${#failed[@]} -eq 0 ]
