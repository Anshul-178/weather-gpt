import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/insights.dart';
import '../providers/app_state.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';
import '../utils/weather_icon.dart';

/// Detailed forecast screen with hourly/daily forecasts and climate trends.
class ForecastScreen extends StatefulWidget {
  const ForecastScreen({super.key});

  @override
  State<ForecastScreen> createState() => _ForecastScreenState();
}

class _ForecastScreenState extends State<ForecastScreen> {
  final WeatherRepository _repository = WeatherRepository();
  ClimateTrend? _climate;
  bool _climateLoading = false;
  String? _climateError;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _loadClimateOnce();
  }

  void _loadClimateOnce() {
    if (_climate != null || _climateLoading || _climateError != null) return;
    final state = context.read<AppState>();
    if (state.location == null) return;
    setState(() => _climateLoading = true);
    _repository
        .fetchClimateTrend(
      state.location!.latitude,
      state.location!.longitude,
      years: 5,
    )
        .then((trend) {
      if (mounted) {
        setState(() {
          _climate = trend;
          _climateLoading = false;
        });
      }
    }).catchError((Object e) {
      if (mounted) {
        setState(() {
          _climateError =
              e is ApiException ? e.message : 'Climate data unavailable.';
          _climateLoading = false;
        });
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    if (state.location == null) {
      return const Center(child: Text('Pick a location first.'));
    }
    if (state.loading && state.daily.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 112),
      children: [
        _ForecastLocationHeader(location: state.location!.name),
        const SizedBox(height: 22),
        const _SectionHeader(
          title: 'Next 24 hours',
          subtitle: 'A closer look at what is coming up',
        ),
        const SizedBox(height: 10),
        if (state.hourly.isEmpty)
          const Text('No hourly data available.')
        else
          SizedBox(
            height: 124,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: state.hourly.length.clamp(0, 24),
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, index) =>
                  _ForecastHourCard(hour: state.hourly[index]),
            ),
          ),
        const SizedBox(height: 24),
        const _SectionHeader(
          title: 'Daily forecast',
          subtitle: 'Seven days of temperature and conditions',
        ),
        const SizedBox(height: 10),
        if (state.daily.isEmpty)
          const _EmptyForecastCard()
        else
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Column(
                children: [
                  for (var index = 0; index < state.daily.length; index++) ...[
                    _ForecastDayRow(day: state.daily[index]),
                    if (index < state.daily.length - 1)
                      const Divider(height: 1, indent: 16, endIndent: 16),
                  ],
                ],
              ),
            ),
          ),
        const SizedBox(height: 24),
        _ClimateSection(
          climate: _climate,
          loading: _climateLoading,
          error: _climateError,
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

class _ForecastLocationHeader extends StatelessWidget {
  final String location;
  const _ForecastLocationHeader({required this.location});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: scheme.primaryContainer.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Icon(Icons.location_on_rounded, size: 18, color: scheme.primary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              location,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: scheme.onPrimaryContainer,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
          Text(
            'Live forecast',
            style: TextStyle(
              color: scheme.onPrimaryContainer.withValues(alpha: 0.72),
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyForecastCard extends StatelessWidget {
  const _EmptyForecastCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Row(
          children: [
            Icon(Icons.cloud_queue_rounded,
                color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 12),
            const Expanded(child: Text('Daily forecast is not available yet.')),
          ],
        ),
      ),
    );
  }
}

class _ForecastHourCard extends StatelessWidget {
  final dynamic hour;
  const _ForecastHourCard({required this.hour});

  @override
  Widget build(BuildContext context) {
    final minutesFromNow = hour.time.difference(DateTime.now()).inMinutes;
    final isNow = minutesFromNow >= -30 && minutesFromNow <= 30;
    final scheme = Theme.of(context).colorScheme;
    return Container(
      width: 88,
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
      decoration: BoxDecoration(
        color: isNow ? scheme.primaryContainer : scheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: scheme.outlineVariant.withValues(alpha: isNow ? 0.5 : 0.28),
        ),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            isNow ? 'Now' : DateFormat('HH:mm').format(hour.time),
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 5),
          Icon(
              WeatherIcon.fromCondition(hour.condition, hour.weatherCode),
              size: 22, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 5),
          Text('${hour.temperature?.round() ?? '--'}°',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700)),
          Text('Rain ${hour.precipitationProbability?.round() ?? 0}%',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ],
      ),
    );
  }
}

class _ForecastDayRow extends StatelessWidget {
  final dynamic day;
  const _ForecastDayRow({required this.day});

