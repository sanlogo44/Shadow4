import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/models.dart';
import '../services/api_client.dart';
import '../theme/shadow_theme.dart';

/// Zentraler Applikationszustand (Provider-basiert).
///
/// Hält: Auth, Theme/Highlight/Sprache, Sessions, aktive Session,
/// Modelle und lädt persisted Einstellungen aus SharedPreferences.
class AppState extends ChangeNotifier {
  ShadowUser? _user;
  String? _token;
  String _baseUrl = ApiConfig.defaultLocal;

  // Theme
  ShadowThemeMode _themeMode = ShadowThemeMode.system;
  Color _highlight = ShadowColors.defaultHighlight;
  String _language = 'de';

  // Chat
  List<ChatSession> _sessions = [];
  String? _activeSessionId;
  List<ChatMessage> _activeMessages = [];
  List<ModelEntry> _models = [];
  String? _selectedModelId;
  bool _sending = false;

  bool _initialized = false;

  // ── Getters ──────────────────────────────────────────────────

  ShadowUser? get user => _user;
  bool get isLoggedIn => _token != null && _token!.isNotEmpty;
  bool get isAdmin => _user?.isAdmin ?? false;
  bool get mustChangePassword => _user?.mustChangePassword ?? false;
  bool get needsSetup => _user == null;

  String get baseUrl => _baseUrl;
  ShadowThemeMode get themeMode => _themeMode;
  Color get highlight => _highlight;
  String get language => _language;

  List<ChatSession> get sessions => _sessions;
  String? get activeSessionId => _activeSessionId;
  List<ChatMessage> get activeMessages => _activeMessages;
  List<ModelEntry> get models => _models;
  String? get selectedModelId => _selectedModelId ?? 'shadow-default';
  bool get sending => _sending;
  bool get initialized => _initialized;

  ChatSession? get activeSession => _sessions
      .where((s) => s.id == _activeSessionId)
      .cast<ChatSession?>()
      .firstWhere((s) => s?.id == _activeSessionId, orElse: () => null);

  // ── Init ────────────────────────────────────────────────────

  Future<void> init() async {
    if (_initialized) return;
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = prefs.getString(ApiConfig.keyBaseUrl) ?? ApiConfig.defaultLocal;
    _token = prefs.getString(ApiConfig.keyToken);
    final themeStr = prefs.getString('shadow.theme');
    _themeMode = ShadowThemeModeX.fromString(themeStr);
    final hex = prefs.getString('shadow.highlight');
    if (hex != null) {
      final c = ShadowTheme.parseHex(hex);
      if (c != null) _highlight = c;
    }
    _language = prefs.getString('shadow.language') ?? 'de';
    ApiConfig.configure(baseUrl: _baseUrl, token: _token);

    if (_token != null && _token!.isNotEmpty) {
      try {
        _user = await ApiClient.me();
      } catch (_) {
        // Token ungültig → ausloggen.
        await logout(silent: true);
      }
    }
    _initialized = true;
    notifyListeners();
  }

  // ── Auth ─────────────────────────────────────────────────────

  Future<void> login(String username, String password) async {
    final res = await ApiClient.login(username, password);
    await _applyLogin(res);
  }

  Future<void> setup({
    required String username,
    required String password,
    String? email,
    String? killSwitch,
  }) async {
    final res = await ApiClient.setup(
      username: username,
      password: password,
      email: email,
      killSwitch: killSwitch,
    );
    await _applyLogin(res);
  }

  Future<void> _applyLogin(LoginResponse res) async {
    _token = res.token;
    _user = res.user;
    ApiConfig.token = _token;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(ApiConfig.keyToken, _token!);
    await prefs.setString(ApiConfig.keyBaseUrl, _baseUrl);
    notifyListeners();
    if (!res.mustChangePassword) {
      await refreshModels();
      await refreshSessions();
    }
  }

  Future<void> logout({bool silent = false}) async {
    _token = null;
    _user = null;
    _sessions = [];
    _activeSessionId = null;
    _activeMessages = [];
    ApiConfig.token = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(ApiConfig.keyToken);
    notifyListeners();
    if (!silent) {}
  }

  // ── Settings / Theme ─────────────────────────────────────────

