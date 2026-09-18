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
const int kHoldSeconds = int.fromEnvironment('SHOT_HOLD', defaultValue: 5);

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

Future<void> settle(WidgetTester tester, [int seconds = 3]) async {
  for (var i = 0; i < seconds * 4; i++) {
    await tester.pump(const Duration(milliseconds: 250));
    drainErrors(tester);
  }
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
