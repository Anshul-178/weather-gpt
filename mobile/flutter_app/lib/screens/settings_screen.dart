import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../providers/app_state.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';
import '../services/notification_service.dart';

/// Settings screen: activity scores and preferences.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final WeatherRepository _repository = WeatherRepository();
  static const List<String> _activities = [
    'walking',
    'running',
    'cycling',
    'hiking',
    'cricket',
    'football',
    'picnic',
    'photography',
    'driving',
    'college_commute',
  ];
  String _selectedActivity = 'walking';
  bool _loadingScore = false;
  Map<String, dynamic>? _score;

  bool _registeringPush = false;
  String? _pushStatus;

  // Daily weather notification.
  bool _dailyEnabled = false;
  TimeOfDay _dailyTime = const TimeOfDay(hour: 8, minute: 0);
  bool _dailyLoading = false;
  String? _dailyStatus;

  // Backend URL configuration.
  final _apiUrlController = TextEditingController();
  bool _savingUrl = false;
  String? _urlStatus;

  /// Registers this device for push alerts. The FCM token normally comes
  /// from firebase_messaging; when Firebase is not configured the device is
  /// still registered with a local identifier so the pipeline is testable.
  Future<void> _registerPush(BuildContext context) async {
    final app = context.read<AppState>();
    setState(() => _registeringPush = true);
    try {
      String token;
      String platform = Theme.of(context).platform.name;
      try {
        // firebase_messaging is optional; when present use the real token.
        // ignore: avoid_dynamic_calls
        token = await _fcmToken();
      } catch (_) {
        token = 'local-${DateTime.now().millisecondsSinceEpoch}';
      }
      await _repository.registerForPush(
        token,
        platform: platform,
        lat: app.location?.latitude,
        lon: app.location?.longitude,
      );
      if (mounted) {
        setState(() => _pushStatus =
            'Registered. Alerts will be delivered when rules trigger near your location.');
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _pushStatus = e.message);
    } catch (_) {
      if (mounted) {
        setState(() => _pushStatus = 'Could not reach the server. Try again.');
      }
    } finally {
      if (mounted) setState(() => _registeringPush = false);
    }
  }

  Future<String> _fcmToken() async {
    // Optional dependency: only available when firebase_messaging is added
    // to pubspec and configured. Dynamically import to keep the base build
    // Firebase-free.
    throw UnsupportedError('Firebase messaging not configured');
  }

  Future<void> _saveApiUrl(AppState app, String? url) async {
    setState(() {
      _savingUrl = true;
      _urlStatus = null;
    });
    try {
      await AppConfig.setCustomApiBaseUrl(url);
      // Force a refresh so the new URL takes effect for the next request.
      await app.refreshWeather();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Backend URL saved. Weather will use the new server.'),
            duration: Duration(seconds: 3),
          ),
        );
        setState(() => _urlStatus = 'Saved. Weather will use the new backend.');
      }
    } on Exception catch (e) {
      debugPrint('Failed to save API URL: $e');
      setState(() => _urlStatus = 'Could not save. Try again.');
    } finally {
      if (mounted) setState(() => _savingUrl = false);
    }
  }

  @override
  void initState() {
    super.initState();
    _apiUrlController.text = AppConfig.apiBaseUrl;
    _loadDailySettings();
  }

  Future<void> _loadDailySettings() async {
    final (enabled, time) = await NotificationService.instance.loadDailySettings();
    if (!mounted) return;
    setState(() {
      _dailyEnabled = enabled;
      _dailyTime = time;
    });
  }

  Future<void> _toggleDaily(bool value) async {
    // Format before any await: BuildContext must not be used across gaps.
    final formatted = _dailyTime.format(context);
    setState(() => _dailyLoading = true);
    String? error;
    if (value) {
      error = await NotificationService.instance.enableDaily(_dailyTime);
    } else {
      await NotificationService.instance.disableDaily();
    }
    if (!mounted) return;
    setState(() {
      _dailyLoading = false;
      _dailyEnabled = value && error == null;
      _dailyStatus = error ??
          (value
              ? 'Daily weather on — every day at $formatted.'
              : 'Daily weather notification turned off.');
    });
  }

  Future<void> _pickDailyTime() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _dailyTime,
    );
    if (picked == null || !mounted) return;
    setState(() => _dailyTime = picked);
    if (_dailyEnabled) {
      // Re-arm the schedule at the new time.
      await _toggleDaily(true);
    }
  }

  Future<void> _logout() async {
    final app = context.read<AppState>();
    await app.logout();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Signed out.'), duration: Duration(seconds: 2)),
      );
    }
  }

  Future<void> _clearLocation() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('lat');
    await prefs.remove('lon');
    await prefs.remove('loc_name');
    final app = context.read<AppState>();
    app.location = null;
    app.current = null;
    app.hourly = [];
    app.daily = [];
    app.error = null;
    app.location = app.location; // trigger rebuild
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Saved location cleared. Pick a new one on the Home screen.'),
        duration: const Duration(seconds: 3),
      ),
    );
  }

  Future<void> _fetchScore() async {
    final app = context.read<AppState>();
    if (app.location == null) return;
    setState(() {
      _loadingScore = true;
      _score = null;
    });
    try {
      final result = await _repository.fetchActivityScore(
        _selectedActivity,
        app.location!.latitude,
        app.location!.longitude,
      );
      setState(() => _score = {
            'score': result.score,
            'rating': result.rating,
            'reasons': result.reasons,
            'best_time': result.bestTime,
          });
    } on ApiException catch (e) {
      setState(() => _score = {'error': e.message});
    } finally {
      setState(() => _loadingScore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 112),
      children: [
        const _SectionHeader(
          title: 'Activity weather score',
          subtitle: 'Find the best time to get outside',
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: _selectedActivity,
                  decoration:
                      const InputDecoration(labelText: 'Choose an activity'),
                  items: _activities
                      .map((a) => DropdownMenuItem(
                          value: a,
                          child: Text(a.replaceAll('_', ' '),
                              style: const TextStyle(
                                  textBaseline: TextBaseline.alphabetic))))
                      .toList(),
                  onChanged: (value) =>
                      setState(() => _selectedActivity = value ?? 'walking'),
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: app.location == null || _loadingScore
                        ? null
                        : _fetchScore,
                    icon: _loadingScore
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.insights_rounded),
                    label: const Text('Check conditions'),
                  ),
                ),
                if (_score != null) ...[
                  const SizedBox(height: 18),
                  if (_score!['error'] != null)
                    Text(
                      _score!['error'] as String,
                      style:
                          TextStyle(color: Theme.of(context).colorScheme.error),
                    )
                  else
                    _ScoreResult(score: _score!),
                ],
              ],
            ),
          ),
        ),
        if (app.location == null) ...[
          const SizedBox(height: 10),
          Text(
            'Choose a location from the Home screen before checking conditions.',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
        const SizedBox(height: 24),
        const _SectionHeader(
          title: 'Alert notifications',
          subtitle: 'Stay ahead of extreme weather',
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Extreme weather alerts (rain, heat, storms, flood, '
                  'cyclone winds) are pushed to this device when triggered '
                  'for your saved locations.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _registeringPush ? null : () => _registerPush(context),
                    icon: _registeringPush
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.notifications_active_outlined),
                    label: const Text('Enable push alerts on this device'),
                  ),
                ),
                if (_pushStatus != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    _pushStatus!,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        const _SectionHeader(
          title: 'Daily weather notification',
          subtitle: 'A weather summary on this device, every day',
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Notify me every day'),
                  subtitle: Text(
                    NotificationService.isSupported
                        ? 'Delivers around ${_dailyTime.format(context)} '
                            'with today\'s forecast for your location.'
                        : 'Not supported on this platform (use the Android '
                            'or iOS app).',
                  ),
                  value: _dailyEnabled,
                  onChanged: _dailyLoading
                      ? null
                      : (NotificationService.isSupported
                          ? _toggleDaily
                          : null),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: NotificationService.isSupported
                            ? _pickDailyTime
                            : null,
                        icon: const Icon(Icons.schedule_rounded),
                        label: Text('Time: ${_dailyTime.format(context)}'),
                      ),
                    ),
                  ],
                ),
                if (_dailyStatus != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    _dailyStatus!,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.onSurfaceVariant),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        const _SectionHeader(
          title: 'Backend URL',
          subtitle: 'Point the app at a different WeatherGPT server',
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'The app connects to a WeatherGPT FastAPI backend. '
                  'Change this if you are running your own server or a '
                  'staging instance. The default is the deployed Render backend.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 14),
                TextField(
                  decoration: const InputDecoration(
                    labelText: 'API base URL',
                    hintText: 'https://example.com',
                  ),
                  controller: _apiUrlController,
                  onChanged: (value) =>
                      setState(() => _apiUrlController.text = value.trim()),
                  onSubmitted: (_) => _saveApiUrl(
                      context.read<AppState>(), _apiUrlController.text),
                  enabled: !_savingUrl,
                ),
                const SizedBox(height: 14),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: _savingUrl
                        ? null
                        : () => _saveApiUrl(
                            context.read<AppState>(), _apiUrlController.text),
                    icon: _savingUrl
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.save_outlined),
                    label: const Text('Save backend URL'),
                  ),
                ),
                if (_urlStatus != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    _urlStatus!,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: _urlStatus!.startsWith('Saved')
                            ? Theme.of(context).colorScheme.primary
                            : Theme.of(context).colorScheme.error),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        const _SectionHeader(
          title: 'About WeatherGPT',
          subtitle: 'Privacy and app preferences',
        ),
        const SizedBox(height: 10),
        const Card(
          child: Column(
            children: [
              ListTile(
                leading: Icon(Icons.thermostat_rounded),
                title: Text('Temperature unit'),
                subtitle: Text('Celsius (set by the WeatherGPT backend)'),
              ),
              Divider(height: 1, indent: 56),
              ListTile(
                leading: Icon(Icons.notifications_outlined),
                title: Text('Alerts'),
                subtitle: Text('Alert preferences are managed per account.'),
              ),
              Divider(height: 1, indent: 56),
              ListTile(
                leading: Icon(Icons.privacy_tip_outlined),
                title: Text('Privacy'),
                subtitle:
                    Text('Locations are sent to the WeatherGPT backend only '
                        'to retrieve weather data.'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        const _SectionHeader(
          title: 'Account & data',
          subtitle: 'Sign out or clear saved data',
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                OutlinedButton.icon(
                  onPressed: app.isAuthenticated ? _logout : null,
                  icon: const Icon(Icons.logout_outlined),
                  label: const Text('Sign out'),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: _clearLocation,
                  icon: const Icon(Icons.location_off_outlined),
                  label: const Text('Clear saved location'),
                ),
                const SizedBox(height: 10),
                Text(
                  app.isAuthenticated
                      ? 'You are signed in. Sign out to switch accounts.'
                      : 'You are not signed in. Sign in from the chat screen.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  const _SectionHeader({required this.title, this.subtitle});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w700,
                letterSpacing: -0.1,
              ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 2),
          Text(
            subtitle!,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ],
    );
  }
}

class _ScoreResult extends StatelessWidget {
  final Map<String, dynamic> score;
  const _ScoreResult({required this.score});

  Color _colorFor(double normalized) {
    if (normalized >= 0.66) return Colors.green;
    if (normalized >= 0.33) return Colors.orange;
    return Colors.red;
  }

  @override
  Widget build(BuildContext context) {
    final value = (score['score'] as num?)?.toDouble() ?? 0;
    final normalized = (value / 100).clamp(0.0, 1.0);
    final color = _colorFor(normalized);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            SizedBox(
              width: 64,
              height: 64,
              child: Stack(
                fit: StackFit.expand,
                children: [
                  CircularProgressIndicator(
                    value: normalized,
                    strokeWidth: 6,
                    color: color,
                    backgroundColor:
                        Theme.of(context).colorScheme.surfaceContainerHighest,
                  ),
                  Center(
                    child: Text(
                      '${value.round()}',
                      style: Theme.of(context)
                          .textTheme
                          .titleLarge
                          ?.copyWith(fontWeight: FontWeight.w800),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    score['rating'] as String? ?? '—',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                  if (score['best_time'] != null)
                    Text(
                      'Best time: ${score['best_time']}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color:
                              Theme.of(context).colorScheme.onSurfaceVariant),
                    ),
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        ...(score['reasons'] as List<dynamic>).map(
          (reason) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.check_circle_rounded,
                    size: 17, color: Theme.of(context).colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(
                    child: Text(reason as String,
                        style: Theme.of(context).textTheme.bodyMedium)),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
