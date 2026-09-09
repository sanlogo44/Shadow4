import 'dart:convert';
import 'package:http/http.dart' as http;

import '../models/models.dart';

/// Konfiguration der Server-Verbindung.
///
/// `baseUrl` zeigt auf den shadow-server (lokal oder Netzwerk).
/// Für Web-Builds: der Server muss über CORS verfügen (im Server aktiviert).
class ApiConfig {
  static const String defaultLocal = 'http://127.0.0.1:8787';
  static const String keyBaseUrl = 'shadow.api.baseUrl';
  static const String keyToken = 'shadow.api.token';

  static String baseUrl = defaultLocal;
  static String? token;

  static void configure({required String baseUrl, String? token}) {
    ApiConfig.baseUrl = baseUrl;
    ApiConfig.token = token;
  }
}

/// Fehler der API-Schicht.
class ApiException implements Exception {
  final int? statusCode;
  final String message;
  final String code;

  ApiException(this.message, {this.statusCode, this.code = 'error'});

  @override
  String toString() => '[$code] $message';
}

/// REST-Client für den shadow-server.
///
/// Kapselt alle Endpunkte. Authentifizierte Aufrufe hängen automatisch
/// den `Authorization: Bearer`-Header an, sobald [ApiConfig.token] gesetzt ist.
class ApiClient {
  static Future<String> _url(String path) async => '${ApiConfig.baseUrl}$path';

  static Map<String, String> _headers({bool json = true}) {
    final h = <String, String>{};
    if (json) h['Content-Type'] = 'application/json';
    final token = ApiConfig.token;
    if (token != null && token.isNotEmpty) {
      h['Authorization'] = 'Bearer $token';
    }
    return h;
  }

  static Future<T> _get<T>(
    String path,
    T Function(Map<String, dynamic>) fromJson, {
    bool requiresAuth = true,
  }) async {
    if (requiresAuth) _requireToken();
    final res = await http.get(Uri.parse(await _url(path)), headers: _headers());
    return _decode(res, fromJson);
  }

  static Future<T> _post<T>(
    String path,
    Map<String, dynamic> body,
    T Function(Map<String, dynamic>) fromJson, {
    bool requiresAuth = true,
  }) async {
    if (requiresAuth) _requireToken();
    final res = await http.post(
      Uri.parse(await _url(path)),
      headers: _headers(),
      body: jsonEncode(body),
    );
    return _decode(res, fromJson);
  }

