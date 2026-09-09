import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';

/// Login- und Setup-Bildschirm.
///
/// - Erster Start: Default-Admin (Admin/1234) → Login liefert
///   mustChangePassword=true → Setup-Formular für neuen Admin.
/// - Normaler Login: Benutzername + Passwort.
class LoginScreen extends StatefulWidget {
  final bool forceSetup;
  const LoginScreen({super.key, this.forceSetup = false});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _killCtrl = TextEditingController();
  bool _isSetup = false;
  bool _loading = false;
  String? _error;
  bool _obscure = true;

  @override
  void initState() {
    super.initState();
    _isSetup = widget.forceSetup;
  }

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    _emailCtrl.dispose();
    _killCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    final state = context.read<AppState>();
    try {
      if (_isSetup) {
        await state.setup(
          username: _userCtrl.text.trim(),
          password: _passCtrl.text,
          email: _emailCtrl.text.trim().isEmpty ? null : _emailCtrl.text.trim(),
          killSwitch: _killCtrl.text.trim().isEmpty ? null : _killCtrl.text.trim(),
        );
      } else {
        await state.login(_userCtrl.text.trim(), _passCtrl.text);
        // Nach Default-Admin-Login: muss Passwort ändern → Setup-Formular.
        if (mounted && state.mustChangePassword) {
          setState(() {
            _isSetup = true;
            _passCtrl.clear();
            _emailCtrl.clear();
            _killCtrl.clear();
          });
        }
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Logo / Titel
                  Container(
                    width: 64,
                    height: 64,
                    decoration: BoxDecoration(
                      color: theme.colorScheme.primary,
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: const Icon(Icons.bolt, size: 36, color: Colors.black),
                  ),
                  const SizedBox(height: 16),
                  Text('Shadow',
                      style: theme.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.bold)),
                  Text(
                    _isSetup ? 'Neuen Admin-Account einrichten' : 'Anmelden',
                    style: theme.textTheme.bodyMedium?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 24),
                  TextFormField(
                    controller: _userCtrl,
                    decoration: const InputDecoration(labelText: 'Benutzername'),
                    autofocus: true,
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Pflichtfeld' : null,
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: _passCtrl,
                    decoration: InputDecoration(
                      labelText: 'Passwort',
                      suffixIcon: IconButton(
                        icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility),
                        onPressed: () => setState(() => _obscure = !_obscure),
                      ),
                    ),
                    obscureText: _obscure,
                    validator: (v) => (v == null || v.length < 4)
                        ? 'Mindestens 4 Zeichen'
                        : null,
                  ),
                  if (_isSetup) ...[
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _emailCtrl,
                      decoration: const InputDecoration(labelText: 'E-Mail (optional)'),
                      keyboardType: TextInputType.emailAddress,
                    ),
                    const SizedBox(height: 12),
                    TextFormField(
                      controller: _killCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Kill-Switch-Passwort (optional)',
                        helperText: 'Notfall-Löschung bei Eingabe als Passwort.',
                      ),
                      obscureText: _obscure,
                    ),
                  ],
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _loading ? null : _submit,
                    child: _loading
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(_isSetup ? 'Einrichtung abschließen' : 'Anmelden'),
                  ),
                  const SizedBox(height: 12),
                  TextButton(
                    onPressed: () => setState(() => _isSetup = !_isSetup),
                    child: Text(_isSetup
                        ? 'Stattdessen anmelden'
                        : 'Default-Admin einrichten (Admin/1234)'),
                  ),
                  const SizedBox(height: 24),
                  // Server-Konfiguration
                  const _ServerConfigTile(),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ServerConfigTile extends StatefulWidget {
  const _ServerConfigTile();

  @override
  State<_ServerConfigTile> createState() => _ServerConfigTileState();
}

class _ServerConfigTileState extends State<_ServerConfigTile> {
  late TextEditingController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: context.read<AppState>().baseUrl);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ExpansionTile(
      title: const Text('Server-Verbindung'),
      subtitle: Text(_ctrl.text),
      childrenPadding: const EdgeInsets.only(bottom: 8),
      children: [
        TextFormField(
          controller: _ctrl,
          decoration: const InputDecoration(
            labelText: 'Base URL',
            hintText: 'http://127.0.0.1:8787',
          ),
        ),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(
            onPressed: () async {
              await context.read<AppState>().setBaseUrl(_ctrl.text.trim());
              if (!context.mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Server-URL gespeichert.')));
            },
            child: const Text('Speichern'),
          ),
        ),
      ],
    );
  }
}
