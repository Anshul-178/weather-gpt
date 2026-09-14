import '../models/insights.dart';
import '../models/saved_location.dart';
import '../models/weather.dart';
import '../services/api_service.dart';

/// Repository bundling all WeatherGPT API operations.
class WeatherRepository {
  final ApiService _api = ApiService.instance;

  // ---------------- Weather ---------------- //

  Future<WeatherBundle> fetchWeather(double lat, double lon,
      {String? locationName}) async {
    final results = await Future.wait([
      _api.get('/weather/current', {
        'latitude': '$lat', 'longitude': '$lon',
        if (locationName != null) 'location_name': locationName,
      }),
      _api.get('/weather/forecast', {'latitude': '$lat', 'longitude': '$lon', 'days': '7'}),
    ]);
    final currentJson = results[0] as Map<String, dynamic>;
    final forecastJson = results[1] as Map<String, dynamic>;
    return WeatherBundle(
      location: GeoLocation.fromJson(currentJson['location'] as Map<String, dynamic>),
      current: CurrentWeather.fromJson(currentJson['current'] as Map<String, dynamic>),
      hourly: (forecastJson['hourly'] as List<dynamic>?)
              ?.map((e) => HourlyPoint.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
      daily: (forecastJson['forecast'] as List<dynamic>?)
              ?.map((e) => DailyPoint.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [],
    );
  }

  Future<ActivityScore> fetchActivityScore(
      String activity, double lat, double lon) async {
    final json = await _api.post('/weather/activity-score', {
      'activity': activity,
      'latitude': lat,
      'longitude': lon,
      'day_offset': 0,
    });
    return ActivityScore.fromJson(json);
  }

  Future<List<GeocodeResult>> searchLocations(String query) async {
    final json = await _api.get('/weather/search', {'query': query});
    return (json['results'] as List<dynamic>?)
            ?.map((e) => GeocodeResult.fromJson(e as Map<String, dynamic>))
            .toList() ??
        [];
  }

  // ---------------- Chat ---------------- //

  Future<Map<String, dynamic>> sendChat(
      String message, double lat, double lon, int? conversationId, {String? locationName}) async {
    final json = await _api.post('/chat', {
      'message': message,
      'latitude': lat,
      'longitude': lon,
      'conversation_id': conversationId,
      if (locationName != null) 'location_name': locationName,
    });
    return json;
  }

  // ---------------- Saved locations ---------------- //

  Future<List<SavedLocation>> listLocations() async {
    final json = await _api.get('/locations');
    return (json as List<dynamic>)
        .map((e) => SavedLocation.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<SavedLocation> saveLocation(
      String name, double lat, double lon) async {
    final json = await _api.post('/locations', {
      'name': name,
      'latitude': lat,
      'longitude': lon,
    });
    return SavedLocation.fromJson(json);
  }

  Future<void> deleteLocation(int id) => _api.delete('/locations/$id');

  // ---------------- Alerts ---------------- //

  Future<List<dynamic>> listAlerts() async => await _api.get('/alerts');

  Future<Map<String, dynamic>> createAlert({
    required String alertType,
    double? threshold,
    required double lat,
    required double lon,
    String? locationName,
  }) async {
    return await _api.post('/alerts', {
      'alert_type': alertType,
      'threshold': threshold,
      'enabled': true,
      'latitude': lat,
      'longitude': lon,
      'location_name': locationName,
    });
  }

  Future<void> deleteAlert(int id) => _api.delete('/alerts/$id');

  // ---------------- Insights: climate / agriculture / aviation / city ----------------

  Future<HistoricalWeather> fetchHistorical(double lat, double lon, {int days = 30}) async {
    final json = await _api.get('/weather/historical', {
      'latitude': lat.toString(),
      'longitude': lon.toString(),
      'days': days.toString(),
    });
    return HistoricalWeather.fromJson(json);
  }

  Future<ClimateTrend> fetchClimateTrend(double lat, double lon, {int years = 5}) async {
    final json = await _api.get('/weather/climate', {
      'latitude': lat.toString(),
      'longitude': lon.toString(),
      'years': years.toString(),
    });
    return ClimateTrend.fromJson(json);
  }

  Future<CropAdvisory> fetchCropAdvisory(
      double lat, double lon, String locationName,
      {String? crop}) async {
    final json = await _api.post('/weather/crop-advisory', {
      'latitude': lat,
      'longitude': lon,
      'location_name': locationName,
      if (crop != null && crop.isNotEmpty) 'crop': crop,
    });
    return CropAdvisory.fromJson(json);
  }

  Future<AviationBriefing> fetchAviationBriefing(
      double lat, double lon, String locationName,
      {int hoursAhead = 12}) async {
    final json = await _api.post('/weather/aviation', {
      'latitude': lat,
      'longitude': lon,
      'location_name': locationName,
      'hours_ahead': hoursAhead,
    });
    return AviationBriefing.fromJson(json);
  }

  Future<CityOverview> fetchCityOverview() async {
    final json = await _api.get('/weather/city-overview');
    return CityOverview.fromJson(json);
  }

  // ---------------- Push notifications ----------------

  Future<void> registerForPush(String token,
      {String? platform, double? lat, double? lon}) async {
    await _api.post('/notifications/register', {
      'token': token,
      if (platform != null) 'platform': platform,
      if (lat != null) 'latitude': lat,
      if (lon != null) 'longitude': lon,
    });
  }
}
