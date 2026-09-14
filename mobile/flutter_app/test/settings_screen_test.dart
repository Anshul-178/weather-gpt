import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:weathergpt/models/weather.dart';
import 'package:weathergpt/providers/app_state.dart';
import 'package:weathergpt/screens/settings_screen.dart';

Widget _appWithLocation() {
  return ChangeNotifierProvider(
    create: (_) {
      final app = AppState();
      app.location = const GeoLocation(
        name: 'London',
        latitude: 51.5074,
        longitude: -0.1278,
      );
      return app;
    },        child: MaterialApp(
      home: Scaffold(
        body: ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 800),
          child: SettingsScreen(),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('Settings screen shows all sections', (WidgetTester tester) async {
    await tester.pumpWidget(_appWithLocation());
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('Activity weather score'), findsOneWidget);
    expect(find.text('Alert notifications'), findsOneWidget);
    expect(find.text('Backend URL'), findsOneWidget);
    expect(find.text('About WeatherGPT'), findsOneWidget);
    expect(find.text('Account & data'), findsOneWidget);
    expect(find.text('Sign out'), findsOneWidget);
    expect(find.text('Clear saved location'), findsOneWidget);
  });

  testWidgets('Settings screen shows not-signed-in status', (WidgetTester tester) async {
    await tester.pumpWidget(_appWithLocation());
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 1));

    expect(find.textContaining('not signed in'), findsOneWidget);
  });

  testWidgets('Sign out button is disabled when not authenticated', (WidgetTester tester) async {
    await tester.pumpWidget(_appWithLocation());
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 1));

    final signOutFinder = find.widgetWithText(OutlinedButton, 'Sign out');
    expect(signOutFinder, findsOneWidget);
    final signOut = tester.widget<OutlinedButton>(signOutFinder);
    expect(signOut.onPressed, isNull);
  });
}