  Future<void> setBaseUrl(String url) async {
    _baseUrl = url;
    ApiConfig.configure(baseUrl: url, token: _token);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(ApiConfig.keyBaseUrl, url);
    notifyListeners();
  }

  Future<void> setThemeMode(ShadowThemeMode mode) async {
    _themeMode = mode;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('shadow.theme', mode.name);
    // Auf dem Server persistieren (falls eingeloggt).
    if (isLoggedIn) {
      try {
        await ApiClient.updateSettings({'theme': mode.name});
      } catch (_) {}
    }
    notifyListeners();
  }

  Future<void> setHighlight(Color color) async {
    _highlight = color;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('shadow.highlight', ShadowTheme.toHex(color));
    if (isLoggedIn) {
      try {
        await ApiClient.updateSettings({'highlight': ShadowTheme.toHex(color)});
      } catch (_) {}
    }
    notifyListeners();
  }

  Future<void> setLanguage(String lang) async {
    _language = lang;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('shadow.language', lang);
    if (isLoggedIn) {
      try {
        await ApiClient.updateSettings({'language': lang});
      } catch (_) {}
    }
    notifyListeners();
  }

  // ── Sessions ────────────────────────────────────────────────

  Future<void> refreshSessions() async {
    if (!isLoggedIn) return;
    _sessions = await ApiClient.listSessions();
    notifyListeners();
  }

  Future<void> selectSession(String id) async {
    _activeSessionId = id;
    _activeMessages = await ApiClient.messages(id);
    notifyListeners();
  }

  Future<void> createSession({String? title}) async {
    final session = await ApiClient.createSession(
      title: title ?? 'Neuer Chat',
      modelId: selectedModelId,
    );
    _sessions = [session, ..._sessions];
    _activeSessionId = session.id;
    _activeMessages = [];
    notifyListeners();
  }

  Future<void> renameSession(String id, String title) async {
    await ApiClient.renameSession(id, title);
    await refreshSessions();
  }

  Future<void> deleteSession(String id) async {
    await ApiClient.deleteSession(id);
    if (_activeSessionId == id) {
      _activeSessionId = null;
      _activeMessages = [];
    }
    await refreshSessions();
  }

  Future<void> mergeSessions(String a, String b, String title) async {
    await ApiClient.mergeSessions(a, b, title);
    await refreshSessions();
  }

  // ── Chat ─────────────────────────────────────────────────────

  Future<void> sendMessage(String content) async {
    if (_activeSessionId == null || content.trim().isEmpty) return;
    final sessionId = _activeSessionId!;
    // Optimistisch die User-Nachricht anzeigen.
    final optimistic = ChatMessage(
      id: 'pending-${DateTime.now().millisecondsSinceEpoch}',
      sessionId: sessionId,
      role: 'user',
      content: content,
      createdAt: DateTime.now().millisecondsSinceEpoch ~/ 1000,
    );
    _activeMessages = [..._activeMessages, optimistic];
    _sending = true;
    notifyListeners();

    try {
      final res = await ApiClient.sendMessage(sessionId, content);
      final assistant = ChatMessage(
        id: 'a-${DateTime.now().millisecondsSinceEpoch}',
        sessionId: sessionId,
        role: 'assistant',
        content: res.assistantMessage,
        finishReason: res.finishReason,
        createdAt: DateTime.now().millisecondsSinceEpoch ~/ 1000,
      );
      _activeMessages = [..._activeMessages, assistant];
    } on ApiException catch (e) {
      final err = ChatMessage(
        id: 'err-${DateTime.now().millisecondsSinceEpoch}',
        sessionId: sessionId,
        role: 'assistant',
        content: 'Fehler: ${e.message}',
        finishReason: 'Error',
        createdAt: DateTime.now().millisecondsSinceEpoch ~/ 1000,
      );
      _activeMessages = [..._activeMessages, err];
    } finally {
      _sending = false;
      notifyListeners();
    }
  }

  // ── Models ───────────────────────────────────────────────────

  Future<void> refreshModels() async {
    if (!isLoggedIn) return;
    _models = await ApiClient.listModels();
    if (_selectedModelId == null && _models.isNotEmpty) {
      _selectedModelId = _models.first.modelId;
    }
    notifyListeners();
  }

  void selectModel(String modelId) {
    _selectedModelId = modelId;
    notifyListeners();
  }
}
