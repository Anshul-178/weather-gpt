import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../models/weather.dart';
import '../providers/app_state.dart';
import '../utils/weather_icon.dart';
import 'locations_screen.dart';

/// Home screen — current conditions and quick forecast.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final current = state.current;
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return RefreshIndicator(
      onRefresh: () => state.refreshWeather(),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 96),
        children: [
          _HomeIntro(location: state.location?.name),
          const SizedBox(height: 14),
          if (state.location == null)
            const _EmptyCard(
              icon: Icons.location_on_outlined,
              text: 'Pick a location to see the weather.',
            )
          else ...[
            _HeroCard(state: state, isDark: isDark),
            if (state.loading)
              const Padding(
                padding: EdgeInsets.only(top: 12),
                child: LinearProgressIndicator(minHeight: 3),
              ),
            if (state.error != null)
              _AlertBanner(
                icon: Icons.cloud_off_rounded,
                text: state.error!,
                color: Theme.of(context).colorScheme.errorContainer,
              ),
            if (current != null) ...[
              const SizedBox(height: 20),
              const _SectionHeader(title: 'Conditions now'),
              const SizedBox(height: 10),
              _MetricGrid(current: current),
            ],
            // AQI Section
            if (state.aqi != null) ...[
              const SizedBox(height: 24),
              const _SectionHeader(title: 'Air Quality'),
              const SizedBox(height: 10),
              _AQICard(aqi: state.aqi!, isDark: isDark),
            ],
            if (state.hourly.isNotEmpty) ...[
            const SizedBox(height: 24),
            const _SectionHeader(title: 'Next hours'),
            const SizedBox(height: 10),
              SizedBox(
                height: 124,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: state.hourly.length.clamp(0, 24),
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (context, index) =>
                      _HourCard(hour: state.hourly[index]),
                ),
              ),
            ],
            if (state.daily.isNotEmpty) ...[
            const SizedBox(height: 24),
            const _SectionHeader(title: '7-day forecast'),
            const SizedBox(height: 10),
              Card(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Column(
                    children: state.daily
                        .take(7)
                        .map((day) => _DayRow(day: day))
                        .toList(),
                  ),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class _HomeIntro extends StatelessWidget {
  final String? location;
  const _HomeIntro({required this.location});

  @override
  Widget build(BuildContext context) {
    final now = DateTime.now();
    final greeting = now.hour < 12
        ? 'Good morning'
        : now.hour < 18 ? 'Good afternoon' : 'Good evening';
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(greeting,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.5,
                      )),
              const SizedBox(height: 3),
              Text(
                location == null
                    ? 'Choose a place to get started'
                    : DateFormat('EEEE, d MMMM').format(now),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
        ),
        if (location != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primaryContainer,
              borderRadius: BorderRadius.circular(99),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.my_location_rounded,
                    size: 14, color: Theme.of(context).colorScheme.primary),
                const SizedBox(width: 5),
                Text('Live',
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                          color: Theme.of(context)
                              .colorScheme
                              .onPrimaryContainer,
                          fontWeight: FontWeight.w700,
                        )),
              ],
            ),
          ),
      ],
    );
  }
}

// ---------------- Hero ---------------- //

class _HeroCard extends StatelessWidget {
  final AppState state;
  final bool isDark;
  const _HeroCard({required this.state, required this.isDark});

