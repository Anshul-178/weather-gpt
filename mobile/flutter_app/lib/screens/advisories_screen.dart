import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/insights.dart';
import '../providers/app_state.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';

/// Decision-support screen: crop advisories, aviation briefing, and a
/// multi-city weather overview (smart-city monitoring).
class AdvisoriesScreen extends StatefulWidget {
  const AdvisoriesScreen({super.key});

  @override
  State<AdvisoriesScreen> createState() => _AdvisoriesScreenState();
}

class _AdvisoriesScreenState extends State<AdvisoriesScreen> {
  final WeatherRepository _repository = WeatherRepository();

  CropAdvisory? _crop;
  AviationBriefing? _aviation;
  CityOverview? _cities;
  bool _loading = false;
  String? _error;

  String _selectedCrop = '';
  static const List<(String, String)> _crops = [
    ('', 'General'),
    ('rice', 'Rice'),
    ('wheat', 'Wheat'),
    ('cotton', 'Cotton'),
    ('sugarcane', 'Sugarcane'),
    ('maize', 'Maize'),
    ('mustard', 'Mustard'),
    ('groundnut', 'Groundnut'),
    ('onion', 'Onion'),
    ('potato', 'Potato'),
    ('tomato', 'Tomato'),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadCities();
      _loadAdvisories();
    });
  }

  Future<void> _loadCities() async {
    try {
      final overview = await _repository.fetchCityOverview();
      if (mounted) setState(() => _cities = overview);
    } on ApiException {
      // Non-fatal: the city panel simply stays hidden.
    } catch (_) {}
  }

  Future<void> _loadAdvisories() async {
    final app = context.read<AppState>();
    if (app.location == null) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final cropFuture = _repository.fetchCropAdvisory(
        app.location!.latitude,
        app.location!.longitude,
        app.location!.name,
        crop: _selectedCrop.isNotEmpty ? _selectedCrop : null,
      );
      final aviationFuture = _repository.fetchAviationBriefing(
        app.location!.latitude,
        app.location!.longitude,
        app.location!.name,
      );
      final results = await Future.wait([cropFuture, aviationFuture]);
      if (mounted) {
        setState(() {
          _crop = results[0] as CropAdvisory;
          _aviation = results[1] as AviationBriefing;
          _loading = false;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _error = e.message;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _error = 'Could not load advisories. Please try again.';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return RefreshIndicator(
      onRefresh: _loadAdvisories,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 112),
        children: [
          Text(
            'Decision support',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 4),
          Text(
            'Useful guidance for farming, flying, and city monitoring.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<String>(
                  initialValue: _selectedCrop,
                  isDense: true,
                  decoration: const InputDecoration(
                    labelText: 'Crop (optional)',
                  ),
                  items: _crops
                      .map((c) =>
                          DropdownMenuItem(value: c.$1, child: Text(c.$2)))
                      .toList(),
                  onChanged: (value) {
                    setState(() => _selectedCrop = value ?? '');
                    _loadAdvisories();
                  },
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_error != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Text(_error!, style: TextStyle(color: scheme.error)),
              ),
            )
          else ...[
            if (_crop != null) _CropCard(crop: _crop!),
            const SizedBox(height: 16),
            if (_aviation != null) _AviationCard(briefing: _aviation!),
            const SizedBox(height: 16),
          ],
          if (_cities != null && _cities!.cities.isNotEmpty) ...[
            const _SectionHeader(
              title: 'City weather monitor',
              subtitle: 'A quick view across monitored locations',
            ),
            const SizedBox(height: 10),
            Card(
              child: Column(
                children: _cities!.cities
                    .map((city) => _CityRow(city: city))
                    .toList(),
              ),
            ),
          ],
        ],
      ),
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

class _CropCard extends StatelessWidget {
  final CropAdvisory crop;
  const _CropCard({required this.crop});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.agriculture_rounded,
                    color: scheme.primary, size: 22),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    crop.crop == null
                        ? 'Crop advisory — ${crop.location}'
                        : 'Crop advisory — ${crop.crop} · ${crop.location}',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                if (crop.fieldWorkScore != null) ...[
                  const SizedBox(width: 8),
                  _MiniScoreBadge(score: crop.fieldWorkScore!),
                ],
              ],
            ),
            if (crop.irrigationNeeded == true) ...[
              const SizedBox(height: 10),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: scheme.tertiaryContainer,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  '💧 Irrigation recommended within 48 hours',
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: scheme.onTertiaryContainer,
                      fontWeight: FontWeight.w600),
                ),
              ),
            ],
            const SizedBox(height: 12),
            ...crop.advisories.map((item) => _AdvisoryRow(item: item)),
          ],
        ),
      ),
    );
  }
}

