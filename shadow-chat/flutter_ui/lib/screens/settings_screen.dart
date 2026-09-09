import 'package:flutter/material.dart';
import 'package:flutter_colorpicker/flutter_colorpicker.dart';
import 'package:provider/provider.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../state/app_state.dart';
import '../theme/shadow_theme.dart';
import 'admin_dashboard_screen.dart';

/// Einstellungen: Sprache, Design, Modelle, Benutzer, API, Plugins, Datenschutz.
class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Einstellungen')),
      body: ListView(
        children: const [
          _DesignSection(),
          _HighlightColorSection(),
          _LanguageSection(),
          _ApiSection(),
          _ModelsSection(),
          _UsersSection(),
          _PluginsSection(),
          _PrivacySection(),
          SizedBox(height: 32),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final IconData icon;
  final List<Widget> children;
  const _Section({required this.title, required this.icon, required this.children});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
          child: Row(
            children: [
              Icon(icon, size: 18, color: theme.colorScheme.primary),
              const SizedBox(width: 8),
              Text(title, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.bold)),
            ],
          ),
        ),
        ...children,
        const Divider(),
      ],
    );
  }
}

class _DesignSection extends StatelessWidget {
  const _DesignSection();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return _Section(
      title: 'Design',
      icon: Icons.palette,
      children: [
        RadioGroup<ShadowThemeMode>(
          groupValue: state.themeMode,
          onChanged: (v) {
            if (v != null) state.setThemeMode(v);
          },
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final mode in ShadowThemeMode.values)
                RadioListTile<ShadowThemeMode>(
                  value: mode,
                  title: Text(_modeLabel(mode)),
                ),
            ],
          ),
        ),
      ],
    );
  }

  String _modeLabel(ShadowThemeMode m) => switch (m) {
        ShadowThemeMode.dark => 'Dark (#000000)',
        ShadowThemeMode.light => 'Light (#ffffff)',
        ShadowThemeMode.system => 'Systemmodus',
      };
}

class _HighlightColorSection extends StatelessWidget {
  const _HighlightColorSection();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return _Section(
      title: 'Highlight-Farbe',
      icon: Icons.colorize,
      children: [
        ListTile(
          leading: CircleAvatar(backgroundColor: state.highlight),
          title: Text(ShadowTheme.toHex(state.highlight)),
          subtitle: const Text('Standard: #16C916 — änderbar via RGB / Hex / Farbrad'),
          trailing: const Icon(Icons.edit),
          onTap: () => _pickColor(context, state.highlight, (c) => state.setHighlight(c)),
        ),
      ],
    );
  }

  void _pickColor(BuildContext context, Color current, ValueChanged<Color> onPick) {
    Color picked = current;
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Highlight-Farbe wählen'),
        content: SingleChildScrollView(
          child: ColorPicker(
            pickerColor: current,
            onColorChanged: (c) => picked = c,
            enableAlpha: false,
            labelTypes: const [ColorLabelType.rgb, ColorLabelType.hex],
            pickerAreaHeightPercent: 0.7,
            displayThumbColor: true,
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Abbrechen')),
          TextButton(
            onPressed: () {
              onPick(picked);
              Navigator.pop(context);
            },
            child: const Text('Übernehmen'),
          ),
        ],
      ),
    );
  }
}

class _LanguageSection extends StatelessWidget {
  const _LanguageSection();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return _Section(
      title: 'Sprache',
      icon: Icons.language,
      children: [
        RadioGroup<String>(
          groupValue: state.language,
          onChanged: (v) { if (v != null) state.setLanguage(v); },
          child: const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              RadioListTile<String>(
                value: 'de',
                title: Text('Deutsch'),
              ),
              RadioListTile<String>(
                value: 'en',
                title: Text('English'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ApiSection extends StatelessWidget {
  const _ApiSection();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final ctrl = TextEditingController(text: state.baseUrl);
    return _Section(
      title: 'API / Server-Verbindung',
      icon: Icons.api,
      children: [
        ListTile(
          leading: const Icon(Icons.cloud),
          title: const Text('Verbindung zum Shadow LLM Engine'),
          subtitle: const Text('Lokale API: Flutter → Rust Core → Shadow LLM Engine'),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: TextField(
            controller: ctrl,
            decoration: const InputDecoration(labelText: 'Server-URL', hintText: 'http://127.0.0.1:8787'),
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: () async {
                await state.setBaseUrl(ctrl.text.trim());
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Gespeichert.')));
                }
              },
              child: const Text('Speichern'),
            ),
          ),
        ),
      ],
    );
  }
}

class _ModelsSection extends StatelessWidget {
  const _ModelsSection();

  @override
  Widget build(BuildContext context) {
    return _Section(
      title: 'Modelle',
      icon: Icons.smart_toy,
      children: [
        ListTile(
          leading: const Icon(Icons.list),
          title: const Text('Verfügbare Modelle'),
          subtitle: const Text('Freigegebene Modelle verwalten (Admin).'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context).push(
            MaterialPageRoute(builder: (_) => const _ModelsManagementScreen()),
          ),
        ),
      ],
    );
  }
}

class _ModelsManagementScreen extends StatefulWidget {
  const _ModelsManagementScreen();

  @override
  State<_ModelsManagementScreen> createState() => _ModelsManagementScreenState();
}

class _ModelsManagementScreenState extends State<_ModelsManagementScreen> {
  List<ModelEntry> _models = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      _models = await ApiClient.listAllModels();
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Modelle')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _models.isEmpty
              ? const Center(child: Text('Keine Modelle freigegeben.'))
              : ListView.builder(
                  itemCount: _models.length,
                  itemBuilder: (_, i) {
                    final m = _models[i];
                    return SwitchListTile(
                      value: m.enabled,
                      title: Text(m.displayName),
                      subtitle: Text('${m.modelId} · ${m.adapterType}'),
                      onChanged: (v) async {
                        try {
                          await ApiClient.toggleModel(m.modelId, v);
                          await _load();
                        } catch (e) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Fehler: $e')));
                          }
                        }
                      },
                    );
                  },
                ),
    );
  }
}

