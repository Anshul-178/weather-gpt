import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';

import '../models/saved_location.dart';
import '../models/weather.dart';
import '../providers/app_state.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';

/// Locations screen: search, switch, save, delete.
class LocationsScreen extends StatefulWidget {
  const LocationsScreen({super.key});

  @override
  State<LocationsScreen> createState() => _LocationsScreenState();
}

class _LocationsScreenState extends State<LocationsScreen> {
  final WeatherRepository _repository = WeatherRepository();
  final TextEditingController _searchController = TextEditingController();

  List<GeocodeResult> _results = [];
  List<SavedLocation> _saved = [];
  bool _searching = false;
  bool _locating = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadSaved();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadSaved() async {
    if (!context.read<AppState>().isAuthenticated) return;
    try {
      final saved = await _repository.listLocations();
      if (mounted) setState(() => _saved = saved);
    } on ApiException {
      // Silent: saved locations require login.
    }
  }

  Future<void> _search() async {
    final query = _searchController.text.trim();
    if (query.isEmpty) return;
    setState(() {
      _searching = true;
      _error = null;
    });
    try {
      final results = await _repository.searchLocations(query);
      setState(() => _results = results);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } finally {
      setState(() => _searching = false);
    }
  }

  Future<void> _select(GeoLocationLike location) async {
    await context.read<AppState>().setLocation(
          GeoLocation(
            name: location.name,
            latitude: location.latitude,
            longitude: location.longitude,
          ),
        );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Location set to ${location.name}')),
    );
  }

  Future<void> _saveCurrent() async {
    final app = context.read<AppState>();
    if (app.location == null) return;
    if (!app.isAuthenticated) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Log in to save locations.')));
      return;
    }
    try {
      await _repository.saveLocation(
        app.location!.name,
        app.location!.latitude,
        app.location!.longitude,
      );
      await _loadSaved();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Location saved.')));
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _deleteSaved(SavedLocation saved) async {
    try {
      await _repository.deleteLocation(saved.id);
      await _loadSaved();
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _saveResult(GeocodeResult result) async {
    try {
      await _repository.saveLocation(
          result.displayName, result.latitude, result.longitude);
      await _loadSaved();
    } on ApiException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(title: const Text('Locations')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          // ---- GPS tile ----
          Container(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  Theme.of(context).colorScheme.primaryContainer,
                  Theme.of(context)
                      .colorScheme
                      .primaryContainer
                      .withValues(alpha: 0.4),
                ],
              ),
              borderRadius: BorderRadius.circular(20),
            ),
            child: ListTile(
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              leading: _locating
                  ? const SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(strokeWidth: 2.5))
                  : CircleAvatar(
                      backgroundColor:
                          Theme.of(context).colorScheme.primary,
                      child: const Icon(Icons.my_location_rounded,
                          color: Colors.white, size: 20),
                    ),
              title: const Text('Use current location',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              subtitle: Text(
                app.location?.name ?? 'Detect via GPS',
                style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: _locating
                  ? null
                  : () async {
                      setState(() => _locating = true);
                      final messenger = ScaffoldMessenger.of(context);
                      final reason =
                          await context.read<AppState>().useCurrentLocation();
                      if (!mounted) return;
                      setState(() => _locating = false);
                      if (reason == null) {
                        messenger.showSnackBar(SnackBar(
                          content: Text(
                              'Location updated to ${app.location?.name ?? 'current position'}.'),
                        ));
                        return;
                      }
                      final SnackBarAction? action;
                      if (reason.contains('services')) {
                        action = const SnackBarAction(
                          label: 'Open settings',
                          onPressed: Geolocator.openLocationSettings,
                        );
                      } else if (reason.contains('blocked') ||
                          reason.contains('denied')) {
                        action = const SnackBarAction(
                          label: 'Open app settings',
                          onPressed: Geolocator.openAppSettings,
                        );
                      } else {
                        action = null;
                      }
                      messenger.showSnackBar(SnackBar(
                        content: Text(reason),
                        action: action,
                      ));
                    },
            ),
          ),
          const SizedBox(height: 20),
          // ---- Search ----
          TextField(
            controller: _searchController,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              hintText: 'Search city (e.g. Kanpur, Delhi)',
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: _searching
                  ? const Padding(
                      padding: EdgeInsets.all(12),
                      child:
                          SizedBox(width: 20, height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2)),
                    )
                  : _searchController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.close_rounded),
                          onPressed: () {
                            _searchController.clear();
                            setState(() => _results = []);
                          },
                        )
                      : null,
            ),
            onChanged: (_) => setState(() {}),
            onSubmitted: (_) => _search(),
          ),
          const SizedBox(height: 16),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(_error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ),
          ..._results.map((result) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(20)),
                  leading: const Icon(Icons.location_city_rounded),
                  title: Text(result.displayName),
                  trailing: app.isAuthenticated
                      ? IconButton(
                          icon: const Icon(Icons.bookmark_add_outlined),
                          tooltip: 'Save',
                          onPressed: () => _saveResult(result),
                        )
                      : null,
                  onTap: () => _select(GeoLocationLike(
                    name: result.displayName,
                    latitude: result.latitude,
                    longitude: result.longitude,
                  )),
                ),
              )),
          if (_saved.isNotEmpty || app.isAuthenticated) ...[
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text('Saved locations',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w700)),
                TextButton.icon(
                  onPressed: app.location == null ? null : _saveCurrent,
                  icon: const Icon(Icons.add_location_alt_outlined, size: 18),
                  label: const Text('Save current'),
                ),
              ],
            ),
          ],
          ..._saved.map((saved) => Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(20)),
                  leading: const Icon(Icons.bookmark_rounded),
                  title: Text(saved.name),
                  subtitle: Text(
                      '${saved.latitude.toStringAsFixed(2)}, '
                      '${saved.longitude.toStringAsFixed(2)}'),
                  trailing: IconButton(
                    icon: const Icon(Icons.delete_outline_rounded),
                    onPressed: () => _deleteSaved(saved),
                  ),
                  onTap: () => _select(GeoLocationLike(
                    name: saved.name,
                    latitude: saved.latitude,
                    longitude: saved.longitude,
                  )),
                ),
              )),
        ],
      ),
    );
  }
}

/// Simple lat/lon/name holder for selection.
class GeoLocationLike {
  final String name;
  final double latitude;
  final double longitude;
  GeoLocationLike({
    required this.name,
    required this.latitude,
    required this.longitude,
  });
}
