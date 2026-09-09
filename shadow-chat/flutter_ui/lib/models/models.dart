import 'package:flutter/foundation.dart';

/// Benutzer-Account. Rollen: admin | user | test.
@immutable
class ShadowUser {
  final String id;
  final String name;
  final String role;
  final String? email;
  final bool mustChangePassword;
  final int createdAt;
  final int? expiresAt;

  const ShadowUser({
    required this.id,
    required this.name,
    required this.role,
    this.email,
    this.mustChangePassword = false,
    this.createdAt = 0,
    this.expiresAt,
  });

  factory ShadowUser.fromJson(Map<String, dynamic> j) => ShadowUser(
        id: j['id'] as String,
        name: j['name'] as String,
        role: j['role'] as String,
        email: j['email'] as String?,
        mustChangePassword: j['must_change_password'] as bool? ?? false,
        createdAt: j['created_at'] as int? ?? 0,
        expiresAt: j['expires_at'] as int?,
      );

  bool get isAdmin => role == 'admin';
  bool get isExpired =>
      role == 'test' &&
      expiresAt != null &&
      expiresAt! <= DateTime.now().millisecondsSinceEpoch ~/ 1000;

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'role': role,
        'email': email,
        'must_change_password': mustChangePassword,
        'created_at': createdAt,
        'expires_at': expiresAt,
      };
}

/// Chat-Session (Metadaten).
@immutable
class ChatSession {
  final String id;
  final String userId;
  final String title;
  final String modelId;
  final int createdAt;
  final int updatedAt;

  const ChatSession({
    required this.id,
    required this.userId,
    required this.title,
    required this.modelId,
    required this.createdAt,
    required this.updatedAt,
  });

  factory ChatSession.fromJson(Map<String, dynamic> j) => ChatSession(
        id: j['id'] as String,
        userId: j['user_id'] as String,
        title: j['title'] as String,
        modelId: j['model_id'] as String,
        createdAt: j['created_at'] as int? ?? 0,
        updatedAt: j['updated_at'] as int? ?? 0,
      );
}

/// Eine Chat-Nachricht (system | user | assistant).
@immutable
class ChatMessage {
  final String id;
  final String sessionId;
  final String role;
  final String content;
  final String? finishReason;
  final int createdAt;

  const ChatMessage({
    required this.id,
    required this.sessionId,
    required this.role,
    required this.content,
    this.finishReason,
    required this.createdAt,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
        id: j['id'] as String,
        sessionId: j['session_id'] as String,
        role: j['role'] as String,
        content: j['content'] as String? ?? '',
        finishReason: j['finish_reason'] as String?,
        createdAt: j['created_at'] as int? ?? 0,
      );

  bool get isUser => role == 'user';
  bool get isAssistant => role == 'assistant';
}

/// Ein freigegebenes Modell.
@immutable
class ModelEntry {
  final String modelId;
  final String adapterType;
  final String displayName;
  final int contextWindow;
  final bool enabled;
  final bool exportAllowed;

  const ModelEntry({
    required this.modelId,
    required this.adapterType,
    required this.displayName,
    this.contextWindow = 8192,
    this.enabled = true,
    this.exportAllowed = false,
  });

  factory ModelEntry.fromJson(Map<String, dynamic> j) => ModelEntry(
        modelId: j['model_id'] as String,
        adapterType: j['adapter_type'] as String? ?? 'stub',
        displayName: j['display_name'] as String? ?? j['model_id'] as String,
        contextWindow: j['context_window'] as int? ?? 8192,
        enabled: j['enabled'] as bool? ?? true,
        exportAllowed: j['export_allowed'] as bool? ?? false,
      );
}

/// Antwort auf eine Login-/Setup-Anfrage.
@immutable
class LoginResponse {
  final String token;
  final ShadowUser user;
  final bool mustChangePassword;

  const LoginResponse({
    required this.token,
    required this.user,
    this.mustChangePassword = false,
  });

  factory LoginResponse.fromJson(Map<String, dynamic> j) => LoginResponse(
        token: j['token'] as String,
        user: ShadowUser.fromJson(j['user'] as Map<String, dynamic>),
        mustChangePassword: j['must_change_password'] as bool? ?? false,
      );
}

/// Senden-Antwort (generierte Nachricht + Metriken).
@immutable
class SendMessageResponse {
  final String assistantMessage;
  final int tokensIn;
  final int tokensOut;
  final int latencyMs;
  final String finishReason;

  const SendMessageResponse({
    required this.assistantMessage,
    required this.tokensIn,
    required this.tokensOut,
    required this.latencyMs,
    required this.finishReason,
  });

  factory SendMessageResponse.fromJson(Map<String, dynamic> j) =>
      SendMessageResponse(
        assistantMessage: j['assistant_message'] as String? ?? '',
        tokensIn: j['tokens_in'] as int? ?? 0,
        tokensOut: j['tokens_out'] as int? ?? 0,
        latencyMs: j['latency_ms'] as int? ?? 0,
        finishReason: j['finish_reason'] as String? ?? 'Stop',
      );
}

/// Systemstatus des Admin-Dashboards.
@immutable
class SystemStatus {
  final String version;
  final String dataDir;
  final bool keystoreInitialized;
  final int userCount;
  final int modelCount;
  final String engine;
  final String engineStatus;

  const SystemStatus({
    required this.version,
    required this.dataDir,
    required this.keystoreInitialized,
    required this.userCount,
    required this.modelCount,
    required this.engine,
    required this.engineStatus,
  });

  factory SystemStatus.fromJson(Map<String, dynamic> j) => SystemStatus(
        version: j['version'] as String? ?? '',
        dataDir: j['data_dir'] as String? ?? '',
        keystoreInitialized: j['keystore_initialized'] as bool? ?? false,
        userCount: j['user_count'] as int? ?? 0,
        modelCount: j['model_count'] as int? ?? 0,
        engine: j['engine'] as String? ?? 'stub',
        engineStatus: j['engine_status'] as String? ?? 'Down',
      );
}

/// Ein Audit-Event.
@immutable
class AuditEvent {
  final String id;
  final int timestamp;
  final String actor;
  final String action;
  final String target;
  final Map<String, dynamic> detail;

  const AuditEvent({
    required this.id,
    required this.timestamp,
    required this.actor,
    required this.action,
    required this.target,
    required this.detail,
  });

  factory AuditEvent.fromJson(Map<String, dynamic> j) => AuditEvent(
        id: j['id'] as String,
        timestamp: j['timestamp'] as int? ?? 0,
        actor: j['actor'] as String? ?? '',
        action: j['action'] as String? ?? '',
        target: j['target'] as String? ?? '',
        detail: (j['detail'] as Map<String, dynamic>?) ?? {},
      );
}
