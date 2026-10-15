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

1. Copy `assets/manual_shots_helpers.dart` into `integration_test/` and adapt the two project-specific stubs (secure screen, push permission channel names). It provides `waitFor / waitUntilGone / settle / type / tapText / shot / shotBlind / labelOf` and fake image picker support. Use `type()` for every text field and `tapText()` for taps by label; the reasons are in the pitfalls below.
2. Write `integration_test/manual_shots_test.dart` with one `testWidgets` that switches on a `SHOT_SET` dart-define. A set is one login + a linear path through the screens; each `shot(tester, 'name')` prints the marker. Keep sets small (5–15 shots) so a failure late in a set costs little. Conventions that paid off:
   - First thing in the test: assert the app's base URL contains the test-environment domain. Wrong flavor = zero shots, not 38 shots against production.
   - Steps that write data (generate cards, toggle a POS, submit a form) sit behind dart-defines that default to off (`--dart-define=GEN_CARDS=1`), so a re-run for one fixed shot does not mutate the account again.
   - Segments that need external ids (`UUID_ORDER=…`) are skipped with a printed `[shots] skip <name>` when the define is absent, and a `SKIP_<section>` define skips sections already shot.
   - Navigate by pushing routes through the app's router (`ProviderScope` → GoRouter) when the test only needs to land on a screen; tapping through five menus is slower and breaks with every layout change.
3. Run it with `assets/manual_shots_android.sh` copied to `tool/` (fill in the CONFIG block). It does `pm clear`, starts `scripts/shots_watch.sh` first, grants runtime permissions as soon as the apk is installed, runs `flutter drive --android-skip-build-dependency-validation … --dart-define=SHOT_SET=<set>`, and stops the watcher by its pidfile. By hand that is `bash scripts/shots_watch.sh out/ run.log SERIAL &` then `flutter drive --driver=test_driver/integration_test.dart --target=integration_test/manual_shots_test.dart -d SERIAL --flavor dev --dart-define=SHOT_SET=worker1 2>&1 | tee -a run.log`.
4. Document every set in the project README: account, what it captures, side effects (creates a booking, submits for review), preconditions (account must be in state X).

## Preflight (the watcher enforces these)

- Device **unlocked, screen on**. On a lock screen Flutter produces no frames, `tester.pump()` never returns, and the test hangs silently until the 25-minute timeout. Pattern locks cannot be unlocked by adb. Do not change the device's sleep settings from scripts without asking; the owner may have "stay awake while charging" set.
- `adb exec-out screencap -p` must return a PNG; if it returns 0 bytes the screen is off.
- Start each set from a clean app state (`adb shell pm clear <package>`) so onboarding tours and cached sessions behave the same every run. Note: `flutter drive` uninstalls the app when it finishes, so `pm clear` before the *next* run fails with "Failed" - that is harmless, just run.
- System language of the device = the manual's language. Some apps allow in-app language switching; emulators with production images cannot change locale via adb.

## Pitfalls met on a real device (each cost real time)

- **`tester.enterText` appends on a device.** The IME keeps the field's text, so a second attempt sends `passwordpassword`. With a backend that locks the account after N failures that is a 15-minute wait. `type()` in the helpers taps, clears through the controller, enters, then prints the field length and fails loudly if it differs.
- **Never shoot the "wrong password" screen with a real account.** Use a non-existent account (`nobody@example.com`) so the error renders without a lockout counter ticking on the demo account.
- **`tester.pump(Duration)` does not wait real time** on a device; a "hold 5 s" loop of pumps returns in milliseconds and the host screencap captures the next screen. `settle()` adds a real `Future.delayed` per tick; keep `SHOT_HOLD` at 6 s on USB devices.
- **`find.text(name).first` hits the search box** you just typed into, not the list card. `tapText()` takes `.last`; for ambiguous lists use `find.descendant(of: find.byType(Card), matching: find.text(name))`.
- **Off-screen ListView items** are found but not tappable (lazy build + hit test). `tester.ensureVisible()` first; `tapText()` does it.
- **Gradle/AGP version check** stops `flutter drive` on projects that pin older Gradle: pass `--android-skip-build-dependency-validation`. Some Flutter versions also rewrite `android/gradle.properties` and `analysis_options.yaml` on the first drive; check `git status` before committing.
- **Runtime permission dialogs** (camera) are native and cover the frame. Grant them with `adb shell pm grant <pkg> android.permission.CAMERA` as soon as the apk is installed; the template script polls `pm path` for that moment because `flutter drive` installs and launches in one go.
- **Watcher leftovers.** A `tail -F | while` pipeline survives `kill` of the script and keeps writing; four runs left four watchers appending to the same files, and truncating the log while `tee` held it open filled it with NUL bytes. `shots_watch.sh` now records a pidfile, kills a stale instance, traps its own tail, never truncates the log, and resets each `<name>.txt` the first time a name appears in a run. Give the watcher its own output file; do not share `run.log` between `tee` and the watcher.

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
