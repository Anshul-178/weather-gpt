// Saved location + geocoding models.

class SavedLocation {
  final int id;
  final String name;
  final double latitude;
  final double longitude;

  const SavedLocation({
    required this.id,
    required this.name,
    required this.latitude,
    required this.longitude,
  });

  factory SavedLocation.fromJson(Map<String, dynamic> json) => SavedLocation(
        id: (json['id'] as num?)?.toInt() ?? 0,
        name: json['name'] as String? ?? 'Unknown',
        latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
        longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
      );
}

class GeocodeResult {
  final String name;
  final double latitude;
  final double longitude;
  final String? country;
  final String? admin1;

  const GeocodeResult({
    required this.name,
    required this.latitude,
    required this.longitude,
    this.country,
    this.admin1,
  });

  String get displayName {
    final parts = [name];
    if (admin1 != null && admin1 != name) parts.add(admin1!);
    if (country != null) parts.add(country!);
    return parts.join(', ');
  }

  factory GeocodeResult.fromJson(Map<String, dynamic> json) => GeocodeResult(
        name: json['name'] as String? ?? 'Unknown',
        latitude: (json['latitude'] as num?)?.toDouble() ?? 0,
        longitude: (json['longitude'] as num?)?.toDouble() ?? 0,
        country: json['country'] as String?,
        admin1: json['admin1'] as String?,
      );
}
