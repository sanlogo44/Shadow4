import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../state/app_state.dart';

/// Admin-Dashboard: Benutzerübersicht, Modellübersicht, Systemstatus,
/// Benchmark, Node-Verwaltung, Trainingsstatus, API-Verbindung.
class AdminDashboardScreen extends StatefulWidget {
  const AdminDashboardScreen({super.key});

  @override
  State<AdminDashboardScreen> createState() => _AdminDashboardScreenState();
}

class _AdminDashboardScreenState extends State<AdminDashboardScreen> {
  SystemStatus? _system;
  List<ShadowUser> _users = [];
  List<ModelEntry> _allModels = [];
  List<AuditEvent> _audit = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait([
        ApiClient.systemStatus(),
        ApiClient.listUsers(),
        ApiClient.listAllModels(),
        ApiClient.auditLog(limit: 50),
      ]);
      _system = results[0] as SystemStatus;
      _users = results[1] as List<ShadowUser>;
      _allModels = results[2] as List<ModelEntry>;
      _audit = results[3] as List<AuditEvent>;
    } catch (e) {
      _error = e.toString();
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final theme = Theme.of(context);
    if (_loading) {
      return Scaffold(
        appBar: AppBar(title: const Text('Admin-Dashboard')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }
    if (_error != null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Admin-Dashboard')),
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Fehler: $_error', style: TextStyle(color: theme.colorScheme.error)),
              const SizedBox(height: 12),
              FilledButton(onPressed: _load, child: const Text('Erneut laden')),
            ],
          ),
        ),
      );
    }
    final sys = _system!;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Admin-Dashboard'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _load, tooltip: 'Aktualisieren'),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Systemstatus-Karten
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              _StatusCard(label: 'Version', value: sys.version, icon: Icons.info),
              _StatusCard(label: 'Engine', value: sys.engine, icon: Icons.memory),
              _StatusCard(label: 'Engine-Status', value: sys.engineStatus, icon: Icons.health_and_safety),
              _StatusCard(label: 'Benutzer', value: '${sys.userCount}', icon: Icons.people),
              _StatusCard(label: 'Modelle', value: '${sys.modelCount}', icon: Icons.smart_toy),
              _StatusCard(label: 'Keystore', value: sys.keystoreInitialized ? 'initialisiert' : 'nicht init.', icon: Icons.key),
            ],
          ),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  const Icon(Icons.folder, size: 20),
                  const SizedBox(width: 8),
                  Expanded(child: Text('Datenverzeichnis: ${sys.dataDir}')),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),

          // Benutzerübersicht
          _SectionTitle(title: 'Benutzerübersicht', icon: Icons.people),
          Card(
            child: DataTable(
              columns: const [
                DataColumn(label: Text('Name')),
                DataColumn(label: Text('Rolle')),
                DataColumn(label: Text('E-Mail')),
                DataColumn(label: Text('Ablauf')),
                DataColumn(label: Text('Aktionen')),
              ],
              rows: _users
                  .map((u) => DataRow(cells: [
                        DataCell(Text(u.name)),
                        DataCell(_roleChip(u.role)),
                        DataCell(Text(u.email ?? '—')),
                        DataCell(Text(u.expiresAt != null
                            ? DateTime.fromMillisecondsSinceEpoch(u.expiresAt! * 1000).toLocal().toString().substring(0, 16)
                            : '—')),
                        DataCell(_userActions(context, u)),
                      ]))
                  .toList(),
            ),
          ),
          const SizedBox(height: 8),
          FilledButton.tonalIcon(
            onPressed: () => _showCreateUserDialog(context),
            icon: const Icon(Icons.person_add),
            label: const Text('Neuer Benutzer'),
          ),
          const SizedBox(height: 24),

          // Modellübersicht
          _SectionTitle(title: 'Modellübersicht', icon: Icons.smart_toy),
          Card(
            child: _allModels.isEmpty
                ? const ListTile(title: Text('Keine Modelle.'))
                : Column(
                    children: _allModels
                        .map((m) => ListTile(
                              leading: Icon(m.enabled ? Icons.check_circle : Icons.block,
                                  color: m.enabled ? state.highlight : null),
                              title: Text(m.displayName),
                              subtitle: Text('${m.modelId} · ${m.adapterType} · ${m.contextWindow} ctx'),
                              trailing: Switch(
                                value: m.enabled,
                                onChanged: (v) async {
                                  try {
                                    await ApiClient.toggleModel(m.modelId, v);
                                    setState(() => _allModels = _allModels
                                        .map((x) => x.modelId == m.modelId
                                            ? ModelEntry(
                                                modelId: x.modelId,
                                                displayName: x.displayName,
                                                adapterType: x.adapterType,
                                                enabled: v,
                                                contextWindow: x.contextWindow)
                                            : x)
                                        .toList());
                                  } catch (e) {
                                    if (context.mounted) {
                                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
                                    }
                                  }
                                },
                              ),
                            ))
                        .toList(),
                  ),
          ),
          const SizedBox(height: 24),

          // Benchmark
          _SectionTitle(title: 'Benchmark', icon: Icons.speed),
          _BenchmarkSection(),
          const SizedBox(height: 24),

          // Node-Verwaltung + Training (Stubs)
          _SectionTitle(title: 'Node-Verwaltung & Training', icon: Icons.dns),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.dns),
                  title: const Text('Nodes'),
                  subtitle: const Text('Verteilte Verarbeitung (Schnittstelle vorbereitet).'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _showStubDialog(context, 'Node-Verwaltung'),
                ),
                ListTile(
                  leading: const Icon(Icons.model_training),
                  title: const Text('Trainingsstatus'),
                  subtitle: const Text('Wird durch die Shadow LLM Engine gesteuert.'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _showStubDialog(context, 'Trainingsstatus'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),

          // API-Verbindung / Audit
          _SectionTitle(title: 'API-Verbindung & Audit', icon: Icons.cloud),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: const Icon(Icons.api),
                  title: const Text('Server-URL'),
                  subtitle: Text(state.baseUrl),
                ),
                const Divider(),
                ListTile(
                  leading: const Icon(Icons.history),
                  title: const Text('Audit-Log (letzte 50)'),
                ),
                for (final e in _audit.take(20))
                  ListTile(
                    dense: true,
                    leading: const Icon(Icons.circle, size: 8),
                    title: Text('${e.action} · ${e.actor}', style: const TextStyle(fontSize: 13)),
                    subtitle: Text(
                      DateTime.fromMillisecondsSinceEpoch(e.timestamp * 1000).toLocal().toString().substring(0, 19),
                      style: const TextStyle(fontSize: 11),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Widget _userActions(BuildContext context, ShadowUser u) {
    return PopupMenuButton<String>(
      icon: const Icon(Icons.more_vert),
      onSelected: (v) {
        switch (v) {
          case 'password':
            _showPasswordDialog(context, u);
            break;
          case 'delete':
            _showDeleteUserDialog(context, u);
            break;
        }
      },
      itemBuilder: (_) => [
        const PopupMenuItem(value: 'password', child: Text('Passwort zurücksetzen')),
        const PopupMenuItem(
          value: 'delete',
          child: Text('Löschen'),
        ),
      ],
    );
  }

  void _showPasswordDialog(BuildContext context, ShadowUser u) {
    final ctrl = TextEditingController();
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('Passwort für „${u.name}" zurücksetzen'),
        content: TextField(
          controller: ctrl,
          obscureText: true,
          decoration: const InputDecoration(labelText: 'Neues Passwort'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Abbrechen')),
          FilledButton(
            onPressed: () async {
              if (ctrl.text.length < 4) return;
              try {
                await ApiClient.setUserPassword(u.id, ctrl.text);
                if (context.mounted) {
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Passwort zurückgesetzt.')));
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Fehler: $e')));
                }
              }
            },
            child: const Text('Zurücksetzen'),
          ),
        ],
      ),
    );
  }

  void _showDeleteUserDialog(BuildContext context, ShadowUser u) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text('„${u.name}" löschen?'),
        content: Text('Der Benutzer wird endgültig entfernt. Der letzte Admin kann nicht gelöscht werden.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Abbrechen')),
          TextButton(
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            onPressed: () async {
              try {
                await ApiClient.deleteUser(u.id);
                if (context.mounted) Navigator.pop(context);
                _load();
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Fehler: $e')));
                }
              }
            },
            child: const Text('Löschen'),
          ),
        ],
      ),
    );
  }

  Widget _roleChip(String role) {
    final color = switch (role) {
      'admin' => Colors.red,
      'test' => Colors.orange,
      _ => Colors.blue,
    };
    return Chip(
      label: Text(role),
      backgroundColor: color.withValues(alpha: 0.15),
      labelStyle: TextStyle(color: color, fontSize: 12),
      padding: EdgeInsets.zero,
      visualDensity: VisualDensity.compact,
    );
  }

  void _showCreateUserDialog(BuildContext context) {
    final userCtrl = TextEditingController();
    final passCtrl = TextEditingController();
    final emailCtrl = TextEditingController();
    String role = 'user';
    final expCtrl = TextEditingController();
    final formKey = GlobalKey<FormState>();
    showDialog<void>(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: const Text('Neuer Benutzer'),
          content: Form(
            key: formKey,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextFormField(controller: userCtrl, decoration: const InputDecoration(labelText: 'Benutzername'),
                    validator: (v) => (v == null || v.trim().isEmpty) ? 'Pflichtfeld' : null),
                  TextFormField(controller: passCtrl, decoration: const InputDecoration(labelText: 'Passwort'), obscureText: true,
                    validator: (v) => (v == null || v.length < 4) ? 'Min. 4 Zeichen' : null),
                  TextFormField(controller: emailCtrl, decoration: const InputDecoration(labelText: 'E-Mail (optional)')),
                  DropdownButtonFormField<String>(
                    initialValue: role,
                    decoration: const InputDecoration(labelText: 'Rolle'),
                    items: const [
                      DropdownMenuItem(value: 'user', child: Text('User')),
                      DropdownMenuItem(value: 'admin', child: Text('Admin')),
                      DropdownMenuItem(value: 'test', child: Text('Test User')),
                    ],
                    onChanged: (v) => set(() => role = v ?? 'user'),
                  ),
                  if (role == 'test')
                    TextFormField(
                      controller: expCtrl,
                      decoration: const InputDecoration(labelText: 'Ablauf in Tagen', hintText: 'z. B. 7'),
                      keyboardType: TextInputType.number,
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Abbrechen')),
            FilledButton(
              onPressed: () async {
                if (!formKey.currentState!.validate()) return;
                int? expiresAt;
                if (role == 'test') {
                  final days = int.tryParse(expCtrl.text.trim());
                  if (days != null) {
                    expiresAt = DateTime.now().millisecondsSinceEpoch ~/ 1000 + days * 86400;
                  }
                }
                try {
                  await ApiClient.createUser(
                    username: userCtrl.text.trim(),
                    password: passCtrl.text,
                    role: role,
                    email: emailCtrl.text.trim().isEmpty ? null : emailCtrl.text.trim(),
                    expiresAt: expiresAt,
                  );
                  if (ctx.mounted) Navigator.pop(ctx);
                  _load();
                } catch (e) {
                  if (ctx.mounted) {
                    ScaffoldMessenger.of(ctx).showSnackBar(SnackBar(content: Text('$e')));
                  }
                }
              },
              child: const Text('Anlegen'),
            ),
          ],
        ),
      ),
    );
  }

  void _showStubDialog(BuildContext context, String title) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(title),
        content: const Text('Schnittstelle ist vorbereitet und wird in einer späteren Version mit der Shadow LLM Engine verbunden.'),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  final String title;
  final IconData icon;
  const _SectionTitle({required this.title, required this.icon});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Icon(icon, size: 20, color: theme.colorScheme.primary),
          const SizedBox(width: 8),
          Text(title, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}

