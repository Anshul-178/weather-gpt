import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:weathergpt/main.dart';
import 'package:weathergpt/providers/app_state.dart';

void main() {
  testWidgets('App boots and shows the home shell', (WidgetTester tester) async {
    await tester.pumpWidget(
      ChangeNotifierProvider(
        create: (_) => AppState(),
        child: const WeatherGPTApp(),
      ),
    );
    await tester.pump(const Duration(seconds: 1));

    // App bar title text ('weather_GPT') sits inside a Column in the
    // AppBar; match it without requiring the widget to be on-screen.
    expect(find.text('weather_GPT'), findsOneWidget);
    expect(find.byIcon(Icons.refresh), findsOneWidget);
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('AI Chat'), findsOneWidget);
    expect(find.byType(NavigationBar), findsOneWidget);
  });
}
