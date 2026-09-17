import 'dart:async';
import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
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
  /// Automatic by default. A manual value can still be assigned as an override.
  String language = 'auto';

  final stt.SpeechToText _speech = stt.SpeechToText();
  final AudioPlayer _audioPlayer = AudioPlayer();

  bool _speechInitialized = false;
  bool _isListening = false;
  bool _isPlaying = false;

  /// Guard against overlapping listen sessions (spec §15).
  Completer<void>? _listenSession;

  bool get isListening => _isListening;
  bool get isPlaying => _isPlaying;

  /// Detailed failure reason for the last startListening call, so the UI can
  /// show the right message (permission vs unavailable vs generic).
  VoiceFailure? lastFailure;

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

  /// Select TTS language from the user's text unless a manual override exists.
  String _resolveLanguage(String text, String? languageOverride) {
    if (languageOverride != null && languageOverride != 'auto') {
      return languageOverride;
    }
    if (language != 'auto') return language;
    if (RegExp(r'[\u0900-\u097F]').hasMatch(text)) return 'hi-IN';
    if (RegExp(r'[\u0980-\u09FF]').hasMatch(text)) return 'bn-IN';
    if (RegExp(r'[\u0B80-\u0BFF]').hasMatch(text)) return 'ta-IN';
    if (RegExp(r'[\u0C00-\u0C7F]').hasMatch(text)) return 'te-IN';
    if (RegExp(r'[\u0C80-\u0CFF]').hasMatch(text)) return 'kn-IN';
    if (RegExp(r'[\u0D00-\u0D7F]').hasMatch(text)) return 'ml-IN';
    if (RegExp(r'[\u0A00-\u0A7F]').hasMatch(text)) return 'pa-IN';
    if (RegExp(r'[\u0A80-\u0AFF]').hasMatch(text)) return 'gu-IN';
    return 'en-IN';
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

  /// Pre-flight microphone permission check.
  ///
  /// The speech_to_text plugin requests RECORD_AUDIO itself during
  /// [stt.SpeechToText.initialize], but only when an Activity is available;
  /// a permanent denial is reported as init failure. Probing first lets us
  /// tell the user *why* voice input is unavailable (spec §15).
  Future<bool> _ensureMicPermission() async {
    try {
      const channel = MethodChannel('weathergpt/voice');
      final granted = await channel.invokeMethod('checkMicPermission');
      return granted == true;
    } on MissingPluginException {
      // Non-Android platforms (e.g. Windows debug): fall back to the
      // plugin's own permission probe.
      try {
        return await _speech.hasPermission;
      } catch (_) {
        return true; // let initialize() decide
      }
    } on PlatformException {
      return true; // let initialize() decide
    }
  }

  /// Start listening for microphone input.
  ///
  /// Returns true when a listening session actually started.
  Future<bool> startListening({
    required Function(String recognizedWords) onResult,
    required Function(bool isListening) onStatusChanged,
    String? preferredLocaleId,
    Function(String finalWords)? onFinalResult,
  }) async {
    // Prevent multiple simultaneous listening sessions (spec §15).
    if (_listenSession != null && !_listenSession!.isCompleted) {
      debugPrint('startListening: session already active, ignoring');
      return false;
    }

    lastFailure = null;

    // 1. Microphone permission (spec §14).
    final hasPermission = await _ensureMicPermission();
    if (!hasPermission) {
      lastFailure = VoiceFailure.permissionDenied;
      debugPrint('startListening: RECORD_AUDIO permission denied');
      return false;
    }

    try {
      // 2. Initialize the recognizer (also requests permission on Android).
      if (!_speechInitialized || !_speech.isAvailable) {
        _speechInitialized = await _speech.initialize(
          debugLogging: kDebugMode,
          onStatus: (status) {
            debugPrint('STT status: $status');
            final listening = status == 'listening' || status == 'started';
            // 'done'/'notListening' close the session.
            if (status == 'done' || status == 'notListening') {
              _endSession(notify: onStatusChanged);
            } else if (listening != _isListening) {
              _isListening = listening;
              onStatusChanged(listening);
            }
          },
          onError: (error) {
            debugPrint('STT error: ${error.errorMsg} (permanent: ${error.permanent})');
            _endSession(notify: onStatusChanged);
          },
        );
        if (!_speechInitialized) {
          lastFailure = VoiceFailure.unavailable;
          return false;
        }
      }

      // 3. Stop any TTS playback so the mic doesn't hear the app itself.
      await stopSpeaking();

      // 4. Pick a supported recognition locale (spec §17): use the
      // requested locale when the device supports it; otherwise fall back
      // to an Indian/English locale. The recognizer does NOT detect the
      // spoken language automatically — the locale selects it.
      final localeId = await _resolveLocale(preferredLocaleId);

      final completer = Completer<void>();
      _listenSession = completer;

      _isListening = true;
      onStatusChanged(true);

      await _speech.listen(
        onResult: (result) {
          if (result.recognizedWords.isNotEmpty) {
            onResult(result.recognizedWords);
          }
          if (result.finalResult) {
            final words = result.recognizedWords.trim();
            if (words.isNotEmpty && onFinalResult != null) {
              onFinalResult(words);
            }
            _endSession(notify: onStatusChanged);
          }
        },
        listenOptions: stt.SpeechListenOptions(
          localeId: localeId,
          listenMode: stt.ListenMode.dictation,
          cancelOnError: true,
          partialResults: true,
          // Platform-safe limits: stop after 15s total, or 5s of silence.
          listenFor: const Duration(seconds: 15),
          pauseFor: const Duration(seconds: 5),
        ),
      );

      // Safety net: platform may not honour listenFor on every device.
      Timer(const Duration(seconds: 18), () {
        if (_listenSession == completer && !completer.isCompleted) {
          debugPrint('STT safety timeout elapsed, stopping session');
          _endSession(notify: onStatusChanged);
        }
      });

      return true;
    } catch (e) {
      debugPrint('startListening error: $e');
      lastFailure = VoiceFailure.unavailable;
      _endSession(notify: onStatusChanged);
      return false;
    }
  }

  /// Stop listening and finalize the session.
  Future<void> stopListening() async {
    await _endSession();
  }

  Future<void> _endSession({Function(bool)? notify}) async {
    _isListening = false;
    final session = _listenSession;
    if (session != null && !session.isCompleted) {
      session.complete();
    }
    _listenSession = null;
    try {
      await _speech.stop();
    } catch (_) {}
    try {
      notify?.call(false);
    } catch (_) {}
  }

  /// Resolve a locale supported by the device recognizer (spec §17).
  Future<String> _resolveLocale(String? preferred) async {
    String normalized(String id) => id.toLowerCase().replaceAll('-', '_');
    final wanted = normalized(preferred ?? 'en_IN');

    try {
      final locales = await _speech.locales();
      if (locales.isEmpty) return wanted;

      // Exact match first (e.g. 'hi_IN').
      for (final l in locales) {
        if (normalized(l.localeId) == wanted) return l.localeId;
      }
      // Same language, any region (e.g. 'hi-IN' when 'hi_IN' is missing).
      final lang = wanted.split('_').first;
      for (final l in locales) {
        if (normalized(l.localeId).split('_').first == lang) return l.localeId;
      }
      // Any Indian locale → English (India) → device default.
      for (final l in locales) {
        final n = normalized(l.localeId);
        if (n.endsWith('_in') || n.startsWith('en_in')) return l.localeId;
      }
      return locales.first.localeId;
    } catch (e) {
      debugPrint('locale lookup failed: $e');
      return wanted;
    }
  }
}

/// Why the last voice-input attempt failed; drives the UI message (spec §15).
enum VoiceFailure {
  permissionDenied,
  unavailable,
}

extension VoiceFailureMessage on VoiceFailure? {
  String get userMessage {
    switch (this) {
      case VoiceFailure.permissionDenied:
        return 'Microphone permission is required for voice input.';
      case VoiceFailure.unavailable:
        return 'Speech recognition is not available on this device.';
      default:
        return "Couldn't hear that. Please try again.";
    }
  }
}
