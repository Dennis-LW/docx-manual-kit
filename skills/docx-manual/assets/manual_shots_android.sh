#!/usr/bin/env bash
# Shoot one manual screenshot set on the attached Android device.
# Copy to <app>/tool/manual_shots_android.sh and fill in the CONFIG block.
#
#   tool/manual_shots_android.sh <set> [extra --dart-define=K=V ...]
#   SERIAL=emulator-5554 OUT=../manuals/app/images tool/manual_shots_android.sh staff
#
# What it does, in order, and why each step exists:
#   1. pm clear            - onboarding tours and cached sessions behave the same every run
#   2. start shots_watch   - the host-side watcher must be up before the first marker
#                            (it kills a stale watcher from a previous run by itself)
#   3. grant permissions   - polls until flutter drive has installed the apk, then
#                            `pm grant`s CAMERA etc. so no native dialog covers a shot
#   4. flutter drive       - with --android-skip-build-dependency-validation, because
#                            the Gradle/AGP version check refuses to build otherwise
#   5. stop the watcher    - by its pidfile, so no `tail -F` is left behind
#
# Env: SERIAL (adb serial; default = first device), OUT (png/txt dir),
#      SHOTS_WATCH (path to shots_watch.sh), SHOT_HOLD passes through to the test.
set -uo pipefail
cd "$(dirname "$0")/.."

# ---- CONFIG (project specific) ----------------------------------------------
PKG="${PKG:-com.example.app}"                                  # applicationId of the dev flavor
OUT="${OUT:-../manuals/app/images}"                            # where PNG + TXT land
TARGET="integration_test/manual_shots_test.dart"
DRIVER="test_driver/integration_test.dart"
FLAVOR="${FLAVOR:-}"                                           # e.g. dev; empty = none
PERMS="android.permission.CAMERA"                              # space separated, granted after install
# shots_watch.sh lives in the skill; plugin install → $CLAUDE_PLUGIN_ROOT, plain
# skill → ~/.claude/skills, Codex → ~/.codex/skills.
SHOTS_WATCH="${SHOTS_WATCH:-$HOME/.claude/skills/docx-manual/scripts/shots_watch.sh}"
# -----------------------------------------------------------------------------

SET="${1:?usage: manual_shots_android.sh <set> [--dart-define=K=V ...]}"; shift || true
SERIAL="${SERIAL:-$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device"{print $1; exit}')}"
LOG="${LOG:-/tmp/manual_shots_$SET.log}"

[ -n "$SERIAL" ] || { echo "no device (adb devices shows none unlocked/authorised)"; exit 3; }
[ -f "$SHOTS_WATCH" ] || { echo "shots_watch.sh not found at $SHOTS_WATCH; set SHOTS_WATCH"; exit 3; }
mkdir -p "$OUT"

# 1. clean app state ("Failed" here is harmless: flutter drive uninstalls the app at the end)
adb -s "$SERIAL" shell pm clear "$PKG" >/dev/null 2>&1 || true

# 2. watcher first; its own preflight exits 2 (locked) / 3 (no adb) with a message.
#    Watcher output goes to its own file: sharing $LOG with tee corrupts both.
bash "$SHOTS_WATCH" "$OUT" "$LOG" "$SERIAL" > "$LOG.watch" 2>&1 &
WPID=$!
sleep 2
if ! kill -0 "$WPID" 2>/dev/null; then cat "$LOG.watch"; exit 2; fi

# 3. grant runtime permissions as soon as the package is installed
( for _ in $(seq 1 180); do
    if adb -s "$SERIAL" shell pm path "$PKG" 2>/dev/null | grep -q package; then
      for perm in $PERMS; do
        adb -s "$SERIAL" shell pm grant "$PKG" "$perm" >/dev/null 2>&1 \
          && echo "[perm] granted $perm" || echo "[perm] could not grant $perm (not declared?)"
      done
      break
    fi
    sleep 1
  done ) &
GPID=$!

# 4. drive; the log is what the watcher tails, so tee must write it line-buffered
FLAVOR_ARGS=(); [ -n "$FLAVOR" ] && FLAVOR_ARGS=(--flavor "$FLAVOR")
flutter drive --android-skip-build-dependency-validation \
  --driver="$DRIVER" --target="$TARGET" -d "$SERIAL" "${FLAVOR_ARGS[@]}" \
  --dart-define=SHOT_SET="$SET" ${SHOT_HOLD:+--dart-define=SHOT_HOLD=$SHOT_HOLD} "$@" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}

# 5. stop helpers
kill "$GPID" 2>/dev/null
sleep 2
kill "$(cat "$OUT/.shots_watch.pid" 2>/dev/null)" 2>/dev/null || kill "$WPID" 2>/dev/null
wait "$WPID" 2>/dev/null

echo "[done] set=$SET rc=$RC  captured: $(ls "$OUT"/*.png 2>/dev/null | wc -l | tr -d ' ') png in $OUT"
grep -c '\[capture FAILED\]' "$LOG.watch" >/dev/null 2>&1 && echo "[warn] some captures failed, see $LOG.watch"
# flutter drive rewrites android/gradle.properties and analysis_options.yaml on
# some SDK versions; check `git status` before committing.
git status --porcelain -- android/gradle.properties analysis_options.yaml 2>/dev/null | sed 's/^/[git] touched: /'
exit "$RC"
