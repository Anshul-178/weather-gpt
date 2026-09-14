import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config.dart';

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
    try {
      final response = await _client
          .get(_uri(path, query), headers: _headers)
          .timeout(AppConfig.requestTimeout);
      return _handle(response);
    } on TimeoutException {
      throw ApiException('The request timed out. Please try again.');
    } on ApiException {
      rethrow; // Surface real backend errors instead of masking them.
    } on FormatException {
      // Backend returned non-JSON (for example an HTML error page).
      throw ApiException('Could not reach the WeatherGPT server.');
    } catch (e) {
      debugPrint('API get error: $e');
      throw ApiException('Could not reach the WeatherGPT server.');
    }
  }

  Future<dynamic> post(String path, Map<String, dynamic> body) async {
    try {
      final response = await _client
          .post(_uri(path), headers: _headers, body: jsonEncode(body))
          .timeout(AppConfig.requestTimeout);
      return _handle(response);
    } on TimeoutException {
      throw ApiException('The request timed out. Please try again.');
    } on ApiException {
      rethrow; // Surface real backend errors instead of masking them.
    } on FormatException {
      throw ApiException('Could not reach the WeatherGPT server.');
    } catch (e) {
      debugPrint('API post error: $e');
      throw ApiException('Could not reach the WeatherGPT server.');
    }
  }

  Future<dynamic> patch(String path, Map<String, dynamic> body) async {
    try {
      final response = await _client
          .patch(_uri(path), headers: _headers, body: jsonEncode(body))
          .timeout(AppConfig.requestTimeout);
      return _handle(response);
    } on TimeoutException {
      throw ApiException('The request timed out. Please try again.');
    } on ApiException {
      rethrow; // Surface real backend errors instead of masking them.
    } on FormatException {
      throw ApiException('Could not reach the WeatherGPT server.');
    } catch (e) {
      debugPrint('API patch error: $e');
      throw ApiException('Could not reach the WeatherGPT server.');
    }
  }

  Future<void> delete(String path) async {
    try {
      final response = await _client
          .delete(_uri(path), headers: _headers)
          .timeout(AppConfig.requestTimeout);
      if (response.statusCode >= 400) {
        throw ApiException(_extractMessage(response), response.statusCode);
      }
    } on TimeoutException {
      throw ApiException('The request timed out. Please try again.');
    } on ApiException {
      rethrow;
    } on FormatException {
      throw ApiException('Could not reach the WeatherGPT server.');
    } catch (e) {
      debugPrint('API delete error: $e');
      throw ApiException('Could not reach the WeatherGPT server.');
    }
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
