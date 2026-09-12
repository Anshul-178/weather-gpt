import 'package:flutter/material.dart';

/// Maps weather condition text to a matching icon.
class WeatherIcon {
  WeatherIcon._();

  static IconData fromCondition(String? condition) {
    final c = (condition ?? '').toLowerCase();
    if (c.contains('thunder')) return Icons.flash_on_rounded;
    if (c.contains('drizzle') || c.contains('rain')) {
      return c.contains('heavy')
          ? Icons.umbrella_rounded
          : Icons.water_drop_rounded;
    }
    if (c.contains('snow') || c.contains('sleet')) {
      return Icons.ac_unit_rounded;
    }
    if (c.contains('fog') || c.contains('mist') || c.contains('haze')) {
      return Icons.blur_on_rounded;
    }
    if (c.contains('overcast')) return Icons.cloud_rounded;
    if (c.contains('cloud')) return Icons.cloud_queue_rounded;
    if (c.contains('clear') || c.contains('sunny') || c.contains('sun')) {
      return Icons.wb_sunny_rounded;
    }
    return Icons.wb_twilight_rounded;
  }

  /// Gradient palette that reflects the current conditions.
  static List<Color> heroGradient(String? condition, bool isDark) {
    final c = (condition ?? '').toLowerCase();
    if (c.contains('thunder')) {
      return isDark
          ? const [Color(0xFF312E5F), Color(0xFF1B1830)]
          : const [Color(0xFF4A3F8F), Color(0xFF232746)];
    }
    if (c.contains('rain') || c.contains('drizzle')) {
      return isDark
          ? const [Color(0xFF1E3A5C), Color(0xFF101B2C)]
          : const [Color(0xFF3D6FA8), Color(0xFF1F3B60)];
    }
    if (c.contains('snow')) {
      return isDark
          ? const [Color(0xFF2C4A66), Color(0xFF16283A)]
          : const [Color(0xFF7FA8CC), Color(0xFF4A6E93)];
    }
    if (c.contains('cloud') || c.contains('fog') || c.contains('mist')) {
      return isDark
          ? const [Color(0xFF3A3F55), Color(0xFF1F2230)]
          : const [Color(0xFF64748E), Color(0xFF39435C)];
    }
    // Clear / default: sunny blue sky.
    return isDark
        ? const [Color(0xFF1C3A7A), Color(0xFF101A3A)]
        : const [Color(0xFF3F7FE8), Color(0xFF1E3A8A)];
  }
}
