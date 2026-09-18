// Offline city fallback for location search.
//
// Used when the backend geocoder is unreachable (e.g. the Render free tier
// cold-starting, or no connection). Filters a small curated list of cities so
// the Locations search still returns something useful instead of an error.
//
// Results use the same GeocodeResult model as the backend geocoder, so the
// UI treats them identically.

import '../models/saved_location.dart';

class _OfflineCity {
  final String name;
  final String admin1;
  final String country;
  final double latitude;
  final double longitude;

  const _OfflineCity(this.name, this.admin1, this.country, this.latitude, this.longitude);
}

/// Curated list: larger Indian cities first (the product's home market),
/// then major world cities.
const List<_OfflineCity> _kCities = [
  // India
  _OfflineCity('Kanpur', 'Uttar Pradesh', 'IN', 26.4499, 80.3319),
  _OfflineCity('Lucknow', 'Uttar Pradesh', 'IN', 26.8467, 80.9462),
  _OfflineCity('Delhi', 'Delhi', 'IN', 28.6139, 77.2090),
  _OfflineCity('New Delhi', 'Delhi', 'IN', 28.6139, 77.2090),
  _OfflineCity('Noida', 'Uttar Pradesh', 'IN', 28.5355, 77.3910),
  _OfflineCity('Gurugram', 'Haryana', 'IN', 28.4595, 77.0266),
  _OfflineCity('Mumbai', 'Maharashtra', 'IN', 19.0760, 72.8777),
  _OfflineCity('Pune', 'Maharashtra', 'IN', 18.5204, 73.8567),
  _OfflineCity('Nagpur', 'Maharashtra', 'IN', 21.1458, 79.0882),
  _OfflineCity('Bengaluru', 'Karnataka', 'IN', 12.9716, 77.5946),
  _OfflineCity('Mysuru', 'Karnataka', 'IN', 12.2958, 76.6394),
  _OfflineCity('Chennai', 'Tamil Nadu', 'IN', 13.0827, 80.2707),
  _OfflineCity('Coimbatore', 'Tamil Nadu', 'IN', 11.0168, 76.9558),
  _OfflineCity('Hyderabad', 'Telangana', 'IN', 17.3850, 78.4867),
  _OfflineCity('Warangal', 'Telangana', 'IN', 17.9689, 79.5941),
  _OfflineCity('Ahmedabad', 'Gujarat', 'IN', 23.0225, 72.5714),
  _OfflineCity('Surat', 'Gujarat', 'IN', 21.1702, 72.8311),
  _OfflineCity('Jaipur', 'Rajasthan', 'IN', 26.9124, 75.7873),
  _OfflineCity('Jodhpur', 'Rajasthan', 'IN', 26.2389, 73.0243),
  _OfflineCity('Kolkata', 'West Bengal', 'IN', 22.5726, 88.3639),
  _OfflineCity('Howrah', 'West Bengal', 'IN', 22.5958, 88.2636),
  _OfflineCity('Bhopal', 'Madhya Pradesh', 'IN', 23.2599, 77.4126),
  _OfflineCity('Indore', 'Madhya Pradesh', 'IN', 22.7196, 75.8577),
  _OfflineCity('Patna', 'Bihar', 'IN', 25.5941, 85.1376),
  _OfflineCity('Varanasi', 'Uttar Pradesh', 'IN', 25.3176, 82.9739),
  _OfflineCity('Prayagraj', 'Uttar Pradesh', 'IN', 25.4358, 81.8463),
  _OfflineCity('Agra', 'Uttar Pradesh', 'IN', 27.1767, 78.0081),
  _OfflineCity('Chandigarh', 'Chandigarh', 'IN', 30.7333, 76.7794),
  _OfflineCity('Amritsar', 'Punjab', 'IN', 31.6340, 74.8723),
  _OfflineCity('Kochi', 'Kerala', 'IN', 9.9312, 76.2673),
  _OfflineCity('Thiruvananthapuram', 'Kerala', 'IN', 8.5241, 76.9366),
  _OfflineCity('Visakhapatnam', 'Andhra Pradesh', 'IN', 17.6868, 83.2185),
  _OfflineCity('Bhubaneswar', 'Odisha', 'IN', 20.2961, 85.8245),
  _OfflineCity('Guwahati', 'Assam', 'IN', 26.1445, 91.7362),
  _OfflineCity('Dehradun', 'Uttarakhand', 'IN', 30.3165, 78.0322),
  _OfflineCity('Shimla', 'Himachal Pradesh', 'IN', 31.1048, 77.1734),
  _OfflineCity('Srinagar', 'Jammu and Kashmir', 'IN', 34.0837, 74.7973),
  _OfflineCity('Goa', 'Goa', 'IN', 15.2993, 74.1240),
  // World
  _OfflineCity('London', 'England', 'GB', 51.5074, -0.1278),
  _OfflineCity('Manchester', 'England', 'GB', 53.4808, -2.2426),
  _OfflineCity('Dublin', 'Leinster', 'IE', 53.3498, -6.2603),
  _OfflineCity('Paris', 'Île-de-France', 'FR', 48.8566, 2.3522),
  _OfflineCity('Berlin', 'Berlin', 'DE', 52.5200, 13.4050),
  _OfflineCity('Madrid', 'Madrid', 'ES', 40.4168, -3.7038),
  _OfflineCity('Rome', 'Lazio', 'IT', 41.9028, 12.4964),
  _OfflineCity('Amsterdam', 'North Holland', 'NL', 52.3676, 4.9041),
  _OfflineCity('Zurich', 'Zurich', 'CH', 47.3769, 8.5417),
  _OfflineCity('Stockholm', 'Stockholm', 'SE', 59.3293, 18.0686),
  _OfflineCity('Istanbul', 'Istanbul', 'TR', 41.0082, 28.9784),
  _OfflineCity('Dubai', 'Dubai', 'AE', 25.2048, 55.2708),
  _OfflineCity('Singapore', 'Singapore', 'SG', 1.3521, 103.8198),
  _OfflineCity('Tokyo', 'Tokyo', 'JP', 35.6762, 139.6503),
  _OfflineCity('Seoul', 'Seoul', 'KR', 37.5665, 126.9780),
  _OfflineCity('Beijing', 'Beijing', 'CN', 39.9042, 116.4074),
  _OfflineCity('Sydney', 'New South Wales', 'AU', -33.8688, 151.2093),
  _OfflineCity('Melbourne', 'Victoria', 'AU', -37.8136, 144.9631),
  _OfflineCity('Auckland', 'Auckland', 'NZ', -36.8485, 174.7633),
  _OfflineCity('New York', 'New York', 'US', 40.7128, -74.0060),
  _OfflineCity('Boston', 'Massachusetts', 'US', 42.3601, -71.0589),
  _OfflineCity('Chicago', 'Illinois', 'US', 41.8781, -87.6298),
  _OfflineCity('Austin', 'Texas', 'US', 30.2672, -97.7431),
  _OfflineCity('Seattle', 'Washington', 'US', 47.6062, -122.3321),
  _OfflineCity('San Francisco', 'California', 'US', 37.7749, -122.4194),
  _OfflineCity('Los Angeles', 'California', 'US', 34.0522, -118.2437),
  _OfflineCity('Toronto', 'Ontario', 'CA', 43.6532, -79.3832),
  _OfflineCity('Vancouver', 'British Columbia', 'CA', 49.2827, -123.1207),
  _OfflineCity('Mexico City', 'CDMX', 'MX', 19.4326, -99.1332),
  _OfflineCity('São Paulo', 'São Paulo', 'BR', -23.5505, -46.6333),
  _OfflineCity('Buenos Aires', 'Buenos Aires', 'AR', -34.6037, -58.3816),
  _OfflineCity('Cape Town', 'Western Cape', 'ZA', -33.9249, 18.4241),
  _OfflineCity('Nairobi', 'Nairobi', 'KE', -1.2921, 36.8219),
  _OfflineCity('Cairo', 'Cairo', 'EG', 30.0444, 31.2357),
];

/// Search the offline list. Simple case-insensitive prefix/substring match,
/// with prefix matches ranked before substring matches.
List<GeocodeResult> searchOfflineCities(String query, {int limit = 8}) {
  final q = query.trim().toLowerCase();
  if (q.isEmpty) return const [];

  final prefix = <GeocodeResult>[];
  final contains = <GeocodeResult>[];
  for (final city in _kCities) {
    final name = city.name.toLowerCase();
    final entry = GeocodeResult(
      name: city.name,
      latitude: city.latitude,
      longitude: city.longitude,
      country: city.country,
      admin1: city.admin1,
    );
    if (name.startsWith(q)) {
      prefix.add(entry);
    } else if (name.contains(q) ||
        city.admin1.toLowerCase().contains(q) ||
        city.country.toLowerCase() == q) {
      contains.add(entry);
    }
    if (prefix.length >= limit) break;
  }
  return [...prefix, ...contains].take(limit).toList();
}
