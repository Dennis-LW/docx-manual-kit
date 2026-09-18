# Mobile app screenshots (Flutter integration_test + adb)

Goal: dozens of consistent, production-looking screenshots of a real app build, repeatable next sprint. Driving the UI from an integration test gives exact navigation; taking the picture from the host with the platform's native screenshot gives real status bars, dialogs, shadows and system UI (in-test `takeScreenshot` misses native views and dialogs).

## The pattern

```
integration test (on device)                    host
──────────────────────────────                  ──────────────────────────────
navigate, wait until ready
debugPrint('[shots] ready app_home')  ──log──►  shots_watch.sh: sleep 1.5s,
                                                adb exec-out screencap -p > app_home.png
debugPrint('[shots] text app_home …') ──log──►  append to app_home.txt (copy check)
hold 5 s so the frame stays up
```

1. Copy `assets/manual_shots_helpers.dart` into `integration_test/` and adapt the two project-specific stubs (secure screen, push permission channel names). It provides `waitFor / waitUntilGone / settle / shot / shotBlind / labelOf` and fake image picker support.
2. Write `integration_test/manual_shots_test.dart` with one `testWidgets` that switches on a `SHOT_SET` dart-define. A set is one login + a linear path through the screens; each `shot(tester, 'name')` prints the marker. Keep sets small (5–15 shots) so a failure late in a set costs little.
3. Run: `bash scripts/shots_watch.sh out/ run.log SERIAL &` then `flutter drive --driver=test_driver/integration_test.dart --target=integration_test/manual_shots_test.dart -d SERIAL --flavor dev --dart-define=SHOT_SET=worker1 2>&1 | tee run.log`. Wrap both in a project script (`tool/manual_shots_android.sh <set> <out-dir>`) with the preflight checks below.
4. Document every set in the project README: account, what it captures, side effects (creates a booking, submits for review), preconditions (account must be in state X).

## Preflight (the watcher enforces these)

- Device **unlocked, screen on**. On a lock screen Flutter produces no frames, `tester.pump()` never returns, and the test hangs silently until the 25-minute timeout. Pattern locks cannot be unlocked by adb. Do not change the device's sleep settings from scripts without asking; the owner may have "stay awake while charging" set.
- `adb exec-out screencap -p` must return a PNG; if it returns 0 bytes the screen is off.
- Start each set from a clean app state (`adb shell pm clear <package>`) so onboarding tours and cached sessions behave the same every run. Note: `flutter drive` uninstalls the app when it finishes, so `pm clear` before the *next* run fails with "Failed" - that is harmless, just run.
- System language of the device = the manual's language. Some apps allow in-app language switching; emulators with production images cannot change locale via adb.

## Test-side techniques that keep it working

- **`pumpAndSettle` hangs** on any perpetual animation (skeleton shimmer, spinners). Use a polling `waitFor(finder, timeout)` that pumps 250 ms at a time; drain `takeException()` each loop so background errors do not fail the test.
- **`FLAG_SECURE` screens screenshot black.** Stub the platform channel that sets the flag (`setMockMethodCallHandler(channel, (_) async => null)`) before `app.main()`.
- **Permission prompts** (push notifications) are native dialogs: stub the plugin channel to return "granted" so they never appear, or take the shot with `back: true` so the watcher dismisses them after capture.
- **Image pickers**: replace `ImagePickerPlatform.instance` with a fake returning an in-memory `XFile` (embed a small base64 PNG) - far more stable than mocking pigeon channels.
- **Rich-text labels** (`RichText` with a red "(required)" suffix) are not found by `find.text`; match on `RichText.text.toPlainText()`.
- **`scrollUntilVisible` may throw** `Bad state: No element` on nested scrollables; use `tester.ensureVisible()`.
- **Dialogs closing**: after picking a date in a dialog, `waitUntilGone(dialogFinder)` before tapping the next thing, or the tap lands on the fading dialog.
- **In-app browsers / Custom Tabs** cover the Flutter tree; you cannot pump. Use `shotBlind(name, back: true)` which just prints the marker and sleeps, and let the watcher press BACK.
- **Localised strings**: read them from the generated localizations (`AppLocalizations.of(context)`) instead of hard-coding, so the same test works when the manual is shot in another language.
- **Which screen am I on?** Have `shot()` also dump all visible texts as `text` markers; the `.txt` next to each PNG lets you grep for wording changes and confirm the capture without opening images.
- Widget buttons with `minimumSize: Size.fromHeight(h)` (infinite width) inside a `Row` crash at runtime; if a screenshot run explodes on a dialog, that is the first thing to check.

## Data

Runs mutate the test backend (bookings, submissions, generated codes). Use dedicated demo accounts and know the API calls that reset their state (e.g. `PATCH /members/:id` to send a profile back to "pending", `POST …/approve` to restore). Some accounts are only good for one path (an "incomplete profile" account stops being incomplete after the run) - keep a spare or a reset recipe.

## iOS

Same pattern with `xcrun simctl io booted screenshot out.png` on the simulator (store screenshots typically use the simulator; manuals for iOS operators can too). Physical iPhones cannot be screenshotted from the host without additional tooling; prefer Android for manuals unless the client is iOS-only.

## Post-processing

- Manuals usually embed the full frame (status bar included) downscaled to a fixed pixel size; keep originals.
- `scripts/trim_screenshot.py --auto-status-bar` crops the bars when the client asks for a cleaner look. Apply uniformly to all figures of a manual or none.
- Build a contact sheet (Pillow) of a run's output before inserting anything; it is the fastest way to catch a wrong state or an unexpected dialog.
