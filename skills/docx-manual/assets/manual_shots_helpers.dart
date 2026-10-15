// Shared helpers for manual-screenshot integration tests.
// Copy into <app>/integration_test/ and adapt the two TODO stubs.
// Pattern: the test prints `[shots] ready <name>` when a screen is ready and
// scripts/shots_watch.sh on the host takes a native screenshot.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
// ignore: depend_on_referenced_packages
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';

/// Marker prefix; must match SHOT_MARK of shots_watch.sh.
const String kShotMark = '[shots]';

/// Seconds a screen is held after the marker so the host has time to capture.
/// 6 s is what a real device over USB needs: `adb exec-out screencap` takes
/// 1-2 s itself and the watcher sleeps SHOT_DELAY first. Lower it only on an
/// emulator, and never below 3.
const int kHoldSeconds = int.fromEnvironment('SHOT_HOLD', defaultValue: 6);

/// Background errors (image decode, network) must not fail a screenshot run.
void drainErrors(WidgetTester tester) {
  Object? ex;
  while ((ex = tester.takeException()) != null) {
    debugPrint('$kShotMark ignored background error: $ex');
  }
}

/// `pumpAndSettle` hangs on perpetual animations (skeleton shimmer); poll instead.
Future<void> waitFor(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 40),
  String? what,
}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 250));
    drainErrors(tester);
    if (finder.evaluate().isNotEmpty) return;
  }
  fail('timeout waiting for ${what ?? finder.toString()}');
}

Future<bool> waitForOptional(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 10),
}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 250));
    drainErrors(tester);
    if (finder.evaluate().isNotEmpty) return true;
  }
  return false;
}

/// Wait for a dialog/picker to leave the tree before tapping what is under it.
Future<void> waitUntilGone(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 40),
  String? what,
}) async {
  final end = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 250));
    drainErrors(tester);
    if (finder.evaluate().isEmpty) return;
  }
  debugPrint('$kShotMark WARN still present: ${what ?? finder.toString()}');
}

/// Hold the frame for real wall-clock time. On a device `tester.pump(d)`
/// only advances the test clock and returns at once, so a loop of pumps
/// finishes in milliseconds and the host screencap lands on the *next*
/// screen (two "list" shots that both show the state after the toggle).
/// The `Future.delayed` is what actually waits.
Future<void> settle(WidgetTester tester, [int seconds = 3]) async {
  for (var i = 0; i < seconds * 4; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    await Future<void>.delayed(const Duration(milliseconds: 250));
    drainErrors(tester);
  }
}

/// Type into a text field, replacing whatever is there.
///
/// On a real device `tester.enterText` *appends* to the field's current
/// value (the IME keeps its composing state), so a second login attempt
/// sends "passwordpassword" and a few of those lock the account for 15
/// minutes. Tap first, clear through the controller when there is one, then
/// enter the text, and print the resulting length so the log shows what was
/// really submitted (never the text itself).
Future<void> type(WidgetTester tester, Finder field, String text,
    {String? what}) async {
  await tester.ensureVisible(field);
  await tester.tap(field);
  await tester.pump(const Duration(milliseconds: 300));
  final widget = field.evaluate().single.widget;
  final controller = widget is TextField
      ? widget.controller
      : widget is TextFormField
          ? widget.controller
          : null;
  controller?.clear();
  await tester.enterText(field, text);
  await tester.pump(const Duration(milliseconds: 300));
  final len = controller?.text.length ?? -1;
  debugPrint('$kShotMark typed ${what ?? field.toString()} '
      '(${text.length} chars, field now $len)');
  if (len >= 0 && len != text.length) {
    fail('${what ?? field} holds $len chars after typing ${text.length}; '
        'enterText appended instead of replacing');
  }
}

/// Tap a widget by its text when the same text may appear more than once.
///
/// After typing a name into a search box, `find.text(name).first` hits the
/// search box, not the result card, so take the last match by default. Items
/// of a lazy ListView that are off-screen are found by `find.text` but not
/// hit-testable; `ensureVisible` scrolls them in first.
Future<void> tapText(WidgetTester tester, String text,
    {bool last = true}) async {
  final f = last ? find.text(text).last : find.text(text).first;
  await tester.ensureVisible(f);
  await tester.pump(const Duration(milliseconds: 200));
  await tester.tap(f);
  await tester.pump(const Duration(milliseconds: 300));
}

String _flat(String s) => s.replaceAll('\n', ' ').trim();

/// Dump all visible texts as `text` markers → `<name>.txt` on the host, so
/// wording can be checked with grep instead of opening every image.
void _dumpTexts(WidgetTester tester, String name) {
  final seen = <String>{};
  for (final e in find.byType(RichText).evaluate()) {
    final w = e.widget as RichText;
    final s = _flat(w.text.toPlainText());
    if (s.isEmpty || !seen.add(s)) continue;
    debugPrint('$kShotMark text $name $s');
  }
}

/// Print the ready marker and hold the frame. [back] asks the host to press
/// BACK after capturing (native permission dialogs, in-app browsers).
Future<void> shot(
  WidgetTester tester,
  String name, {
  bool back = false,
  int? hold,
}) async {
  await settle(tester, 2);
  _dumpTexts(tester, name);
  debugPrint('$kShotMark ready $name${back ? ' +back' : ''}');
  await settle(tester, hold ?? kHoldSeconds);
}

/// When a native view (Custom Tab) covers Flutter there is no tree to pump.
Future<void> shotBlind(String name, {bool back = false, int hold = 8}) async {
  debugPrint('$kShotMark ready $name${back ? ' +back' : ''}');
  await Future<void>.delayed(Duration(seconds: hold));
}

/// TODO(project): FLAG_SECURE screens screenshot black. Stub the channel your
/// app uses to set the flag, e.g. `const MethodChannel('com.example/secure_screen')`.
void stubSecureScreen(WidgetTester tester, MethodChannel channel) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    channel,
    (call) async => null,
  );
}

/// TODO(project): keep the native push-permission prompt from appearing.
void stubPushPermission(WidgetTester tester) {
  const channel = MethodChannel('plugins.flutter.io/firebase_messaging');
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
    call,
  ) async {
    if (call.method == 'Messaging#requestPermission' ||
        call.method == 'Messaging#getNotificationSettings') {
      return <String, int>{
        'authorizationStatus': 0,
        'alert': 0,
        'announcement': 0,
        'badge': 0,
        'carPlay': 0,
        'lockScreen': 0,
        'notificationCenter': 0,
        'showPreviews': 0,
        'timeSensitive': 0,
        'criticalAlert': 0,
        'sound': 0,
        'providesAppNotificationSettings': 0,
      };
    }
    return null;
  });
}

/// Fake image picker returning an embedded PNG; more stable than mocking pigeon.
class FakeImagePicker extends ImagePickerPlatform {
  FakeImagePicker(this.bytes, this.filename);

  final Uint8List bytes;
  final String filename;

  @override
  Future<XFile?> getImageFromSource({
    required ImageSource source,
    ImagePickerOptions options = const ImagePickerOptions(),
  }) async => XFile.fromData(bytes, name: filename, mimeType: 'image/png');
}

void stubImagePicker(String base64Png, String filename) {
  ImagePickerPlatform.instance = FakeImagePicker(
    base64Decode(base64Png),
    filename,
  );
}

/// Labels rendered as RichText (label + red "(required)") are invisible to
/// `find.text`; match on the plain text instead.
Finder labelOf(String label) => find.byWidgetPredicate(
  (w) => w is RichText && w.text.toPlainText().startsWith(label),
);
