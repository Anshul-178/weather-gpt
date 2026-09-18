import 'package:flutter_test/flutter_test.dart';

import 'package:weathergpt/services/api_service.dart';

void main() {
  group('retry', () {
    test('succeeds on first attempt', () async {
      var called = 0;
      final result = await retry(() async {
        called++;
        return 'ok';
      });
      expect(result, 'ok');
      expect(called, 1);
    });

    test('retries on ApiException with retryable status code', () async {
      var called = 0;
      final error = ApiException('fail', 503);
      await expectLater(
        retry(() async {
          called++;
          throw error;
        }),
        throwsA(isA<ApiException>()),
      );
      // 3 attempts: initial + 2 retries
      expect(called, 3);
    });

    test('does not retry on non-retryable status code', () async {
      var called = 0;
      final error = ApiException('bad request', 400);
      await expectLater(
        retry(() async {
          called++;
          throw error;
        }),
        throwsA(isA<ApiException>()),
      );
      expect(called, 1);
    });

    test('does not retry after maxAttempts', () async {
      var called = 0;
      await expectLater(
        retry(
          () async {
            called++;
            throw ApiException('fail', 500);
          },
          maxAttempts: 2,
        ),
        throwsA(isA<ApiException>()),
      );
      expect(called, 2);
    });

    test('retryable status codes are 408, 500, 502, 503, 504', () {
      expect(retryableStatusCodes, contains(408));
      expect(retryableStatusCodes, contains(500));
      expect(retryableStatusCodes, contains(502));
      expect(retryableStatusCodes, contains(503));
      expect(retryableStatusCodes, contains(504));
      expect(retryableStatusCodes, isNot(contains(400)));
      expect(retryableStatusCodes, isNot(contains(401)));
      expect(retryableStatusCodes, isNot(contains(404)));
    });

    test('429 is deliberately not retried (provider sends Retry-After)', () async {
      var called = 0;
      await expectLater(
        retry(() async {
          called++;
          throw ApiException('rate limited', 429);
        }),
        throwsA(isA<ApiException>()),
      );
      expect(called, 1);
    });

    test('succeeds after one retry', () async {
      var called = 0;
      final result = await retry(() async {
        called++;
        if (called == 1) throw ApiException('temp fail', 502);
        return 'recovered';
      });
      expect(result, 'recovered');
      expect(called, 2);
    });
  });

  group('ApiException', () {
    test('toString returns the message', () {
      final e = ApiException('test error', 500);
      expect(e.toString(), 'test error');
    });

    test('holds status code', () {
      final e = ApiException('not found', 404);
      expect(e.statusCode, 404);
      expect(e.message, 'not found');
    });
  });

  group('ApiService.isRetrying', () {
    test('starts as false', () {
      expect(ApiService.instance.isRetrying.value, false);
    });
  });
}