  static Future<void> _delete(String path) async {
    _requireToken();
    final res = await http.delete(Uri.parse(await _url(path)), headers: _headers());
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw _parseError(res);
    }
  }

  static Future<void> _patch(String path, Map<String, dynamic> body) async {
    _requireToken();
    final res = await http.patch(
      Uri.parse(await _url(path)),
      headers: _headers(),
      body: jsonEncode(body),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw _parseError(res);
    }
  }

  static void _requireToken() {
    final t = ApiConfig.token;
    if (t == null || t.isEmpty) {
      throw ApiException('Nicht eingeloggt (kein Token).', code: 'unauthorized');
    }
  }

  static T _decode<T>(http.Response res, T Function(Map<String, dynamic>) f) {
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw _parseError(res);
    }
    final body = res.body.isEmpty ? '{}' : res.body;
    return f(jsonDecode(body) as Map<String, dynamic>);
  }

  static ApiException _parseError(http.Response res) {
    try {
      final j = jsonDecode(res.body) as Map<String, dynamic>;
      return ApiException(
        (j['message'] as String?) ?? 'Unbekannter Fehler',
        statusCode: res.statusCode,
        code: (j['error'] as String?) ?? 'error',
      );
    } catch (_) {
      return ApiException(
        'HTTP ${res.statusCode}: ${res.body}',
        statusCode: res.statusCode,
      );
    }
  }

  // ── Auth ──────────────────────────────────────────────────────

  static Future<Map<String, dynamic>> authStatus() async {
    final res = await http.get(Uri.parse(await _url('/api/auth/status')));
    if (res.statusCode != 200) throw _parseError(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  static Future<LoginResponse> login(String username, String password) =>
      _post('/api/auth/login', {
        'username': username,
        'password': password,
      }, LoginResponse.fromJson, requiresAuth: false);

  static Future<LoginResponse> setup({
    required String username,
    required String password,
    String? email,
    String? killSwitch,
  }) =>
      _post('/api/auth/setup', {
        'username': username,
        'password': password,
        if (email != null && email.isNotEmpty) 'email': email,
        if (killSwitch != null && killSwitch.isNotEmpty) 'kill_switch': killSwitch,
      }, LoginResponse.fromJson, requiresAuth: false);

  static Future<ShadowUser> me() => _get('/api/auth/me', ShadowUser.fromJson);

  // ── Users (Admin) ─────────────────────────────────────────────

  static Future<List<ShadowUser>> listUsers() async {
    final res = await http.get(Uri.parse(await _url('/api/users')), headers: _headers());
    final list = jsonDecode(res.body) as List;
    return list.map((e) => ShadowUser.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<ShadowUser> createUser({
    required String username,
    required String password,
    required String role,
    String? email,
    int? expiresAt,
  }) =>
      _post('/api/users', {
        'username': username,
        'password': password,
        'role': role,
        if (email != null && email.isNotEmpty) 'email': email,
        if (expiresAt != null) 'expires_at': expiresAt,
      }, ShadowUser.fromJson);

  static Future<void> deleteUser(String id) => _delete('/api/users/$id');

  static Future<void> setUserPassword(String id, String newPassword) async {
    final res = await http.post(
      Uri.parse(await _url('/api/users/$id/password')),
      headers: _headers(),
      body: jsonEncode({'new_password': newPassword}),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
  }

  static Future<void> deactivateExpiredUsers() async {
    final res = await http.post(Uri.parse(await _url('/api/users/deactivate-expired')), headers: _headers());
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
  }

  // ── Sessions / Chats ──────────────────────────────────────────

  static Future<List<ChatSession>> listSessions() async {
    final res = await http.get(Uri.parse(await _url('/api/sessions')), headers: _headers());
    final list = jsonDecode(res.body) as List;
    return list.map((e) => ChatSession.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<ChatSession> createSession({String? title, String? modelId}) async {
    final res = await http.post(
      Uri.parse(await _url('/api/sessions')),
      headers: _headers(),
      body: jsonEncode({
        if (title != null) 'title': title,
        if (modelId != null) 'model_id': modelId,
      }),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    // Server liefert {id, model_id, title}; wir konstruieren ein ChatSession.
    final j = jsonDecode(res.body) as Map<String, dynamic>;
    return ChatSession(
      id: j['id'] as String,
      userId: '',
      title: j['title'] as String? ?? 'Neuer Chat',
      modelId: j['model_id'] as String? ?? 'shadow-default',
      createdAt: DateTime.now().millisecondsSinceEpoch ~/ 1000,
      updatedAt: DateTime.now().millisecondsSinceEpoch ~/ 1000,
    );
  }

  static Future<void> renameSession(String id, String title) =>
      _patch('/api/sessions/$id', {'title': title});

  static Future<void> deleteSession(String id) => _delete('/api/sessions/$id');

  static Future<List<ChatMessage>> messages(String sessionId) async {
    final res = await http.get(
      Uri.parse(await _url('/api/sessions/$sessionId/messages')),
      headers: _headers(),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    final list = jsonDecode(res.body) as List;
    return list.map((e) => ChatMessage.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<SendMessageResponse> sendMessage(String sessionId, String content) =>
      _post('/api/sessions/$sessionId/messages', {
        'content': content,
      }, SendMessageResponse.fromJson);

  static Future<Map<String, dynamic>> mergeSessions(String a, String b, String title) async {
    final res = await http.post(
      Uri.parse(await _url('/api/sessions/merge')),
      headers: _headers(),
      body: jsonEncode({'chat1': a, 'chat2': b, 'title': title}),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  // ── Models ────────────────────────────────────────────────────

  static Future<List<ModelEntry>> listModels() async {
    final res = await http.get(Uri.parse(await _url('/api/models')), headers: _headers());
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    final list = jsonDecode(res.body) as List;
    return list.map((e) => ModelEntry.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// Alle Modelle (inkl. deaktivierter) — für die Admin-Verwaltung.
  static Future<List<ModelEntry>> listAllModels() async {
    final res = await http.get(Uri.parse(await _url('/api/models/all')), headers: _headers());
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    final list = jsonDecode(res.body) as List;
    return list.map((e) => ModelEntry.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> toggleModel(String id, bool enabled) async {
    final res = await http.post(
      Uri.parse(await _url('/api/models/$id/toggle')),
      headers: _headers(),
      body: jsonEncode({'enabled': enabled}),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
  }

  // ── Settings ─────────────────────────────────────────────────

  static Future<Map<String, dynamic>> getSettings() async {
    final res = await http.get(Uri.parse(await _url('/api/settings')), headers: _headers());
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  static Future<Map<String, dynamic>> updateSettings(Map<String, dynamic> patch) async {
    final res = await http.patch(
      Uri.parse(await _url('/api/settings')),
      headers: _headers(),
      body: jsonEncode(patch),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  // ── Admin ────────────────────────────────────────────────────

  static Future<SystemStatus> systemStatus() => _get('/api/admin/system', SystemStatus.fromJson);

  static Future<List<AuditEvent>> auditLog({int limit = 100}) async {
    final res = await http.get(
      Uri.parse(await _url('/api/admin/audit?limit=$limit')),
      headers: _headers(),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    final list = jsonDecode(res.body) as List;
    return list.map((e) => AuditEvent.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<Map<String, dynamic>> runBenchmark(String modelId, int runs) async {
    final res = await http.post(
      Uri.parse(await _url('/api/admin/benchmark')),
      headers: _headers(),
      body: jsonEncode({'model_id': modelId, 'runs': runs}),
    );
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  static Future<List<Map<String, dynamic>>> plugins() async {
    final res = await http.get(Uri.parse(await _url('/api/plugins')), headers: _headers());
    if (res.statusCode < 200 || res.statusCode >= 300) throw _parseError(res);
    final list = jsonDecode(res.body) as List;
    return list.map((e) => Map<String, dynamic>.from(e as Map)).toList();
  }
}
