// Models for insights features: climate history, crop advisories,
// aviation briefings, and city overview.

// ---------------- Climate / historical ----------------

class HistoricalStats {
  final int periodDays;
  final double? tempMean;
  final double? tempMax;
  final double? tempMin;
  final double? totalPrecipitation;
  final int wetDays;
  final String? hottestDayDate;
  final double? hottestDayTemp;
  final String? wettestDayDate;
  final double? wettestDayPrecip;

  const HistoricalStats({
    required this.periodDays,
    this.tempMean,
    this.tempMax,
    this.tempMin,
    this.totalPrecipitation,
    this.wetDays = 0,
    this.hottestDayDate,
    this.hottestDayTemp,
    this.wettestDayDate,
    this.wettestDayPrecip,
  });

  factory HistoricalStats.fromJson(Map<String, dynamic> json) => HistoricalStats(
        periodDays: (json['period_days'] as num?)?.toInt() ?? 0,
        tempMean: (json['temp_mean'] as num?)?.toDouble(),
        tempMax: (json['temp_max'] as num?)?.toDouble(),
        tempMin: (json['temp_min'] as num?)?.toDouble(),
        totalPrecipitation: (json['total_precipitation'] as num?)?.toDouble(),
        wetDays: (json['wet_days'] as num?)?.toInt() ?? 0,
        hottestDayDate:
            (json['hottest_day'] as Map<String, dynamic>?)?['date'] as String?,
        hottestDayTemp: (json['hottest_day'] as Map<String, dynamic>?) == null
            ? null
            : ((json['hottest_day'] as Map<String, dynamic>)['temperature_max']
                    as num?)
                ?.toDouble(),
        wettestDayDate:
            (json['wettest_day'] as Map<String, dynamic>?)?['date'] as String?,
        wettestDayPrecip:
            (json['wettest_day'] as Map<String, dynamic>?) == null
                ? null
                : ((json['wettest_day'] as Map<String, dynamic>)['precipitation_sum']
                        as num?)
                    ?.toDouble(),
      );
}

class HistoricalDaily {
  final String date;
  final double? temperatureMax;
  final double? temperatureMin;
  final double? temperatureMean;
  final double? precipitationSum;

  const HistoricalDaily({
    required this.date,
    this.temperatureMax,
    this.temperatureMin,
    this.temperatureMean,
    this.precipitationSum,
  });

  factory HistoricalDaily.fromJson(Map<String, dynamic> json) => HistoricalDaily(
        date: json['date'] as String? ?? '',
        temperatureMax: (json['temperature_max'] as num?)?.toDouble(),
        temperatureMin: (json['temperature_min'] as num?)?.toDouble(),
        temperatureMean: (json['temperature_mean'] as num?)?.toDouble(),
        precipitationSum: (json['precipitation_sum'] as num?)?.toDouble(),
      );
}

class HistoricalWeather {
  final String startDate;
  final String endDate;
  final List<HistoricalDaily> daily;
  final HistoricalStats stats;

  const HistoricalWeather({
    required this.startDate,
    required this.endDate,
    required this.daily,
    required this.stats,
  });

  factory HistoricalWeather.fromJson(Map<String, dynamic> json) =>
      HistoricalWeather(
        startDate: json['start_date'] as String? ?? '',
        endDate: json['end_date'] as String? ?? '',
        daily: (json['daily'] as List<dynamic>?)
                ?.map((e) => HistoricalDaily.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        stats: HistoricalStats.fromJson(
            json['stats'] as Map<String, dynamic>? ?? {}),
      );
}

class ClimateTrendMonth {
  final String month;
  final double? avgTempMax;
  final double? avgTempMin;
  final double? avgTempMean;
  final double? totalPrecipitation;
  final int wetDays;

  const ClimateTrendMonth({
    required this.month,
    this.avgTempMax,
    this.avgTempMin,
    this.avgTempMean,
    this.totalPrecipitation,
    this.wetDays = 0,
  });

  factory ClimateTrendMonth.fromJson(Map<String, dynamic> json) =>
      ClimateTrendMonth(
        month: json['month'] as String? ?? '',
        avgTempMax: (json['avg_temp_max'] as num?)?.toDouble(),
        avgTempMin: (json['avg_temp_min'] as num?)?.toDouble(),
        avgTempMean: (json['avg_temp_mean'] as num?)?.toDouble(),
        totalPrecipitation: (json['total_precipitation'] as num?)?.toDouble(),
        wetDays: (json['wet_days'] as num?)?.toInt() ?? 0,
      );
}

class ClimateTrend {
  final int years;
  final List<ClimateTrendMonth> monthly;
  final double? warmingTrendCPerDecade;
  final double? annualPrecipitationMm;
  final double? currentMonthAnomalyC;