class _UsersSection extends StatelessWidget {
  const _UsersSection();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    final user = state.user;
    return _Section(
      title: 'Benutzer',
      icon: Icons.people,
      children: [
        ListTile(
          leading: CircleAvatar(
            backgroundColor: state.highlight,
            child: Text(
              (user?.name.isNotEmpty ?? false) ? user!.name[0].toUpperCase() : '?',
              style: const TextStyle(color: Colors.black),
            ),
          ),
          title: Text(user?.name ?? '—'),
          subtitle: Text('Rolle: ${user?.role ?? "—"} · E-Mail: ${user?.email ?? "—"}'),
        ),
        ListTile(
          leading: const Icon(Icons.lock_reset),
          title: const Text('Eigenes Passwort ändern'),
          subtitle: const Text('Passwort-Reset über den Server (Admin kann fremde zurücksetzen).'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => _showChangePasswordDialog(context, user?.id),
        ),
        if (state.isAdmin)
          ListTile(
            leading: const Icon(Icons.admin_panel_settings),
            title: const Text('Benutzerverwaltung'),
            subtitle: const Text('Benutzer anlegen, löschen, deaktivieren, Passwörter zurücksetzen.'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AdminDashboardScreen()),
            ),
          ),
        if (state.isAdmin)
          ListTile(
            leading: const Icon(Icons.cleaning_services),
            title: const Text('Abgelaufene Test-User deaktivieren'),
            subtitle: const Text('Prüft Ablaufdaten und sperrt abgelaufene Test-Konten.'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () async {
              try {
                await ApiClient.deactivateExpiredUsers();
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Abgelaufene Test-User deaktiviert.')));
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Fehler: $e')));
                }
              }
            },
          ),
      ],
    );
  }

  void _showChangePasswordDialog(BuildContext context, String? userId) {
    if (userId == null) return;
    final ctrl = TextEditingController();
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Passwort ändern'),
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
                await ApiClient.setUserPassword(userId, ctrl.text);
                if (context.mounted) {
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Passwort geändert.')));
                }
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Fehler: $e')));
                }
              }
            },
            child: const Text('Ändern'),
          ),
        ],
      ),
    );
  }
}

class _PluginsSection extends StatelessWidget {
  const _PluginsSection();

  @override
  Widget build(BuildContext context) {
    return _Section(
      title: 'Plugins',
      icon: Icons.extension,
      children: [
        FutureBuilder<List<Map<String, dynamic>>>(
          future: ApiClient.plugins(),
          builder: (_, snap) {
            if (snap.connectionState != ConnectionState.done) {
              return const Padding(
                padding: EdgeInsets.all(16),
                child: Center(child: CircularProgressIndicator()),
              );
            }
            final items = snap.data ?? [];
            if (items.isEmpty) {
              return const ListTile(
                leading: Icon(Icons.extension),
                title: Text('Keine Plugins installiert.'),
                subtitle: Text('Plugin-Schnittstelle ist vorbereitet.'),
              );
            }
            return Column(
              children: [
                for (final p in items)
                  ListTile(
                    leading: const Icon(Icons.check_circle_outline),
                    title: Text(p['name'] as String? ?? ''),
                    subtitle: Text('Status: ${p['status'] ?? "vorbereitet"}'),
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _PrivacySection extends StatelessWidget {
  const _PrivacySection();

  @override
  Widget build(BuildContext context) {
    return _Section(
      title: 'Datenschutz',
      icon: Icons.lock,
      children: [
        ListTile(
          leading: const Icon(Icons.enhanced_encryption),
          title: const Text('Verschlüsselte Speicherung'),
          subtitle: const Text(
              'Chat-Inhalte AES-256-GCM verschlüsselt (Master-Key via Argon2id). '
              'Passwörter als Argon2id-PHC-String.'),
        ),
        ListTile(
          leading: const Icon(Icons.shield),
          title: const Text('Manipulationserkennung'),
          subtitle: const Text('SHA-256-Integritätsprüfung für Modelle und Exports.'),
        ),
        ListTile(
          leading: const Icon(Icons.delete_forever),
          title: const Text('Kill-Switch'),
          subtitle: const Text(
              'Optional beim Einrichten. Eingabe als Passwort löst sofortige Löschung '
              'aller Account-Daten aus.'),
        ),
        ListTile(
          leading: const Icon(Icons.history),
          title: const Text('Audit-Log'),
          subtitle: const Text('Sicherheitsrelevante Aktionen werden protokolliert.'),
        ),
      ],
    );
  }
}
