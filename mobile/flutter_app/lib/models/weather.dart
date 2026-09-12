// Weather and AQI data models matching the WeatherGPT API schemas.

// AQI models
class AQICurrent {
  final int? aqi;
  final double? pm2_5;
  final double? pm10;
  final double? o3;
  final double? no2;
  final double? so2;
  final double? co;
  final String? epaAqi;
  final String? dominantPollutant;

  const AQICurrent({
    this.aqi,
    this.pm2_5,
    this.pm10,
    this.o3,
    this.no2,
    this.so2,
    this.co,
    this.epaAqi,
    this.dominantPollutant,
  });

  factory AQICurrent.fromJson(Map<String, dynamic> json) => AQICurrent(
        aqi: json['aqi'] as int?,
        pm2_5: (json['pm2_5'] as num?)?.toDouble(),
        pm10: (json['pm10'] as num?)?.toDouble(),
        o3: (json['o3'] as num?)?.toDouble(),
        no2: (json['no2'] as num?)?.toDouble(),
        so2: (json['so2'] as num?)?.toDouble(),
        co: (json['co'] as num?)?.toDouble(),
        epaAqi: json['epa_aqi'] as String?,
        dominantPollutant: json['dominant_pollutant'] as String?,
      );
}

class AQIResponse {
  final String locationName;
  final double latitude;
  final double longitude;
  final AQICurrent current;
  final DateTime timestamp;

  const AQIResponse({
    required this.locationName,
    required this.latitude,
    required this.longitude,
    required this.current,
    required this.timestamp,
  });

  factory AQIResponse.fromJson(Map<String, dynamic> json) => AQIResponse(
        locationName: json['location_name'] as String? ?? 'Unknown',
        latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
        longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
        current: AQICurrent.fromJson(
            json['current'] as Map<String, dynamic>? ?? {}),
        timestamp: DateTime.tryParse(json['timestamp'] as String? ?? '') ??
            DateTime.now(),
      );

  int? get aqi => current.aqi;
  String? get category => current.epaAqi;
  double? get pm25 => current.pm2_5;

  String get aqiColor {
    final value = aqi ?? 0;
    if (value <= 50) return '#00E400';  // Green
    if (value <= 100) return '#FFFF00';  // Yellow
    if (value <= 150) return '#FF7E00';  // Orange
    if (value <= 200) return '#FF0000';  // Red
    if (value <= 300) return '#8F3F97';  // Purple
    return '#7E0023';  // Maroon
  }

  String get aqiDescription {
    final value = aqi ?? 0;
    if (value <= 50) return 'Air quality is satisfactory.';
    if (value <= 100) return 'Acceptable; moderate pollution.';
    if (value <= 150) return 'Unhealthy for sensitive groups.';
    if (value <= 200) return 'Unhealthy for everyone.';
    if (value <= 300) return 'Very unhealthy.';
    return 'Hazardous conditions.';
  }
}


class GeoLocation {
  final String name;
  final double latitude;
  final double longitude;

  const GeoLocation({
    required this.name,
    required this.latitude,
    required this.longitude,
  });

  factory GeoLocation.fromJson(Map<String, dynamic> json) => GeoLocation(
        name: json['name'] as String? ?? 'Unknown',
        latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
        longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
      );
}

class CurrentWeather {
  final double? temperature;
  final double? feelsLike;
  final double? humidity;
  final double? windSpeed;
  final String? windDirectionCompass;
  final double? pressure;
  final double? precipitation;
  final double? precipitationProbability;
  final double? cloudCover;
  final double? visibility;
  final double? uvIndex;
  final String? condition;
  final bool? isDay;

  const CurrentWeather({
    this.temperature,
    this.feelsLike,
    this.humidity,
    this.windSpeed,
    this.windDirectionCompass,
    this.pressure,
    this.precipitation,
    this.precipitationProbability,
    this.cloudCover,
    this.visibility,
    this.uvIndex,
    this.condition,
    this.isDay,
  });

