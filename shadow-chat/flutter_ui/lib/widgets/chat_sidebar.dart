import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../state/app_state.dart';

/// Linke Seitenleiste: Liste aller Chats mit einklappen, löschen,
/// umbenennen und zusammenführen.
class ChatSidebar extends StatelessWidget {
  final VoidCallback onOpen;
  const ChatSidebar({super.key, required this.onOpen});

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final theme = Theme.of(context);
    final activeId = state.activeSessionId;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: () async {
                    await state.createSession();
                    onOpen();
                  },
                  icon: const Icon(Icons.add),
                  label: const Text('Neuer Chat'),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: state.sessions.isEmpty
              ? const Center(child: Text('Noch keine Chats.'))
              : ListView.builder(
                  itemCount: state.sessions.length,
                  itemBuilder: (_, i) {
                    final s = state.sessions[i];
                    final active = s.id == activeId;
                    return ListTile(
                      selected: active,
                      selectedTileColor: theme.colorScheme.primary.withValues(alpha: 0.12),
                      leading: const Icon(Icons.chat_bubble_outline),
                      title: Text(s.title, overflow: TextOverflow.ellipsis),
                      subtitle: Text(_modelLabel(s.modelId), style: const TextStyle(fontSize: 12)),
                      onTap: () async {
                        await state.selectSession(s.id);
                        onOpen();
                      },
                      trailing: PopupMenuButton<String>(
                        icon: const Icon(Icons.more_vert),
                        onSelected: (v) => _action(context, v, s),
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 'rename', child: Text('Umbenennen')),
                          PopupMenuItem(value: 'merge', child: Text('Zusammenführen')),
                          PopupMenuItem(value: 'delete', child: Text('Löschen')),
                        ],
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  String _modelLabel(String id) => id;

  void _action(BuildContext context, String action, ChatSession s) {
    switch (action) {
      case 'rename':
        _rename(context, s);
        break;
      case 'merge':
        _merge(context, s);
        break;
      case 'delete':
        _delete(context, s);
        break;
    }
  }

  void _rename(BuildContext context, ChatSession s) {
    final ctrl = TextEditingController(text: s.title);
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Chat umbenennen'),
        content: TextField(controller: ctrl, autofocus: true),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Abbrechen')),
          TextButton(
            onPressed: () async {
              await context.read<AppState>().renameSession(s.id, ctrl.text.trim());
              if (context.mounted) Navigator.pop(context);
            },
            child: const Text('Speichern'),
          ),
        ],
      ),
    );
  }

  void _delete(BuildContext context, ChatSession s) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Chat löschen?'),
        content: Text('„${s.title}" wird endgültig gelöscht.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Abbrechen')),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            onPressed: () async {
              await context.read<AppState>().deleteSession(s.id);
              if (context.mounted) Navigator.pop(context);
            },
            child: const Text('Löschen'),
          ),
        ],
      ),
    );
  }

  void _merge(BuildContext context, ChatSession s) {
    final state = context.read<AppState>();
    final others = state.sessions.where((x) => x.id != s.id).toList();
    if (others.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Kein weiterer Chat zum Zusammenführen vorhanden.')),
      );
      return;
    }
    String? selectedId = others.first.id;
    final titleCtrl = TextEditingController(text: 'Zusammengeführt: ${s.title}');
    showDialog<void>(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Chats zusammenführen'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('Quelle 1:'),
              Text(s.title, style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 12),
              const Text('Zusammenführen mit:'),
              DropdownButton<String>(
                value: selectedId,
                items: others
                    .map((o) => DropdownMenuItem(value: o.id, child: Text(o.title)))
                    .toList(),
                onChanged: (v) => set(() => selectedId = v),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: titleCtrl,
                decoration: const InputDecoration(labelText: 'Neuer Titel'),
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Abbrechen')),
            TextButton(
              onPressed: () async {
                if (selectedId == null) return;
                await state.mergeSessions(s.id, selectedId!, titleCtrl.text.trim());
                if (ctx.mounted) Navigator.pop(ctx);
              },
              child: const Text('Zusammenführen'),
            ),
          ],
        ),
      ),
    );
  }
}
