import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config.dart';

/// Transient status codes that are worth retrying.
///
/// 429 is deliberately excluded: the backend answers 429 with a Retry-After
/// and its own cooldown, so retrying after a fixed 2s delay only hammers the
/// provider again and keeps the rate-limit window alive. Surface the server's
/// message instead and let the user refresh when they choose.
const retryableStatusCodes = {408, 500, 502, 503, 504};

/// Lightweight retry helper for transient failures.
Future<T> retry<T>(
  Future<T> Function() fn, {
  int maxAttempts = 3,
  Duration baseDelay = const Duration(seconds: 2),
  bool notifyRetrying = false,
}) async {
  int attempt = 0;
  while (true) {
    try {
      return await fn();
    } on ApiException catch (e) {
      attempt++;
      if (attempt >= maxAttempts || e.statusCode != null &&
          !retryableStatusCodes.contains(e.statusCode)) {
        rethrow;
      }
      final delay = baseDelay * (1 << (attempt - 1));
      debugPrint('Retry $attempt/$maxAttempts after ${delay.inSeconds}s: $e');
      // Inform any listening UI that a retry is in progress.
      if (notifyRetrying) {
        try {
          ApiService.instance.isRetrying.value = true;
          await Future.delayed(delay);
        } finally {
          ApiService.instance.isRetrying.value = false;
        }
      } else {
        await Future.delayed(delay);
      }
    }
  }
}

/// Errors surfaced to the UI in a friendly form.
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  ApiException(this.message, [this.statusCode]);

  @override
  String toString() => message;
}

/// Dedicated WeatherGPT API client.
///
/// All calls go to the WeatherGPT FastAPI backend; no third-party secrets
/// are stored in this app.
class ApiService {
  ApiService._();

  static final ApiService instance = ApiService._();

  final http.Client _client = http.Client();
  String? _accessToken;

  /// Controls for UI -- callers can listen to these via a simple accessor.
  final ValueNotifier<bool> isRetrying = ValueNotifier<bool>(false);

  void setAuthToken(String? token) => _accessToken = token;

  Map<String, String> get _headers {
    final headers = <String, String>{'Content-Type': 'application/json'};
    final token = _accessToken;
    if (token != null) {
      headers['Authorization'] = 'Bearer $token';
    }
    return headers;
  }

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${AppConfig.apiBaseUrl}$path').replace(queryParameters: query);

  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    return retry(() async {
      final response = await _client
          .get(_uri(path, query), headers: _headers)
          .timeout(AppConfig.requestTimeout);
      return _handle(response);
    }, notifyRetrying: true);
  }

  Future<dynamic> post(String path, Map<String, dynamic> body) async {
    return retry(() async {
      final response = await _client
          .post(_uri(path), headers: _headers, body: jsonEncode(body))
          .timeout(AppConfig.requestTimeout);
      return _handle(response);
    }, notifyRetrying: true);
  }

  Future<dynamic> patch(String path, Map<String, dynamic> body) async {
    return retry(() async {
      final response = await _client
          .patch(_uri(path), headers: _headers, body: jsonEncode(body))
          .timeout(AppConfig.requestTimeout);
      return _handle(response);
    }, notifyRetrying: true);
  }

  Future<void> delete(String path) async {
    await retry(() async {
      final response = await _client
          .delete(_uri(path), headers: _headers)
          .timeout(AppConfig.requestTimeout);
      if (response.statusCode >= 400) {
        throw ApiException(_extractMessage(response), response.statusCode);
      }
    }, notifyRetrying: true);
  }

  dynamic _handle(http.Response response) {
    if (response.body.isNotEmpty) {
      // Backend error pages (for example Render/connectivity pages) can return
      // HTML instead of JSON. Treat that as a network error instead of crashing
      // on jsonDecode.
      if (!response.body.trim().startsWith('{') &&
          !response.body.trim().startsWith('[')) {
        throw ApiException(
          'Could not reach the WeatherGPT server.',
          response.statusCode,
        );
      }
      try {
        return jsonDecode(response.body) as Map<String, dynamic>;
      } on FormatException catch (e) {
        throw ApiException(
          'Could not reach the WeatherGPT server.\n\nDebug: $e',
          response.statusCode,
        );
      }
    }
    return <String, dynamic>{};
  }

  String _extractMessage(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      if (body is Map && body['error'] is Map) {
        return body['error']['message'] as String? ?? 'Request failed.';
      }
      if (body is Map && body['detail'] is String) {
        return body['detail'] as String;
      }
    } catch (_) {}
    return 'Request failed (${response.statusCode}).';
  }

  void dispose() => _client.close();
}
