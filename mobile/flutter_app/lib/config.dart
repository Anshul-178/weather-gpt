/// App configuration.
///
/// The backend URL comes from build-time configuration so it is never
/// scattered through the code:
///
/// ```
/// flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
/// ```
///
/// No weather-provider or LLM API keys ever live in this app: all requests
/// go through the WeatherGPT FastAPI backend.
library;

import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

class AppConfig {
  static const String _configuredUrl = String.fromEnvironment('API_BASE_URL');
  static const String _prefKey = 'custom_api_base_url';
  static String? _customUrl;

  /// Load any user-saved backend URL from SharedPreferences
  static Future<void> init() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _customUrl = prefs.getString(_prefKey);
    } catch (_) {}
  }

  /// Update and save the custom backend URL
  static Future<void> setCustomApiBaseUrl(String? url) async {
    _customUrl = (url != null && url.trim().isNotEmpty) ? url.trim() : null;
    try {
      final prefs = await SharedPreferences.getInstance();
      if (_customUrl != null) {
        await prefs.setString(_prefKey, _customUrl!);
      } else {
        await prefs.remove(_prefKey);
      }
    } catch (_) {}
  }

  static String get apiBaseUrl {
    if (_customUrl != null && _customUrl!.isNotEmpty) {
      return _customUrl!;
    }
    if (_configuredUrl.isNotEmpty) {
      return _configuredUrl;
    }
    // By default both debug and release builds use the deployed Render
    // backend. Debug builds only fall back to a local development backend
    // when you opt in with --dart-define=API_BASE_URL=<local url>.
    if (kIsWeb ||
        Platform.isWindows ||
        Platform.isMacOS ||
        Platform.isLinux) {
      return 'https://weather-gpt-pc49.onrender.com';
    }
    return 'https://weather-gpt-pc49.onrender.com';
  }

  // Generous timeout: Render's free tier sleeps when idle, and a cold start
  // can take 20-50s. Also covers slow LLM-generated chat answers.
  static const Duration requestTimeout = Duration(seconds: 60);
}
