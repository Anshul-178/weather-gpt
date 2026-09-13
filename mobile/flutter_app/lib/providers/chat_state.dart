import 'package:flutter/foundation.dart';

import '../models/chat.dart';
import '../providers/app_state.dart';
import '../repositories/weather_repository.dart';
import '../services/api_service.dart';
import '../services/voice_service.dart';

/// Chat state: message list + conversation continuity.
class ChatState extends ChangeNotifier {
  final WeatherRepository _repository = WeatherRepository();
  final AppState appState;

  ChatState(this.appState);

  final List<ChatMessage> messages = [
    ChatMessage(
      text: 'Hi! Ask me anything about the weather — rain, temperature, '
          'air quality, what to wear, or whether it\'s a good day for cricket.',
      isUser: false,
      time: DateTime.now(),
    ),
  ];

  bool sending = false;
  bool autoSpeak = true;
  String voiceLanguage = 'auto'; // Detect response language from each message.

  static const List<String> suggestedQuestions = [
    'Will it rain today?',
    'What should I wear today?',
    'क्या आज बारिश होगी?',
    'Is tomorrow good for cycling?',
    'How is the air quality?',
  ];

  void setAutoSpeak(bool value) {
    autoSpeak = value;
    notifyListeners();
  }

  void setVoiceLanguage(String lang) {
    voiceLanguage = lang;
    // Keep the voice service in sync so TTS uses the same language.
    VoiceService.instance.language = lang;
    notifyListeners();
  }

  Future<void> send(String text, {bool? speakResponse}) async {
    final question = text.trim();
    if (question.isEmpty || sending) return;
    if (appState.location == null) {
      messages.add(ChatMessage(
        text: 'Please pick a location first.',
        isUser: false,
        time: DateTime.now(),
        isError: true,
      ));
      notifyListeners();
      return;
    }

    messages.add(ChatMessage(
      text: question,
      isUser: true,
      time: DateTime.now(),
    ));
    sending = true;
    notifyListeners();

    try {
      final answer = await _repository.sendChat(
        question,
        appState.location!.latitude,
        appState.location!.longitude,
        appState.conversationId,
        locationName: appState.location!.name,
      );
      appState.conversationId =
          (answer['conversation_id'] as num?)?.toInt() ?? appState.conversationId;
      final answerText = answer['answer'] as String? ?? '…';
      messages.add(ChatMessage(
        text: answerText,
        isUser: false,
        time: DateTime.now(),
      ));

      if (speakResponse ?? autoSpeak) {
        // Automatically speak using VoiceService
        await _speakAnswer(answerText);
      }
    } on ApiException catch (e) {
      messages.add(ChatMessage(
        text: e.message,
        isUser: false,
        time: DateTime.now(),
        isError: true,
      ));
    } catch (e) {
      messages.add(ChatMessage(
        text: 'Could not reach the WeatherGPT server. Please try again.\n\nDebug: $e',
        isUser: false,
        time: DateTime.now(),
        isError: true,
      ));
    }
    sending = false;
    notifyListeners();
  }

  Future<void> _speakAnswer(String text) async {
    try {
      final voice = VoiceService.instance;
      await voice.speak(text);
    } catch (_) {}
  }
}
