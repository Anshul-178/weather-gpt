// Chat models.

class ChatMessage {
  final String text;
  final bool isUser;
  final DateTime time;
  final bool isError;

  const ChatMessage({
    required this.text,
    required this.isUser,
    required this.time,
    this.isError = false,
  });
}