  const ClimateTrend({
    required this.years,
    required this.monthly,
    this.warmingTrendCPerDecade,
    this.annualPrecipitationMm,
    this.currentMonthAnomalyC,
  });

  factory ClimateTrend.fromJson(Map<String, dynamic> json) => ClimateTrend(
        years: (json['years'] as num?)?.toInt() ?? 0,
        monthly: (json['monthly'] as List<dynamic>?)
                ?.map((e) =>
                    ClimateTrendMonth.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        warmingTrendCPerDecade:
            (json['warming_trend_c_per_decade'] as num?)?.toDouble(),
        annualPrecipitationMm:
            (json['annual_precipitation_mm'] as num?)?.toDouble(),
        currentMonthAnomalyC:
            (json['current_month_anomaly_c'] as num?)?.toDouble(),
      );
}

// ---------------- Crop advisories ----------------

class CropAdvisoryItem {
  final String category;
  final String severity;
  final String message;

  const CropAdvisoryItem({
    required this.category,
    required this.severity,
    required this.message,
  });

  factory CropAdvisoryItem.fromJson(Map<String, dynamic> json) =>
      CropAdvisoryItem(
        category: json['category'] as String? ?? 'general',
        severity: json['severity'] as String? ?? 'info',
        message: json['message'] as String? ?? '',
      );
}

class CropAdvisory {
  final String location;
  final String? crop;
  final List<CropAdvisoryItem> advisories;
  final int? fieldWorkScore;
  final bool? irrigationNeeded;

  const CropAdvisory({
    required this.location,
    this.crop,
    required this.advisories,
    this.fieldWorkScore,
    this.irrigationNeeded,
  });

  factory CropAdvisory.fromJson(Map<String, dynamic> json) => CropAdvisory(
        location: json['location'] as String? ?? 'Unknown',
        crop: json['crop'] as String?,
        advisories: (json['advisories'] as List<dynamic>?)
                ?.map((e) =>
                    CropAdvisoryItem.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        fieldWorkScore: (json['field_work_score'] as num?)?.toInt(),
        irrigationNeeded: json['irrigation_needed'] as bool?,
      );
}

// ---------------- Aviation briefing ----------------

class AviationConditionItem {
  final String parameter;
  final String status;
  final String? value;
  final String? note;

  const AviationConditionItem({
    required this.parameter,
    required this.status,
    this.value,
    this.note,
  });

  factory AviationConditionItem.fromJson(Map<String, dynamic> json) =>
      AviationConditionItem(
        parameter: json['parameter'] as String? ?? '',
        status: json['status'] as String? ?? 'ok',
        value: json['value'] as String?,
        note: json['note'] as String?,
      );
}

class AviationBriefing {
  final String location;
  final String flightCategory;
  final String summary;
  final List<AviationConditionItem> conditions;
  final List<String> bestWindows;

  const AviationBriefing({
    required this.location,
    required this.flightCategory,
    required this.summary,
    required this.conditions,
    required this.bestWindows,
  });

  factory AviationBriefing.fromJson(Map<String, dynamic> json) =>
      AviationBriefing(
        location: json['location'] as String? ?? 'Unknown',
        flightCategory: json['flight_category'] as String? ?? 'unknown',
        summary: json['summary'] as String? ?? '',
        conditions: (json['conditions'] as List<dynamic>?)
                ?.map((e) =>
                    AviationConditionItem.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        bestWindows: (json['best_windows'] as List<dynamic>?)
                ?.map((e) => e as String)
                .toList() ??
            [],
      );
}

// ---------------- City overview ----------------

class CitySnapshot {
  final String name;
  final double? temperature;
  final double? humidity;
  final double? windSpeed;
  final String? condition;
  final int? aqi;

  const CitySnapshot({
    required this.name,
    this.temperature,
    this.humidity,
    this.windSpeed,
    this.condition,
    this.aqi,
  });

  factory CitySnapshot.fromJson(Map<String, dynamic> json) => CitySnapshot(
        name: json['name'] as String? ?? 'Unknown',
        temperature: (json['temperature'] as num?)?.toDouble(),
        humidity: (json['humidity'] as num?)?.toDouble(),
        windSpeed: (json['wind_speed'] as num?)?.toDouble(),
        condition: json['condition'] as String?,
        aqi: (json['aqi'] as num?)?.toInt(),
      );
}

class CityOverview {
  final List<CitySnapshot> cities;

  const CityOverview({required this.cities});

  factory CityOverview.fromJson(Map<String, dynamic> json) => CityOverview(
        cities: (json['cities'] as List<dynamic>?)
                ?.map((e) => CitySnapshot.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
      );
}
