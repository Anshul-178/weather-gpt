// Daily weather notification service.
//
// Schedules a local notification every day at the user-chosen time with a
// one-line weather summary. Uses flutter_local_notifications (Android/iOS)
// with exact alarm scheduling; on platforms where local notifications are
// not supported (Windows, web) every entry point degrades to a no-op.
//
// Two delivery paths:
//   1. OS-scheduled: a placeholder notification zoned for the chosen local
//      time each day (survives restarts, no app running required).
//   2. Foreground refresh: when the app happens to be running at fire time
//      the placeholder is replaced with fresh weather text immediately.
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;
import 'package:flutter_timezone/flutter_timezone.dart';

import '../models/weather.dart';
import '../repositories/weather_repository.dart';

class NotificationService {
  NotificationService._();

  static final NotificationService instance = NotificationService._();

  static const _prefsKeyEnabled = 'daily_weather_notify_enabled';
  static const _prefsKeyHour = 'daily_weather_notify_hour';
  static const _prefsKeyMinute = 'daily_weather_notify_minute';

  static const _channelId = 'daily_weather';
  static const _channelName = 'Daily weather';
  static const _dailyNotificationId = 4201;

  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  final WeatherRepository _repository = WeatherRepository();

  bool _initialized = false;
  bool? _permissionsGranted;

  /// Android + iOS are the only supported platforms for local notifications.
  static bool get isSupported =>
      !kIsWeb &&
      (Platform.isAndroid || Platform.isIOS);

  Future<void> init() async {
    if (_initialized || !isSupported) return;
    try {
      tzdata.initializeTimeZones();
      try {
        final localName = await FlutterTimezone.getLocalTimezone();
        tz.setLocalLocation(tz.getLocation(localName));
      } catch (_) {
        // Fall back to UTC rather than failing scheduling outright.
      }

      const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
      const iosInit = DarwinInitializationSettings(
        requestAlertPermission: false,
        requestBadgePermission: false,
        requestSoundPermission: false,
      );
      await _plugin.initialize(
        const InitializationSettings(android: androidInit, iOS: iosInit),
      );
      _initialized = true;

      // Re-check whether anything is enabled after a reinstall/update:
      // pending OS schedules are lost on data clear, prefs may not be.
      final prefs = await SharedPreferences.getInstance();
      final enabled = prefs.getBool(_prefsKeyEnabled) ?? false;
      if (enabled) {
        final hour = prefs.getInt(_prefsKeyHour) ?? 8;
        final minute = prefs.getInt(_prefsKeyMinute) ?? 0;
        // Re-resolve weather content and re-arm the schedule idempotently.
        await enableDaily(TimeOfDay(hour: hour, minute: minute));
      }
    } catch (e) {
      debugPrint('NotificationService init failed: $e');
    }
  }

  /// Ask the OS for notification permission (Android 13+, iOS).
  Future<bool> requestPermissions() async {
    if (!isSupported) return false;
    if (_permissionsGranted != null) return _permissionsGranted!;
    try {
      if (Platform.isAndroid) {
        final android = _plugin.resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>();
        final granted = await android?.requestNotificationsPermission();
        final exact = await android?.requestExactAlarmsPermission();
        _permissionsGranted = (granted ?? false) && (exact ?? true);
      } else if (Platform.isIOS) {
        final ios = _plugin.resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin>();
        final granted = await ios?.requestPermissions(
          alert: true,
          badge: true,
          sound: true,
        );
        _permissionsGranted = granted ?? false;
      }
    } catch (e) {
      debugPrint('Notification permission request failed: $e');
      _permissionsGranted = false;
    }
    return _permissionsGranted ?? false;
  }

  /// Load (enabled, time) from prefs for the Settings UI.
  Future<(bool, TimeOfDay)> loadDailySettings() async {
    final prefs = await SharedPreferences.getInstance();
    final enabled = prefs.getBool(_prefsKeyEnabled) ?? false;
    final time = TimeOfDay(
      hour: prefs.getInt(_prefsKeyHour) ?? 8,
      minute: prefs.getInt(_prefsKeyMinute) ?? 0,
    );
    return (enabled, time);
  }

