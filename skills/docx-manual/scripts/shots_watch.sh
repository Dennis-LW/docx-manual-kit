#!/usr/bin/env bash
# shots_watch.sh — capture Android screenshots driven by markers in a log file.
#
# Tails LOG_FILE and reacts to two marker lines (prefix from $SHOT_MARK,
# default "[shots]"):
#
#   [shots] ready <name>          -> adb exec-out screencap -p > OUT_DIR/<name>.png
#   [shots] ready <name> +back    -> same, then send BACK (in-app browser,
#                                    native permission dialogs)
#   [shots] text <name> <text>    -> append <text> to OUT_DIR/<name>.txt
#
# The capture happens $SHOT_DELAY seconds (default 1.5) after the marker, to let
# animations settle.
#
# Usage (or use assets/manual_shots_android.sh, which wraps all of this):
#   bash shots_watch.sh out run.log &
#   flutter drive --driver=test_driver/integration_test.dart \
#     --target=integration_test/manual_shots_test.dart -d "$DEVICE" 2>&1 | tee run.log
#   kill "$(cat out/.shots_watch.pid)"   # when the drive finishes
#
#   bash shots_watch.sh OUT_DIR LOG_FILE [ADB_SERIAL]
#
# Environment:
#   SHOT_MARK   marker prefix (default "[shots]")
#   SHOT_DELAY  seconds to wait before screencap (default 1.5)
#
# Start the watcher BEFORE flutter drive: it only follows lines appended after
# it starts, and it never truncates LOG_FILE - truncating a file that tee
# already holds open leaves a run of NUL bytes in it. It writes its
# pid to OUT_DIR/.shots_watch.pid and kills a stale watcher found there, so
# the usual "4 leftover watchers after 3 runs" cannot happen; killing the
# watcher also kills its tail (trap), unlike a plain `tail | while` pipeline.
# <name>.txt is truncated the first time a name shows up in a run, so text
# dumps do not accumulate across runs.
#
# Exit 2 preflight failures: a locked or sleeping device. That matters because
# Flutter produces no frames while the screen is off, so `tester.pump()` never
# returns and the whole test run hangs — and `screencap` returns 0 bytes.
set -uo pipefail

OUT="${1:?usage: shots_watch.sh OUT_DIR LOG_FILE [ADB_SERIAL]}"
LOG="${2:?usage: shots_watch.sh OUT_DIR LOG_FILE [ADB_SERIAL]}"
DEV="${3:-}"
MARK="${SHOT_MARK:-[shots]}"
DELAY="${SHOT_DELAY:-1.5}"

ADB=(adb)
[ -n "$DEV" ] && ADB=(adb -s "$DEV")

mkdir -p "$OUT"
touch "$LOG" 2>/dev/null || true
# Follow the log from its size *now*: lines appended while the preflight below
# runs (about 1.5 s) are still seen, lines from an earlier run are not.
START=$(stat -f%z "$LOG" 2>/dev/null || stat -c%s "$LOG" 2>/dev/null || echo 0)

# ---- one watcher per OUT_DIR: kill a stale one, record ourselves ----------
PIDFILE="$OUT/.shots_watch.pid"
if [ -f "$PIDFILE" ]; then
  old=$(cat "$PIDFILE" 2>/dev/null || true)
  if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
    echo "[watch] killing stale watcher pid $old"
    kill "$old" 2>/dev/null; sleep 0.5
  fi
fi
echo $$ > "$PIDFILE"

# ---- preflight: tooling first, so a missing adb is not reported as a locked
# device (every adb call below is silenced) --------------------------------
if ! command -v adb >/dev/null 2>&1; then
  echo "ERROR: adb not found on PATH. Install Android platform-tools (macOS: brew install --cask android-platform-tools) and re-run." >&2
  exit 3
fi
if ! "${ADB[@]}" get-state >/dev/null 2>&1; then
  echo "ERROR: no device reachable via adb${DEV:+ (serial $DEV)}; check 'adb devices'." >&2
  exit 3
fi

# ---- preflight: wake the device and make sure it is not locked -------------
"${ADB[@]}" shell input keyevent 224 >/dev/null 2>&1   # KEYCODE_WAKEUP
sleep 1
if "${ADB[@]}" shell dumpsys window policy 2>/dev/null | grep -q "showing=true"; then
  echo "ERROR: device is on the lock screen; unlock it and re-run." >&2
  exit 2
fi
if ! "${ADB[@]}" exec-out screencap -p 2>/dev/null | head -c 8 | grep -q PNG; then
  echo "ERROR: screencap returned no PNG (screen off or locked); unlock and re-run." >&2
  exit 2
fi

# escape the marker for use inside a bash regex
MARK_RE=$(printf '%s' "$MARK" | sed 's/[][\\.^$*+?(){}|]/\\&/g')

echo "[watch] out=$OUT log=$LOG mark=$MARK delay=${DELAY}s${DEV:+ device=$DEV}"

SEEN_TXT=" "   # names whose .txt was already reset in this run (bash 3.2 safe)
cleanup() {
  [ -n "${TAIL_PID:-}" ] && kill "$TAIL_PID" 2>/dev/null
  [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ] && rm -f "$PIDFILE"
}
trap cleanup EXIT INT TERM

# process substitution instead of `tail | while`: the loop runs in this shell,
# so $TAIL_PID is known and the trap can kill it when we are killed.
exec 3< <(tail -c +$((START + 1)) -F "$LOG" 2>/dev/null)
TAIL_PID=$!

while IFS= read -r line <&3; do
  if [[ "$line" =~ ${MARK_RE}\ text\ ([A-Za-z0-9_.-]+)\ (.*)$ ]]; then
    name="${BASH_REMATCH[1]}"
    case "$SEEN_TXT" in
      *" $name "*) ;;
      *) : > "$OUT/$name.txt"; SEEN_TXT="$SEEN_TXT$name " ;;
    esac
    printf '%s\n' "${BASH_REMATCH[2]}" >> "$OUT/$name.txt"
    echo "[text] $name"
  elif [[ "$line" =~ ${MARK_RE}\ ready\ ([A-Za-z0-9_.-]+)(\ \+back)? ]]; then
    name="${BASH_REMATCH[1]}"; back="${BASH_REMATCH[2]:-}"
    sleep "$DELAY"
    if "${ADB[@]}" exec-out screencap -p > "$OUT/$name.png" 2>/dev/null \
       && [ -s "$OUT/$name.png" ]; then
      echo "[capture] $OUT/$name.png"
    else
      echo "[capture FAILED] $name" >&2
    fi
    if [ -n "$back" ]; then
      sleep 0.5
      "${ADB[@]}" shell input keyevent 4 >/dev/null 2>&1
      echo "[back] after $name"
    fi
  fi
done