class _MiniScoreBadge extends StatelessWidget {
  final int score;
  const _MiniScoreBadge({required this.score});

  Color get color {
    if (score >= 66) return Colors.green;
    if (score >= 33) return Colors.orange;
    return Colors.red;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        'Field work $score',
        style:
            TextStyle(color: color, fontWeight: FontWeight.w700, fontSize: 12),
      ),
    );
  }
}

class _AdvisoryRow extends StatelessWidget {
  final CropAdvisoryItem item;
  const _AdvisoryRow({required this.item});

  IconData get _icon {
    switch (item.category) {
      case 'irrigation':
        return Icons.water_drop_rounded;
      case 'pest_disease':
        return Icons.bug_report_rounded;
      case 'field_work':
        return Icons.construction_rounded;
      case 'sowing':
        return Icons.grass_rounded;
      default:
        return Icons.info_outline_rounded;
    }
  }

  Color get _color {
    switch (item.severity) {
      case 'warning':
        return Colors.red;
      case 'caution':
        return Colors.orange;
      default:
        return Colors.green;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(_icon, size: 18, color: _color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(item.message,
                style: Theme.of(context).textTheme.bodyMedium),
          ),
        ],
      ),
    );
  }
}

class _AviationCard extends StatelessWidget {
  final AviationBriefing briefing;
  const _AviationCard({required this.briefing});

  Color get _categoryColor {
    switch (briefing.flightCategory) {
      case 'ok':
        return Colors.green;
      case 'caution':
        return Colors.orange;
      case 'hazard':
        return Colors.red;
      default:
        return Colors.grey;
    }
  }

  IconData get _categoryIcon {
    switch (briefing.flightCategory) {
      case 'ok':
        return Icons.flight_takeoff_rounded;
      case 'caution':
        return Icons.flight_rounded;
      case 'hazard':
        return Icons.flight_land_rounded;
      default:
        return Icons.help_outline_rounded;
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(_categoryIcon, color: _categoryColor, size: 22),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Aviation briefing — ${briefing.location}',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: _categoryColor.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    briefing.flightCategory.toUpperCase(),
                    style: TextStyle(
                        color: _categoryColor,
                        fontWeight: FontWeight.w800,
                        fontSize: 11,
                        letterSpacing: 0.5),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(briefing.summary,
                style: Theme.of(context).textTheme.bodyMedium),
            if (briefing.bestWindows.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  for (final window in briefing.bestWindows)
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: scheme.primaryContainer,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(
                        '🛫 $window',
                        style: TextStyle(
                            color: scheme.onPrimaryContainer,
                            fontWeight: FontWeight.w600,
                            fontSize: 12),
                      ),
                    ),
                ],
              ),
            ],
            const SizedBox(height: 12),
            ...briefing.conditions.map((c) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        c.status == 'hazard'
                            ? Icons.error_outline_rounded
                            : c.status == 'caution'
                                ? Icons.warning_amber_rounded
                                : Icons.check_circle_rounded,
                        size: 17,
                        color: c.status == 'hazard'
                            ? Colors.red
                            : c.status == 'caution'
                                ? Colors.orange
                                : Colors.green,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          c.note ?? c.parameter,
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ),
                    ],
                  ),
                )),
          ],
        ),
      ),
    );
  }
}

class _CityRow extends StatelessWidget {
  final CitySnapshot city;
  const _CityRow({required this.city});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
      child: Row(
        children: [
          Expanded(
            child: Text(
              city.name,
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
          if (city.aqi != null) ...[
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              decoration: BoxDecoration(
                color: scheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                'AQI ${city.aqi}',
                style: Theme.of(context).textTheme.labelSmall,
              ),
            ),
            const SizedBox(width: 10),
          ],
          SizedBox(
            width: 110,
            child: Text(
              city.condition ?? '—',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(color: scheme.onSurfaceVariant),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            city.temperature == null ? '--°' : '${city.temperature!.round()}°',
            style: Theme.of(context)
                .textTheme
                .titleMedium
                ?.copyWith(fontWeight: FontWeight.w700),
          ),
        ],
      ),
    );
  }
}
