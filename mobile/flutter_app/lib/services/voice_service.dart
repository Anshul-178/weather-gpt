import 'dart:async';
import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:speech_to_text/speech_to_text.dart' as stt;

import '../config.dart';

/// Manages Speech-to-Text (STT) and Microsoft Edge Neural Text-to-Speech
/// (TTS) across 9 Indian languages. Voice selection: explicit language →
/// script auto-detection on the backend → Indian English default.
class VoiceService {
  VoiceService._();
  static final VoiceService instance = VoiceService._();

  /// Currently preferred BCP-47 language for TTS (e.g. 'ta-IN').
  String language = 'en-IN';

  final stt.SpeechToText _speech = stt.SpeechToText();
  final AudioPlayer _audioPlayer = AudioPlayer();

  bool _speechInitialized = false;
  bool _isListening = false;
  bool _isPlaying = false;

  bool get isListening => _isListening;
  bool get isPlaying => _isPlaying;

  /// Initialize AudioPlayer listeners
  Future<void> init() async {
    try {
      _audioPlayer.onPlayerStateChanged.listen((state) {
        _isPlaying = (state == PlayerState.playing);
      });
    } catch (e) {
      debugPrint('VoiceService init error: $e');
    }
  }

  /// Check whether text has Devanagari Hindi characters
  bool isHindiText(String text) {
    final hindiRegex = RegExp(r'[\u0900-\u097F]');
    return hindiRegex.hasMatch(text);
  }

  /// Select the TTS language: explicit override, current preference, or
  /// script auto-detection (backend handles detection when none is passed).
  String _resolveLanguage(String text, String? languageOverride) {
    if (languageOverride != null) return languageOverride;
    return language;
  }

  /// Synthesize and speak using Microsoft Edge Neural TTS via backend API.
  Future<void> speak(String text, {String? voice, String? languageOverride}) async {
    if (text.trim().isEmpty) return;

    try {
      await stopSpeaking();

      final selectedLanguage = _resolveLanguage(text, languageOverride);
      final selectedVoice = voice ?? (
        selectedLanguage == 'hi-IN' && isHindiText(text)
            ? 'hi-IN-SwaraNeural'
            : null
      );

      final url = Uri.parse('${AppConfig.apiBaseUrl}/chat/tts');
      final response = await http.post(
        url,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'text': text,
          if (selectedVoice != null) 'voice': selectedVoice,
          'language': selectedLanguage,
        }),
      );

      if (response.statusCode == 200 && response.bodyBytes.isNotEmpty) {
        _isPlaying = true;
        await _audioPlayer.play(BytesSource(response.bodyBytes));
      } else {
        debugPrint('Edge TTS request failed: ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('VoiceService speak error: $e');
      _isPlaying = false;
    }
  }

  /// Stop any ongoing speech
  Future<void> stopSpeaking() async {
    try {
      await _audioPlayer.stop();
      _isPlaying = false;
    } catch (_) {}
  }

  /// Start listening for microphone input
  Future<bool> startListening({
    required Function(String recognizedWords) onResult,
    required Function(bool isListening) onStatusChanged,
    String? preferredLocaleId,
    Function(String finalWords)? onFinalResult,
  }) async {
    try {
      if (!_speechInitialized) {
        _speechInitialized = await _speech.initialize(
          onStatus: (status) {
            _isListening = status == 'listening';
            onStatusChanged(_isListening);
          },
          onError: (error) {
            debugPrint('STT error: $error');
            _isListening = false;
            onStatusChanged(false);
          },
        );
      }

      if (!_speechInitialized) {
        return false;
      }

      await stopSpeaking();

      String localeId = preferredLocaleId ?? 'en_IN';
      try {
        final locales = await _speech.locales();
        final hasTarget = locales.any((l) => l.localeId.toLowerCase().replaceAll('-', '_') == localeId.toLowerCase());
        if (!hasTarget) {
          final fallback = locales.firstWhere(
            (l) => l.localeId.toLowerCase().contains('in') || l.localeId.toLowerCase().contains('hi'),
            orElse: () => locales.first,
          );
          localeId = fallback.localeId;
        }
      } catch (_) {}

      _isListening = true;
      onStatusChanged(true);

      await _speech.listen(
        onResult: (result) {
          if (result.recognizedWords.isNotEmpty) {
            onResult(result.recognizedWords);
          }
          // Call final result callback and auto-stop when speech is complete
          if (result.finalResult) {
            if (onFinalResult != null && result.recognizedWords.isNotEmpty) {
              onFinalResult(result.recognizedWords);
            }
            _speech.stop().then((_) {
              _isListening = false;
              onStatusChanged(false);
            });
          }
        },
        listenOptions: stt.SpeechListenOptions(
          localeId: localeId,
          listenMode: stt.ListenMode.dictation,
          cancelOnError: true,
          partialResults: true,
        ),
      );

      // Also set a timeout to stop listening after 10 seconds of silence
      // ignore: unawaited_futures
      Future.delayed(const Duration(seconds: 10), () {
        if (_isListening) {
          _speech.stop().then((_) {
            _isListening = false;
            onStatusChanged(false);
          });
        }
      });

      return true;
    } catch (e) {
      debugPrint('startListening error: $e');
      _isListening = false;
      onStatusChanged(false);
      return false;
    }
  }

  /// Stop listening
  Future<void> stopListening() async {
    try {
      await _speech.stop();
      _isListening = false;
    } catch (_) {}
  }
}