  factory CurrentWeather.fromJson(Map<String, dynamic> json) => CurrentWeather(
        temperature: (json['temperature'] as num?)?.toDouble(),
        feelsLike: (json['feels_like'] as num?)?.toDouble(),
        humidity: (json['humidity'] as num?)?.toDouble(),
        windSpeed: (json['wind_speed'] as num?)?.toDouble(),
        windDirectionCompass: json['wind_direction_compass'] as String?,
        pressure: (json['pressure'] as num?)?.toDouble(),
        precipitation: (json['precipitation'] as num?)?.toDouble(),
        precipitationProbability:
            (json['precipitation_probability'] as num?)?.toDouble(),
        cloudCover: (json['cloud_cover'] as num?)?.toDouble(),
        visibility: (json['visibility'] as num?)?.toDouble(),
        uvIndex: (json['uv_index'] as num?)?.toDouble(),
        condition: json['condition'] as String?,
        isDay: json['is_day'] as bool?,
      );
}

class HourlyPoint {
  final DateTime time;
  final double? temperature;
  final double? precipitationProbability;
  final double? windSpeed;
  final String? condition;

  const HourlyPoint({
    required this.time,
    this.temperature,
    this.precipitationProbability,
    this.windSpeed,
    this.condition,
  });

  factory HourlyPoint.fromJson(Map<String, dynamic> json) => HourlyPoint(
        time: DateTime.tryParse(json['time'] as String? ?? '') ??
            DateTime.now(),
        temperature: (json['temperature'] as num?)?.toDouble(),
        precipitationProbability:
            (json['precipitation_probability'] as num?)?.toDouble(),
        windSpeed: (json['wind_speed'] as num?)?.toDouble(),
        condition: json['condition'] as String?,
      );
}

class DailyPoint {
  final String date;
  final double? temperatureMax;
  final double? temperatureMin;
  final double? precipitationProbability;
  final double? windSpeedMax;
  final double? uvIndexMax;
  final String? condition;

  const DailyPoint({
    required this.date,
    this.temperatureMax,
    this.temperatureMin,
    this.precipitationProbability,
    this.windSpeedMax,
    this.uvIndexMax,
    this.condition,
  });

  factory DailyPoint.fromJson(Map<String, dynamic> json) => DailyPoint(
        date: json['date'] as String? ?? '',
        temperatureMax: (json['temperature_max'] as num?)?.toDouble(),
        temperatureMin: (json['temperature_min'] as num?)?.toDouble(),
        precipitationProbability:
            (json['precipitation_probability'] as num?)?.toDouble(),
        windSpeedMax: (json['wind_speed_max'] as num?)?.toDouble(),
        uvIndexMax: (json['uv_index_max'] as num?)?.toDouble(),
        condition: json['condition'] as String?,
      );
}

class WeatherBundle {
  final GeoLocation location;
  final CurrentWeather current;
  final List<HourlyPoint> hourly;
  final List<DailyPoint> daily;

  const WeatherBundle({
    required this.location,
    required this.current,
    required this.hourly,
    required this.daily,
  });
}

class ActivityScoreFactor {
  final String name;
  final double score;
  final String detail;

  const ActivityScoreFactor({
    required this.name,
    required this.score,
    required this.detail,
  });

  factory ActivityScoreFactor.fromJson(Map<String, dynamic> json) =>
      ActivityScoreFactor(
        name: json['name'] as String? ?? '',
        score: (json['score'] as num?)?.toDouble() ?? 0,
        detail: json['detail'] as String? ?? '',
      );
}

class ActivityScore {
  final String activity;
  final int score;
  final String rating;
  final List<String> reasons;
  final List<ActivityScoreFactor> factors;
  final String? bestTime;

  const ActivityScore({
    required this.activity,
    required this.score,
    required this.rating,
    required this.reasons,
    required this.factors,
    this.bestTime,
  });

  factory ActivityScore.fromJson(Map<String, dynamic> json) => ActivityScore(
        activity: json['activity'] as String? ?? '',
        score: (json['score'] as num?)?.toInt() ?? 0,
        rating: json['rating'] as String? ?? '',
        reasons:
            (json['reasons'] as List<dynamic>?)?.map((e) => e as String).toList() ??
                [],
        factors: (json['factors'] as List<dynamic>?)
                ?.map((e) => ActivityScoreFactor.fromJson(e as Map<String, dynamic>))
                .toList() ??
            [],
        bestTime: json['best_time'] as String?,
      );
}