  /// Enable (or re-arm) the daily weather notification at [time].
  ///
  /// Returns a user-readable error message, or null on success.
  Future<String?> enableDaily(TimeOfDay time) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsKeyEnabled, true);
    await prefs.setInt(_prefsKeyHour, time.hour);
    await prefs.setInt(_prefsKeyMinute, time.minute);

    if (!isSupported || !_initialized) return null;

    final granted = await requestPermissions();
    if (!granted) {
      return 'Notification permission was denied. Enable it in system settings.';
    }

    try {
      await _buildAndSchedule(time);
      return null;
    } catch (e) {
      debugPrint('Scheduling daily notification failed: $e');
      return 'Could not schedule the daily notification. Try again.';
    }
  }

  /// Turn the daily notification off.
  Future<void> disableDaily() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefsKeyEnabled, false);
    if (!isSupported || !_initialized) return;
    try {
      await _plugin.cancel(_dailyNotificationId);
    } catch (e) {
      debugPrint('Cancel daily notification failed: $e');
    }
  }

  /// Called by the app shell at fire time (app open): replaces the pending
  /// placeholder with fresh weather text so the user never sees stale copy.
  Future<void> showDailyNow() async {
    if (!isSupported || !_initialized) return;
    try {
      final (enabled, time) = await loadDailySettings();
      if (!enabled) return;
      final summary = await _buildSummary();
      await _showNow(summary);
      // Keep the daily schedule alive (zonedSchedule already repeats; this
      // only refreshes content if the OS one fired before the app opened).
      await _scheduleDaily(time, summary);
    } catch (e) {
      debugPrint('showDailyNow failed: $e');
    }
  }

  // ------------------------------------------------------------------ //

  Future<DailyPoint?> _todayForecast(GeoLocation location) async {
    try {
      final bundle = await _repository.fetchWeather(
        location.latitude,
        location.longitude,
        locationName: location.name,
      );
      return bundle.daily.isNotEmpty ? bundle.daily.first : null;
    } catch (e) {
      debugPrint('Daily-notification weather fetch failed: $e');
      return null;
    }
  }

  String _buildText(GeoLocation location, DailyPoint? today) {
    final buffer = StringBuffer();
    if (today?.condition != null && today!.condition!.isNotEmpty) {
      buffer.write(_capitalize(today.condition!));
    }
    if (today?.temperatureMax != null && today?.temperatureMin != null) {
      final hi = today!.temperatureMax!.round();
      final lo = today.temperatureMin!.round();
      if (buffer.isNotEmpty) buffer.write(' · ');
      buffer.write('High $hi° / Low $lo°');
    }
    if (today?.precipitationProbability != null &&
        today!.precipitationProbability! > 0) {
      if (buffer.isNotEmpty) buffer.write(' · ');
      final rainPct = today.precipitationProbability!.round();
      buffer.write('$rainPct% rain');
    }
    if (buffer.isEmpty) {
      return 'Tap to open WeatherGPT for today\'s weather.';
    }
    return buffer.toString();
  }

  String _capitalize(String s) =>
      s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';

  /// Fetch weather and schedule today's occurrence (which repeats daily).
  Future<void> _buildAndSchedule(TimeOfDay time) async {
    final summary = await _buildSummary();
    await _scheduleDaily(time, summary);
  }

  Future<({String title, String body})> _buildSummary() async {
    final prefs = await SharedPreferences.getInstance();
    final name = prefs.getString('loc_name');
    final lat = prefs.getDouble('lat');
    final lon = prefs.getDouble('lon');
    final location = (lat != null && lon != null)
        ? GeoLocation(name: name ?? 'My location', latitude: lat, longitude: lon)
        : null;

    String title;
    String body;
    if (location == null) {
      title = 'Daily weather';
      body = 'Pick a location in WeatherGPT to see your daily forecast here.';
    } else {
      final today = await _todayForecast(location);
      title = 'Today\'s weather — ${location.name}';
      body = _buildText(location, today);
    }
    return (title: title, body: body);
  }

  Future<void> _scheduleDaily(
      TimeOfDay time, ({String title, String body}) summary) async {
    final now = tz.TZDateTime.now(tz.local);
    var scheduled = tz.TZDateTime(
      tz.local,
      now.year,
      now.month,
      now.day,
      time.hour,
      time.minute,
    );
    if (!scheduled.isAfter(now)) {
      scheduled = scheduled.add(const Duration(days: 1));
    }

    await _plugin.zonedSchedule(
      _dailyNotificationId,
      summary.title,
      summary.body,
      scheduled,
      const NotificationDetails(
        android: AndroidNotificationDetails(
          _channelId,
          _channelName,
          channelDescription: 'One weather summary every morning',
          importance: Importance.defaultImportance,
          priority: Priority.defaultPriority,
          styleInformation: BigTextStyleInformation(''),
        ),
        iOS: DarwinNotificationDetails(),
      ),
      androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
      matchDateTimeComponents: DateTimeComponents.time,
    );
  }

  Future<void> _showNow(({String title, String body}) summary) async {
    await _plugin.show(
      _dailyNotificationId,
      summary.title,
      summary.body,
      const NotificationDetails(
        android: AndroidNotificationDetails(
          _channelId,
          _channelName,
          channelDescription: 'One weather summary every morning',
          importance: Importance.defaultImportance,
          priority: Priority.defaultPriority,
          styleInformation: BigTextStyleInformation(''),
        ),
        iOS: DarwinNotificationDetails(),
      ),
    );
  }
}
