import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:geocoding/geocoding.dart' as geocoding;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config.dart';
import '../models/weather.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';

/// Central app state (provider + ChangeNotifier — lightweight by design).
class AppState extends ChangeNotifier {
  final WeatherRepository _repository = WeatherRepository();

  GeoLocation? location;
  CurrentWeather? current;
  List<HourlyPoint> hourly = [];
  List<DailyPoint> daily = [];

  bool loading = false;
  String? error;

  String? authToken;
  int? conversationId;
  Future<void>? _refreshInFlight;

  AppState() {
    _restore();
  }

  bool get isAuthenticated => authToken != null;

  Future<void> _restore() async {
    final prefs = await SharedPreferences.getInstance();
    authToken = prefs.getString('auth_token');
    ApiService.instance.setAuthToken(authToken);
    final savedLat = prefs.getDouble('lat');
    final savedLon = prefs.getDouble('lon');
    final savedName = prefs.getString('loc_name');
    if (savedLat != null && savedLon != null) {
      location = GeoLocation(
        name: savedName ?? 'My location',
        latitude: savedLat,
        longitude: savedLon,
      );
      await refreshWeather();
    } else {
      // No saved location: detect the device's current location automatically.
      final reason = await useCurrentLocation();
      if (reason != null) {
        // Show weather for the fallback city rather than an empty app.
        await _useFallbackLocation(reason);
      }
    }
    notifyListeners();
  }



  /// Detect the device's current location via GPS and load weather for it.
  ///
  /// Returns null on success, or a human-readable reason for failure so the
  /// caller can show it to the user.
  Future<String?> useCurrentLocation() async {
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        return 'Location services are off. Enable them in system settings.';
      }

      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied) {
        return 'Location permission denied. Allow it and try again.';
      }
      if (permission == LocationPermission.deniedForever) {
        return 'Location permission is blocked. Enable it in app settings.';
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.medium,
          timeLimit: Duration(seconds: 10),
        ),
      );

      var placeName = 'Current location';
      try {
        final placemarks = await geocoding.Geocoding().placemarkFromCoordinates(
          position.latitude, position.longitude);
        if (placemarks.isNotEmpty) {
          final place = placemarks.first;
          final parts = <String>{};
          for (final value in [place.locality, place.subAdministrativeArea,
            place.administrativeArea]) {
            final trimmed = value?.trim();
            if (trimmed != null && trimmed.isNotEmpty) parts.add(trimmed);
          }
          if (parts.isNotEmpty) placeName = parts.join(', ');
        }
      } catch (e) {
        debugPrint('Reverse geocoding failed: $e');
      }

      await setLocation(GeoLocation(
        name: placeName,
        latitude: position.latitude,
        longitude: position.longitude,
      ));
      return null;
    } catch (e) {
      debugPrint('useCurrentLocation failed: $e');
      return 'Could not get your position. Try again or search for a city.';
    }
  }

  /// Default city when current location is unavailable, so weather always shows.
  Future<void> _useFallbackLocation(String reason) async {
    debugPrint('Current location unavailable: $reason');
    await setLocation(const GeoLocation(
      name: 'London',
      latitude: 51.5074,
      longitude: -0.1278,
    ));
  }

  Future<void> setLocation(GeoLocation newLocation) async {
    location = newLocation;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble('lat', newLocation.latitude);
    await prefs.setDouble('lon', newLocation.longitude);
    await prefs.setString('loc_name', newLocation.name);
    await refreshWeather();
    notifyListeners();
  }

  Future<void> refreshWeather() async {
    final inFlight = _refreshInFlight;
    if (inFlight != null) {
      await inFlight;
      return;
    }

    final target = location;
    if (target == null) return;

    final request = _performRefreshWeather(target);
    _refreshInFlight = request;
    try {
      await request;
    } finally {
      if (identical(_refreshInFlight, request)) {
        _refreshInFlight = null;
      }
    }
    notifyListeners();
  }

  Future<void> _performRefreshWeather(GeoLocation target) async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      final bundle = await _repository.fetchWeather(
        target.latitude,
        target.longitude,
        locationName: target.name,
      );
      current = bundle.current;
      hourly = _upcomingHours(bundle.hourly);
      daily = bundle.daily;
    } on ApiException catch (e) {
      error = e.message;
    } catch (_) {
      error = 'Something went wrong. Please try again.';
    }
    loading = false;
    debugAssertIsAttached();
    notifyListeners();
  }

  /// Keep only the next 24 hours of the hourly forecast.
  List<HourlyPoint> _upcomingHours(List<HourlyPoint> points) {
    final now = DateTime.now();
    return points.where((p) => p.time.isAfter(now)).take(24).toList();
  }

  // ---------------- Auth ---------------- //

  Future<String?> register(String name, String email, String password) async {
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/auth/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'name': name, 'email': email, 'password': password}),
      );
      if (response.statusCode != 201) {
        final body = jsonDecode(response.body);
        if (body is Map && body['error']?['message'] is String) {
          return body['error']['message'] as String;
        }
        return 'Registration failed. Please try again.';
      }
      return await login(email, password);
    } catch (e) {
      debugPrint('Register error: $e');
      return 'Could not reach the WeatherGPT server.\n\nDebug: $e';
    }
  }

  Future<String?> login(String email, String password) async {
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiBaseUrl}/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'email': email, 'password': password}),
      );
      if (response.statusCode != 200) {
        final body = jsonDecode(response.body);
        if (body is Map && body['error']?['message'] is String) {
          return body['error']['message'] as String;
        }
        return 'Invalid email or password.';
      }
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      authToken = body['access_token'] as String?;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('auth_token', authToken!);
      ApiService.instance.setAuthToken(authToken);
      notifyListeners();
      return null;
    } catch (e) {
      debugPrint('Login error: $e');
      return 'Could not reach the WeatherGPT server.\n\nDebug: $e';
    }
  }

  void debugAssertIsAttached() {
    assert(() {
      if (!_debugIsAttached) {
        throw StateError(
          'AppState notifyListeners() called after dispose. '
          'Use a mounted-check or scope listeners to the widget lifecycle.');
      }
      return true;
    }());
  }

  bool _debugIsAttached = true;

  @override
  void dispose() {
    _debugIsAttached = false;
    super.dispose();
  }

  Future<void> logout() async {
    authToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    ApiService.instance.setAuthToken(null);
    location = null;
    current = null;
    hourly = [];
    daily = [];
    error = null;
    notifyListeners();
  }
}
