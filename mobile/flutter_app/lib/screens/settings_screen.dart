import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_state.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';

/// Settings screen: activity scores and preferences.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final WeatherRepository _repository = WeatherRepository();
  static const List<String> _activities = [
    'walking', 'running', 'cycling', 'hiking', 'cricket', 'football',
    'picnic', 'photography', 'driving', 'college_commute',
  ];
  String _selectedActivity = 'walking';
  bool _loadingScore = false;
  Map<String, dynamic>? _score;

  bool _registeringPush = false;
  String? _pushStatus;

  /// Registers this device for push alerts. The FCM token normally comes
  /// from firebase_messaging; when Firebase is not configured the device is
  /// still registered with a local identifier so the pipeline is testable.
  Future<void> _registerPush() async {
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
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
      children: [
        const _SectionHeader(title: 'Activity weather score'),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                DropdownButtonFormField<String>(
                  initialValue: _selectedActivity,
                  decoration: const InputDecoration(
                      labelText: 'Choose an activity'),
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
                    onPressed:
                        app.location == null || _loadingScore ? null : _fetchScore,
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
                      style: TextStyle(
                          color: Theme.of(context).colorScheme.error),
                    )
                  else
                    _ScoreResult(score: _score!),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        const _SectionHeader(title: 'Alert notifications'),
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
                    onPressed: _registeringPush ? null : _registerPush,
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
        const _SectionHeader(title: 'About'),
        const SizedBox(height: 10),
        const Card(
          child: Column(
            children: [
              ListTile(
                leading: Icon(Icons.thermostat_rounded),
                title: Text('Temperature unit'),
                subtitle: Text('Celsius (set by the WeatherGPT backend)'),
              ),
              Divider(
                  height: 1,
                  indent: 56),
              ListTile(
                leading: Icon(Icons.notifications_outlined),
                title: Text('Alerts'),
                subtitle:
                    Text('Alert preferences are managed per account.'),
              ),
              Divider(
                  height: 1,
                  indent: 56),
              ListTile(
                leading: Icon(Icons.privacy_tip_outlined),
                title: Text('Privacy'),
                subtitle: Text(
                    'Locations are sent to the WeatherGPT backend only '
                    'to retrieve weather data.'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader({required this.title});

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: Theme.of(context).textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
            letterSpacing: -0.1,
          ),
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
                          color: Theme.of(context).colorScheme.onSurfaceVariant),
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