  @override
  Widget build(BuildContext context) {
    final date = DateTime.tryParse(day.date);
    final maxT = day.temperatureMax;
    final minT = day.temperatureMin;
    final wind = day.windSpeedMax;
    final uv = day.uvIndexMax;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          SizedBox(
            width: 76,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  date != null ? DateFormat('EEE').format(date) : day.date,
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
                Text(
                  date != null ? DateFormat('MMM d').format(date) : '',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          Icon(
              WeatherIcon.fromCondition(day.condition, day.weatherCode),
              size: 24, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(day.condition ?? '—',
                    style: Theme.of(context).textTheme.bodyMedium,
                    overflow: TextOverflow.ellipsis),
                const SizedBox(height: 4),
                Text(
                  'Rain ${(day.precipitationProbability ?? 0).round()}%'
                  '  ·  Wind ${wind?.toStringAsFixed(0) ?? '--'} km/h'
                  '  ·  UV ${uv?.toStringAsFixed(0) ?? '--'}',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant),
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                '${maxT?.round() ?? '--'}°',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w700),
              ),
              Text(
                '${minT?.round() ?? '--'}°',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Climate trends card: 5-year warming trend, annual rainfall, anomaly.
class _ClimateSection extends StatelessWidget {
  final ClimateTrend? climate;
  final bool loading;
  final String? error;

  const _ClimateSection({
    required this.climate,
    required this.loading,
    required this.error,
  });

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Card(
        child: Padding(
          padding: EdgeInsets.all(20),
          child: Center(
            child: SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          ),
        ),
      );
    }
    if (error != null || climate == null) {
      return const SizedBox.shrink();
    }

    final trend = climate!;
    final scheme = Theme.of(context).colorScheme;
    final warming = trend.warmingTrendCPerDecade;
    final anomaly = trend.currentMonthAnomalyC;

    String anomalyText;
    if (anomaly == null) {
      anomalyText = 'Baseline building…';
    } else if (anomaly >= 1) {
      anomalyText =
          'This month is ${anomaly.toStringAsFixed(1)}°C warmer than recent years';
    } else if (anomaly <= -1) {
      anomalyText =
          'This month is ${anomaly.abs().toStringAsFixed(1)}°C cooler than recent years';
    } else {
      anomalyText = 'This month is close to the recent average';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _SectionHeader(
          title: 'Climate trends (5 years)',
          subtitle: 'Longer-term patterns for this location',
        ),
        const SizedBox(height: 10),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.query_stats_rounded,
                        size: 20, color: scheme.primary),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        anomalyText,
                        style: Theme.of(context)
                            .textTheme
                            .bodyMedium
                            ?.copyWith(fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(
                      child: _ClimateStat(
                        icon: Icons.trending_up_rounded,
                        label: 'Warming trend',
                        value: warming == null
                            ? '—'
                            : '${warming >= 0 ? '+' : ''}${warming.toStringAsFixed(2)}°C/decade',
                      ),
                    ),
                    Expanded(
                      child: _ClimateStat(
                        icon: Icons.water_drop_outlined,
                        label: 'Avg annual rain',
                        value: trend.annualPrecipitationMm == null
                            ? '—'
                            : '${trend.annualPrecipitationMm!.round()} mm',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                SizedBox(
                  height: 96,
                  child: _MonthlyBars(monthly: trend.monthly),
                ),
                const SizedBox(height: 6),
                Text(
                  'Monthly mean temperature, last ${trend.years} years',
                  style: Theme.of(context)
                      .textTheme
                      .labelSmall
                      ?.copyWith(color: scheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _ClimateStat extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;

  const _ClimateStat({
    required this.icon,
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Row(
      children: [
        Icon(icon, size: 18, color: scheme.primary),
        const SizedBox(width: 6),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(value,
                  style: Theme.of(context)
                      .textTheme
                      .titleSmall
                      ?.copyWith(fontWeight: FontWeight.w700)),
              Text(label,
                  style: Theme.of(context)
                      .textTheme
                      .labelSmall
                      ?.copyWith(color: scheme.onSurfaceVariant)),
            ],
          ),
        ),
      ],
    );
  }
}

/// Tiny sparkline-style bar chart of monthly mean temperatures.
class _MonthlyBars extends StatelessWidget {
  final List<ClimateTrendMonth> monthly;

  const _MonthlyBars({required this.monthly});

  @override
  Widget build(BuildContext context) {
    final points =
        monthly.where((m) => m.avgTempMean != null).toList().take(60).toList();
    if (points.isEmpty) return const SizedBox.shrink();
    final values = points.map((m) => m.avgTempMean!).toList();
    final minV = values.reduce((a, b) => a < b ? a : b);
    final maxV = values.reduce((a, b) => a > b ? a : b);
    final range = (maxV - minV) == 0 ? 1.0 : (maxV - minV);
    final scheme = Theme.of(context).colorScheme;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        for (final value in values)
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 1),
              child: FractionallySizedBox(
                alignment: Alignment.bottomCenter,
                heightFactor: 0.15 + 0.85 * ((value - minV) / range),
                child: Container(
                  decoration: BoxDecoration(
                    color: scheme.primary.withValues(alpha: 0.55),
                    borderRadius: const BorderRadius.vertical(
                      top: Radius.circular(2),
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
