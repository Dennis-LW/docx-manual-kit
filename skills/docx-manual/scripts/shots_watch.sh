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
# Usage:
#   bash shots_watch.sh out run.log &
#   flutter drive --driver=test_driver/integration_test.dart \
#     --target=integration_test/manual_shots_test.dart -d "$DEVICE" 2>&1 | tee run.log
#   wait   # or kill the watcher when the drive finishes
#
#   bash shots_watch.sh OUT_DIR LOG_FILE [ADB_SERIAL]
#
# Environment:
#   SHOT_MARK   marker prefix (default "[shots]")
#   SHOT_DELAY  seconds to wait before screencap (default 1.5)
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
: > "$LOG" 2>/dev/null || true

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

tail -n +1 -F "$LOG" 2>/dev/null | while IFS= read -r line; do
  if [[ "$line" =~ ${MARK_RE}\ text\ ([A-Za-z0-9_.-]+)\ (.*)$ ]]; then
    printf '%s\n' "${BASH_REMATCH[2]}" >> "$OUT/${BASH_REMATCH[1]}.txt"
    echo "[text] ${BASH_REMATCH[1]}"
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
