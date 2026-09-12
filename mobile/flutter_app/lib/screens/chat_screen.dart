import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/chat.dart';
import '../providers/app_state.dart';
import '../providers/chat_state.dart';
import '../services/voice_service.dart';

/// AI chat screen — opened from the floating "Ask AI" button.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final VoiceService _voiceService = VoiceService.instance;

  bool _isListening = false;
  String _selectedLocale = 'en_IN';

  // 9 Indian languages: code + display name + native greeting hint.
  static const List<(String, String)> _locales = [
    ('en_IN', 'English (IN)'),
    ('hi_IN', 'हिन्दी · Hindi'),
    ('ta_IN', 'தமிழ் · Tamil'),
    ('te_IN', 'తెలుగు · Telugu'),
    ('bn_IN', 'বাংলা · Bengali'),
    ('mr_IN', 'मराठी · Marathi'),
    ('kn_IN', 'ಕನ್ನಡ · Kannada'),
    ('ml_IN', 'മലയാളം · Malayalam'),
    ('gu_IN', 'ગુજરાતી · Gujarati'),
  ];

  @override
  void initState() {
    super.initState();
    _voiceService.init();
  }

  @override
  void dispose() {
    _voiceService.stopListening();
    _voiceService.stopSpeaking();
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _send(ChatState chat) async {
    final text = _controller.text;
    if (text.trim().isEmpty) return;
    _controller.clear();
    await chat.send(text);
    _scrollToBottom();
  }

  void _scrollToBottom() {
    if (_scrollController.hasClients) {
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 300),
        curve: Curves.easeOut,
      );
    }
  }

  bool _isSendingFromSpeech = false;

  void _toggleListening(ChatState chat) async {
    if (_isListening) {
      await _voiceService.stopListening();
      setState(() => _isListening = false);
      // Send when user manually stops recording
      if (_controller.text.trim().isNotEmpty && !_isSendingFromSpeech) {
        _send(chat);
      }
      _isSendingFromSpeech = false;
    } else {
      _isSendingFromSpeech = false;
      final success = await _voiceService.startListening(
        preferredLocaleId: _selectedLocale,
        onStatusChanged: (listening) {
          if (mounted) setState(() => _isListening = listening);
        },
        onResult: (words) {
          if (mounted) {
            setState(() {
              _controller.text = words;
              _controller.selection = TextSelection.fromPosition(
                TextPosition(offset: _controller.text.length),
              );
            });
          }
        },
        onFinalResult: (finalWords) {
          // Auto-send when speech recognition detects the user stopped speaking
          if (mounted && finalWords.trim().isNotEmpty && !_isSendingFromSpeech) {
            _isSendingFromSpeech = true;
            _send(chat);
          }
        },
      );

      if (!success && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Microphone permission or speech recognition unavailable.'),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final chat = context.watch<ChatState>();
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      resizeToAvoidBottomInset: true,
      appBar: AppBar(
        title: Row(
          children: [
            CircleAvatar(
              radius: 16,
              backgroundColor: scheme.primaryContainer,
              child: Icon(Icons.auto_awesome_rounded,
                  size: 18, color: scheme.onPrimaryContainer),
            ),
            const SizedBox(width: 10),
            const Text('WeatherGPT AI'),
          ],
        ),
        actions: [
          // Language selector — 9 Indian languages.
          PopupMenuButton<String>(
            tooltip: 'Voice Language',
            icon: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.language_rounded, size: 20, color: scheme.primary),
                const SizedBox(width: 4),
                Text(
                  _locales
                      .firstWhere((l) => l.$1 == _selectedLocale,
                          orElse: () => _locales.first)
                      .$2
                      .split('·')
                      .first
                      .trim(),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: scheme.primary,
                  ),
                ),
              ],
            ),
            initialValue: _selectedLocale,
            onSelected: (val) {
              setState(() => _selectedLocale = val);
              chat.setVoiceLanguage(val.replaceAll('_', '-'));
            },
            itemBuilder: (context) => [
              for (final (code, name) in _locales)
                PopupMenuItem(
                  value: code,
                  child: Text('🇮🇳 $name'),
                ),
            ],
          ),
          // Auto-speak toggle
          IconButton(
            tooltip: chat.autoSpeak ? 'Mute AI Voice' : 'Enable AI Voice',
            icon: Icon(
              chat.autoSpeak ? Icons.volume_up_rounded : Icons.volume_off_rounded,
              color: chat.autoSpeak ? scheme.primary : scheme.onSurfaceVariant,
            ),
            onPressed: () {
              chat.setAutoSpeak(!chat.autoSpeak);
              if (!chat.autoSpeak) {
                _voiceService.stopSpeaking();
              }
            },
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: Column(
        children: [
          if (_isListening)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
              color: scheme.errorContainer.withValues(alpha: 0.7),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.mic, color: Colors.red, size: 18),
                  const SizedBox(width: 8),
                  Text(
                    'Listening… ($_selectedLocale)',
                    style: TextStyle(
                      color: scheme.onErrorContainer,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ),
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              itemCount: chat.messages.length + (chat.sending ? 1 : 0),
              itemBuilder: (context, index) {
                if (index == chat.messages.length) {
                  return Align(
                    alignment: Alignment.centerLeft,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: List.generate(3, (i) {
                          return Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 2),
                            child: CircleAvatar(
                              radius: 4,
                              backgroundColor:
                                  scheme.primary.withValues(alpha: 0.5),
                            ),
                          );
                        }),
                      ),
                    ),
                  );
                }
                final ChatMessage message = chat.messages[index];
                return _MessageBubble(
                  message: message,
                  onSpeak: () => _voiceService.speak(message.text),
                );
              },
            ),
          ),
          if (chat.messages.length <= 1)
            SizedBox(
              height: 52,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 16),
                itemCount: ChatState.suggestedQuestions.length +
                    (context.read<AppState>().aqi != null ? 1 : 0),
                separatorBuilder: (_, __) => const SizedBox(width: 8),
                itemBuilder: (context, index) {
                  final aqi = context.read<AppState>().aqi;
                  const questions = ChatState.suggestedQuestions;
                  if (aqi != null && index == questions.length) {
                    return ActionChip(
                      avatar: const Icon(Icons.air_outlined, size: 18),
                      label: const Text('How is the air quality?'),
                      onPressed: () => chat.send('How is the air quality right now?'),
                    );
                  }
                  return ActionChip(
                    label: Text(questions[index]),
                    onPressed: () => chat.send(questions[index]),
                  );
                },
              ),
            ),
          SafeArea(
            top: false,
            left: false,
            right: false,
            bottom: true,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: scheme.surface,
                border: Border(
                  top: BorderSide(
                    color: scheme.outlineVariant.withValues(alpha: 0.3),
                    width: 1,
                  ),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  // Microphone button
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    margin: const EdgeInsets.only(right: 8),
                    decoration: BoxDecoration(
                      color: _isListening
                          ? Colors.red
                          : scheme.surfaceContainerHighest,
                      shape: BoxShape.circle,
                    ),
                    child: IconButton(
                      tooltip: _isListening ? 'Stop Recording' : 'Speak via Mic',
                      icon: Icon(
                        _isListening ? Icons.mic : Icons.mic_none_rounded,
                        color: _isListening ? Colors.white : scheme.primary,
                      ),
                      onPressed: () => _toggleListening(chat),
                    ),
                  ),
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      minLines: 1,
                      maxLines: 3,
                      textInputAction: TextInputAction.send,
                      decoration: InputDecoration(
                        isDense: true,
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 16, vertical: 10),
                        hintText: _isListening
                            ? 'Listening...'
                            : (_selectedLocale == 'hi_IN'
                                ? 'मौसम या हवा की गुणवत्ता पूछें...'
                                : 'Ask about the weather or air quality…'),
                      ),
                      onSubmitted: (_) => _send(chat),
                    ),
                  ),
                  const SizedBox(width: 8),
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    decoration: BoxDecoration(
                      color: chat.sending
                          ? scheme.surfaceContainerHighest
                          : scheme.primary,
                      shape: BoxShape.circle,
                    ),
                    child: IconButton(
                      icon: chat.sending
                          ? SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: scheme.onSurfaceVariant),
                            )
                          : const Icon(Icons.arrow_upward_rounded,
                              color: Colors.white),
                      onPressed:
                          chat.sending ? null : () => _send(chat),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final ChatMessage message;
  final VoidCallback? onSpeak;

  const _MessageBubble({
    required this.message,
    this.onSpeak,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isUser = message.isUser;
    final isError = message.isError;

    final bg = isError
        ? scheme.errorContainer
        : isUser
            ? scheme.primary
            : scheme.surfaceContainerLow;
    final fg = isError
        ? scheme.onErrorContainer
        : isUser
            ? scheme.onPrimary
            : scheme.onSurface;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 5),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.82,
        ),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18),
            topRight: const Radius.circular(18),
            bottomLeft: Radius.circular(isUser ? 18 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 18),
          ),
        ),
        child: Column(
          crossAxisAlignment:
              isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
          children: [
            Text(
              message.text,
              style: TextStyle(color: fg, height: 1.35),
            ),
            if (!isUser && !isError) ...[
              const SizedBox(height: 4),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  InkWell(
                    onTap: onSpeak,
                    borderRadius: BorderRadius.circular(12),
                    child: Padding(
                      padding: const EdgeInsets.all(4),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.volume_up_outlined,
                              size: 16, color: fg.withValues(alpha: 0.7)),
                          const SizedBox(width: 4),
                          Text(
                            'Listen',
                            style: TextStyle(
                              fontSize: 11,
                              color: fg.withValues(alpha: 0.7),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