class _StatusCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  const _StatusCard({required this.label, required this.value, required this.icon});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 160,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 20, color: Theme.of(context).colorScheme.primary),
          const SizedBox(height: 6),
          Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
          Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
        ],
      ),
    );
  }
}

class _BenchmarkSection extends StatefulWidget {
  const _BenchmarkSection();

  @override
  State<_BenchmarkSection> createState() => _BenchmarkSectionState();
}

class _BenchmarkSectionState extends State<_BenchmarkSection> {
  final _runsCtrl = TextEditingController(text: '3');
  Map<String, dynamic>? _result;
  bool _running = false;

  @override
  void dispose() {
    _runsCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                SizedBox(width: 120, child: TextField(controller: _runsCtrl, decoration: const InputDecoration(labelText: 'Runs'), keyboardType: TextInputType.number)),
                const SizedBox(width: 12),
                FilledButton(
                  onPressed: _running ? null : _run,
                  child: _running
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Benchmark starten'),
                ),
              ],
            ),
            if (_result != null) ...[
              const SizedBox(height: 12),
              Text('Modell: ${_result!['model_id']} · Runs: ${_result!['runs']}',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              Text('Ø Latenz: ${_result!['avg_latency_ms']} ms · ${_result!['tokens_per_sec']} tok/s'),
              Text('Tokens: ${_result!['total_tokens']} (Prompt: ${_result!['prompt_tokens']})'),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _run() async {
    final runs = int.tryParse(_runsCtrl.text.trim()) ?? 3;
    setState(() => _running = true);
    try {
      final state = context.read<AppState>();
      final modelId = state.selectedModelId ?? 'shadow-default';
      _result = await ApiClient.runBenchmark(modelId, runs);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Benchmark fehlgeschlagen: $e')));
      }
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }
}