  @override
  Widget build(BuildContext context) {
    final current = state.current;
    final gradientColors = WeatherIcon.heroGradient(
      current?.condition,
      isDark,
    );

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(28),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: gradientColors,
        ),
        boxShadow: [
          BoxShadow(
            color: gradientColors.first.withValues(alpha: 0.35),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(22),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Row(
                    children: [
                      const Icon(Icons.location_on_rounded,
                          size: 18, color: Colors.white70),
                      const SizedBox(width: 4),
                      Flexible(
                        child: Text(
                          state.location!.name,
                          style: Theme.of(context)
                              .textTheme
                              .titleMedium
                              ?.copyWith(
                                  color: Colors.white,
                                  fontWeight: FontWeight.w600),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.tune_rounded,
                      color: Colors.white70, size: 20),
                  tooltip: 'Change location',
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const LocationsScreen()),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${current?.temperature?.round() ?? '--'}°',
                  style: Theme.of(context)
                      .textTheme
                      .displayLarge
                      ?.copyWith(
                          color: Colors.white,
                          fontSize: 88,
                          fontWeight: FontWeight.w200,
                          height: 1.0),
                ),
                const Spacer(),
                Padding(
                  padding: const EdgeInsets.only(top: 10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Icon(
                        WeatherIcon.fromCondition(current?.condition),
                        color: Colors.white.withValues(alpha: 0.9),
                        size: 44,
                      ),
                      const SizedBox(height: 6),
                      Text(
                        current?.condition ?? '—',
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            color: Colors.white.withValues(alpha: 0.85)),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            Text(
              'Feels like ${current?.feelsLike?.round() ?? '--'}°',
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(color: Colors.white.withValues(alpha: 0.75)),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------- Sections ---------------- //

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

class _MetricGrid extends StatelessWidget {
  final CurrentWeather current;
  const _MetricGrid({required this.current});

  @override
  Widget build(BuildContext context) {
    final metrics = [
      ('Humidity', '${current.humidity?.round() ?? '--'}%',
          Icons.water_drop_rounded),
      ('Wind', '${current.windSpeed?.toStringAsFixed(0) ?? '--'} km/h',
          Icons.air_rounded),
      ('UV index', current.uvIndex?.toStringAsFixed(0) ?? '--',
          Icons.wb_sunny_outlined),
      ('Visibility',
          '${current.visibility?.toStringAsFixed(0) ?? '--'} km',
          Icons.visibility_outlined),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 420;
        return GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: metrics.length,
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: compact ? 2 : 4,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            childAspectRatio: compact ? 2.05 : 0.88,
          ),
          itemBuilder: (context, index) => _MetricTile(metric: metrics[index]),
        );
      },
    );
  }
}

class _MetricTile extends StatelessWidget {
  final (String, String, IconData) metric;
  const _MetricTile({required this.metric});

  @override
  Widget build(BuildContext context) {
    final (label, value, icon) = metric;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 10),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(18),
      ),
      child: LayoutBuilder(builder: (context, constraints) {
        final isWide = constraints.maxWidth > 130;
        final content = [
          Icon(icon, size: 20, color: Theme.of(context).colorScheme.primary),
          SizedBox(width: isWide ? 10 : 0, height: isWide ? 0 : 6),
          Text(value,
              style: Theme.of(context)
                  .textTheme
                  .titleSmall
                  ?.copyWith(fontWeight: FontWeight.w700)),
          SizedBox(width: isWide ? 6 : 0, height: isWide ? 0 : 2),
          Text(label,
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ];
        return isWide
            ? Row(mainAxisAlignment: MainAxisAlignment.center, children: content)
            : Column(mainAxisAlignment: MainAxisAlignment.center, children: content);
      }),
    );
  }
}

class _HourCard extends StatelessWidget {
  final HourlyPoint hour;
  const _HourCard({required this.hour});

  @override
  Widget build(BuildContext context) {
    final isNow = hour.time.difference(DateTime.now()).inHours == 0;
    return Container(
      width: 84,
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: BoxDecoration(
        color: isNow
            ? Theme.of(context).colorScheme.primaryContainer
            : Theme.of(context).colorScheme.surfaceContainerLow,
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            DateFormat('HH:mm').format(hour.time),
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
          const SizedBox(height: 6),
          Icon(WeatherIcon.fromCondition(hour.condition),
              size: 22, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 6),
          Text('${hour.temperature?.round() ?? '--'}°',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          Text('${hour.precipitationProbability?.round() ?? 0}%',
              style: Theme.of(context)
                  .textTheme
                  .labelSmall
                  ?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ],
      ),
    );
  }
}

class _DayRow extends StatelessWidget {
  final DailyPoint day;
  const _DayRow({required this.day});

  @override
  Widget build(BuildContext context) {
    final date = DateTime.tryParse(day.date);
    final maxT = day.temperatureMax;
    final minT = day.temperatureMin;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(
        children: [
          SizedBox(
            width: 46,
            child: Text(
              date != null ? DateFormat('EEE').format(date) : day.date,
              style: Theme.of(context)
                  .textTheme
                  .titleSmall
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
          ),
          Icon(WeatherIcon.fromCondition(day.condition),
              size: 22, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(day.condition ?? '—',
                    style: Theme.of(context).textTheme.bodyMedium,
                    overflow: TextOverflow.ellipsis),
                const SizedBox(height: 4),
                ClipRRect(
                  borderRadius: BorderRadius.circular(99),
                  child: LinearProgressIndicator(
                    value: (day.precipitationProbability ?? 0) / 100,
                    minHeight: 4,
                    backgroundColor: Theme.of(context)
                        .colorScheme
                        .surfaceContainerHighest,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            '${maxT?.round() ?? '--'}°  /  ${minT?.round() ?? '--'}°',
            style: Theme.of(context)
                .textTheme
                .titleSmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
        ],
      ),
    );
  }
}

class _EmptyCard extends StatelessWidget {
  final IconData icon;
  final String text;
  const _EmptyCard({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          children: [
            Icon(icon, size: 48, color: Theme.of(context).colorScheme.primary),
            const SizedBox(height: 12),
            Text(text, textAlign: TextAlign.center),
          ],
        ),
      ),
    );
  }
}

/// Reusable alert/error banner also used by other screens.
class _AlertBanner extends StatelessWidget {
  final IconData icon;
  final String text;
  final Color color;
  const _AlertBanner(
      {required this.icon, required this.text, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Icon(icon),
          const SizedBox(width: 8),
          Expanded(child: Text(text)),
        ],
      ),
    );
  }
}

class _AQICard extends StatelessWidget {
  final AQIResponse aqi;
  final bool isDark;
  const _AQICard({required this.aqi, required this.isDark});

  @override
  Widget build(BuildContext context) {
    final color = Color(int.parse(aqi.aqiColor.replaceFirst('#', '0xFF')));

    return Card(
      color: isDark
          ? Theme.of(context).colorScheme.surfaceContainerHigh
          : Theme.of(context).colorScheme.surface,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  'AQI: ${aqi.aqi ?? "--"}',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: color,
                      ),
                ),
                const Spacer(),
                Text(
                  aqi.category ?? 'Unknown',
                  style: Theme.of(context).textTheme.labelMedium?.copyWith(
                        color: color,
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              aqi.aqiDescription,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                _AQIMetric(
                  label: 'PM2.5',
                  value: aqi.pm25?.toStringAsFixed(1) ?? '--',
                  icon: Icons.grass,
                  unit: 'μg/m³',
                ),
                const SizedBox(width: 12),
                _AQIMetric(
                  label: 'PM10',
                  value: aqi.current.pm10?.toStringAsFixed(1) ?? '--',
                  icon: Icons.air,
                  unit: 'μg/m³',
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _AQIMetric extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  final String unit;
  const _AQIMetric({
    required this.label,
    required this.value,
    required this.icon,
    required this.unit,
  });

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(
        children: [
          Icon(icon, size: 18, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 4),
          Text(
            value,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 2),
          Text(
            '$label ($unit)',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
        ],
      ),
    );
  }
}
