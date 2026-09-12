import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:geocoding/geocoding.dart';
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
  AQIResponse? aqi;

  bool loading = false;
  String? error;

  String? authToken;
  int? conversationId;

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
        final placemarks = await placemarkFromCoordinates(
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
  }

  Future<void> refreshWeather() async {
    if (location == null) return;
    loading = true;
    error = null;
    notifyListeners();
    try {
      final bundle = await _repository.fetchWeather(
        location!.latitude,
        location!.longitude,
        locationName: location!.name,
      );
      current = bundle.current;
      hourly = _upcomingHours(bundle.hourly);
      daily = bundle.daily;
    } on ApiException catch (e) {
      error = e.message;
    } catch (_) {
      error = 'Something went wrong. Please try again.';
    }
    // Fetch AQI separately — non-fatal if it fails.
    try {
      aqi = await _repository.fetchAQI(
        location!.latitude,
        location!.longitude,
        location!.name,
      );
    } catch (_) {
      aqi = null;
    }
    loading = false;
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
    } catch (_) {
      return 'Could not reach the WeatherGPT server.';
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
    } catch (_) {
      return 'Could not reach the WeatherGPT server.';
    }
  }

  Future<void> logout() async {
    authToken = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    ApiService.instance.setAuthToken(null);
    notifyListeners();
  }
}
