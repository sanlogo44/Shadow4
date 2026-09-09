import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import '../widgets/chat_sidebar.dart';
import '../widgets/model_selector.dart';
import 'settings_screen.dart';
import 'admin_dashboard_screen.dart';

/// Haupt-Chat-Oberfläche: Sidebar + Nachrichtenverlauf + Eingabe.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _inputCtrl = TextEditingController();
  final _scrollCtrl = ScrollController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final state = context.read<AppState>();
      state.refreshSessions();
      state.refreshModels();
    });
  }

  @override
  void dispose() {
    _inputCtrl.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 150),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _send() async {
    final text = _inputCtrl.text.trim();
    if (text.isEmpty) return;
    _inputCtrl.clear();
    await context.read<AppState>().sendMessage(text);
    _scrollToBottom();
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final isWide = MediaQuery.sizeOf(context).width > 900;

    return Scaffold(
      appBar: AppBar(
        title: Text(state.activeSession?.title ?? 'Shadow'),
        actions: [
          // Chat-Menü: Schwarm-Modus, Ziel-Agent, Prompt-Verfeinerer (Stubs)
          PopupMenuButton<String>(
            icon: const Icon(Icons.hub),
            tooltip: 'Chat-Menü',
            onSelected: (v) => _showFeatureStub(context, v),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'swarm', child: Text('Schwarm-Modus')),
              PopupMenuItem(value: 'target-agent', child: Text('Ziel-Agent')),
              PopupMenuItem(value: 'prompt-refiner', child: Text('Prompt-Verfeinerer')),
            ],
          ),
          // Einstellungen (Zahnrad)
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: 'Einstellungen',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
          // Admin-Dashboard (nur Admin)
          if (state.isAdmin)
            IconButton(
              icon: const Icon(Icons.admin_panel_settings),
              tooltip: 'Admin-Dashboard',
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const AdminDashboardScreen()),
              ),
            ),
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Abmelden',
            onPressed: () => context.read<AppState>().logout(),
          ),
        ],
      ),
      body: Row(
        children: [
          // Linke Seitenleiste (Chats)
          if (isWide)
            SizedBox(width: 280, child: ChatSidebar(onOpen: _scrollToBottom)),
          // Nachrichtenverlauf
          Expanded(
            child: state.activeSessionId == null
                ? _EmptyChat(onNew: () async {
                    await state.createSession();
                    _scrollToBottom();
                  })
                : Column(
                    children: [
                      Expanded(
                        child: ListView.builder(
                          controller: _scrollCtrl,
                          padding: const EdgeInsets.all(16),
                          itemCount: state.activeMessages.length,
                          itemBuilder: (_, i) {
                            final msg = state.activeMessages[i];
                            return _MessageBubble(message: msg);
                          },
                        ),
                      ),
                      if (state.sending)
                        const Padding(
                          padding: EdgeInsets.only(bottom: 8),
                          child: LinearProgressIndicator(),
                        ),
                      _MessageInput(
                        controller: _inputCtrl,
                        onSend: _send,
                        enabled: !state.sending,
                      ),
                    ],
                  ),
          ),
        ],
      ),
      // Modell-Auswahl unten rechts
      floatingActionButton: Align(
        alignment: Alignment.bottomRight,
        child: Padding(
          padding: const EdgeInsets.only(bottom: 80, right: 8),
          child: ModelSelector(),
        ),
      ),
      drawer: isWide
          ? null
          : Drawer(child: ChatSidebar(onOpen: () => Navigator.of(context).pop())),
    );
  }

  void _showFeatureStub(BuildContext context, String feature) {
    final names = {
      'swarm': 'Schwarm-Modus',
      'target-agent': 'Ziel-Agent',
      'prompt-refiner': 'Prompt-Verfeinerer',
    };
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(names[feature] ?? feature),
        content: const Text(
            'Bereit für zukünftige Integration. Diese Funktion ist als '
            'Schnittstelle vorbereitet und wird in einer späteren Version '
            'mit der Shadow LLM Engine verbunden.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Verstanden'),
          ),
        ],
      ),
    );
  }
}

class _EmptyChat extends StatelessWidget {
  final VoidCallback onNew;
  const _EmptyChat({required this.onNew});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.chat_bubble_outline, size: 64, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Text('Kein Chat ausgewählt', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          FilledButton.icon(
            onPressed: onNew,
            icon: const Icon(Icons.add),
            label: const Text('Neuer Chat'),
          ),
        ],
      ),
    );
  }
}

class _MessageInput extends StatelessWidget {
  final TextEditingController controller;
  final VoidCallback onSend;
  final bool enabled;

  const _MessageInput({
    required this.controller,
    required this.onSend,
    required this.enabled,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: controller,
              enabled: enabled,
              minLines: 1,
              maxLines: 6,
              decoration: const InputDecoration(
                hintText: 'Nachricht schreiben… (Markdown unterstützt)',
                prefixIcon: Icon(Icons.attach_file),
              ),
              onSubmitted: (_) => onSend(),
            ),
          ),
          const SizedBox(width: 8),
          FilledButton(
            onPressed: enabled ? onSend : null,
            child: const Icon(Icons.send),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final ChatMessage message;
  const _MessageBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUser = message.isUser;
    final align = isUser ? Alignment.centerRight : Alignment.centerLeft;
    final bg = isUser
        ? theme.colorScheme.primary.withValues(alpha: 0.15)
        : theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5);

    return Align(
      alignment: align,
      child: Container(
        constraints: BoxConstraints(maxWidth: MediaQuery.sizeOf(context).width * 0.7),
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(14),
            topRight: const Radius.circular(14),
            bottomLeft: Radius.circular(isUser ? 14 : 4),
            bottomRight: Radius.circular(isUser ? 4 : 14),
          ),
        ),
        child: MarkdownBody(
          data: message.content,
          selectable: true,
        ),
      ),
    );
  }
}
