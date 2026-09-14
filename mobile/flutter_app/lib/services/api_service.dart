import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/weather.dart';

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
    } catch (e) {
      // Log the actual error for debugging
      debugPrint('API get error: $e');
      throw ApiException('Could not reach the WeatherGPT server.\n\nDebug: $e');
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
    } catch (e) {
      // Log the actual error for debugging
      debugPrint('API post error: $e');
      throw ApiException('Could not reach the WeatherGPT server.\n\nDebug: $e');
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
    } catch (e) {
      // Log the actual error for debugging
      debugPrint('API patch error: $e');
      throw ApiException('Could not reach the WeatherGPT server.\n\nDebug: $e');
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
    } catch (e) {
      // Log the actual error for debugging
      debugPrint('API delete error: $e');
      throw ApiException('Could not reach the WeatherGPT server.\n\nDebug: $e');
    }
  }

  dynamic _handle(http.Response response) {
    final body = response.body.isNotEmpty
        ? jsonDecode(response.body) as Map<String, dynamic>
        : <String, dynamic>{};
    if (response.statusCode >= 400) {
      throw ApiException(_extractMessage(response), response.statusCode);
    }
    return body;
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
