//! HTTP-Routen des Shadow-Servers.
//!
//! Alle Pfade liegen unter `/api`. Authentifizierte Endpunkte erwarten
//! `Authorization: Bearer <token>`. Token werden beim Login ausgestellt.

use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::HeaderMap;
use axum::{routing::{delete, get, post}, Json, Router};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::error::ApiError;
use crate::state::AppState;

pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        // ── Auth ──────────────────────────────────────────────
        .route("/api/auth/status", get(auth_status))
        .route("/api/auth/login", post(auth_login))
        .route("/api/auth/setup", post(auth_setup))
        .route("/api/auth/me", get(auth_me))
        // ── Users (Admin) ─────────────────────────────────────
        .route("/api/users", get(users_list).post(users_create))
        .route("/api/users/:id", delete(users_delete))
        .route("/api/users/:id/password", post(users_set_password))
        .route("/api/users/deactivate-expired", post(users_deactivate_expired))
        // ── Sessions / Chats ───────────────────────────────────
        .route("/api/sessions", get(sessions_list).post(sessions_create))
        .route("/api/sessions/merge", post(sessions_merge))
        .route("/api/sessions/:id", get(sessions_get).patch(sessions_rename).delete(sessions_delete))
        .route("/api/sessions/:id/messages", get(sessions_messages).post(sessions_send))
        // ── Models ─────────────────────────────────────────────
        .route("/api/models", get(models_list_enabled))
        .route("/api/models/all", get(models_list_all))
        .route("/api/models", post(models_upsert))
        .route("/api/models/:id/toggle", post(models_toggle))
        .route("/api/models/:id/health", get(models_health))
        // ── Settings ───────────────────────────────────────────
        .route("/api/settings", get(settings_get).patch(settings_update))
        // ── Admin ──────────────────────────────────────────────
        .route("/api/admin/system", get(admin_system))
        .route("/api/admin/audit", get(admin_audit))
        .route("/api/admin/benchmark", post(admin_benchmark))
        .route("/api/admin/training", get(admin_training).patch(admin_training_update))
        .route("/api/admin/nodes", get(admin_nodes))
        // ── Plugins ───────────────────────────────────────────
        .route("/api/plugins", get(plugins_list))
        // ── Engine / LLM ──────────────────────────────────────
        .route("/api/engine/health", get(engine_health))
        .with_state(state)
}

// ── Hilfsfunktionen ──────────────────────────────────────────────

fn bearer_token(headers: &HeaderMap) -> Option<String> {
    headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .map(str::to_string)
}

// ════════════════════════════════════════════════════════════════
// AUTH
// ════════════════════════════════════════════════════════════════

#[derive(Serialize)]
pub struct AuthStatus {
    pub first_start: bool,
    pub keystore_initialized: bool,
    pub version: &'static str,
}

async fn auth_status(State(s): State<Arc<AppState>>) -> Result<Json<AuthStatus>, ApiError> {
    let conn = s.conn.lock().unwrap();
    let us = shadow_core::auth::UserStore::new(&conn);
    let first = us.is_first_start().map_err(|e| ApiError::from_core(&e))?;
    let kinit = shadow_core::keystore_is_initialized(&conn).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(AuthStatus { first_start: first, keystore_initialized: kinit, version: "2.0" }))
}

#[derive(Deserialize)]
pub struct LoginRequest { pub username: String, pub password: String }

#[derive(Serialize)]
pub struct LoginResponse {
    pub token: String,
    pub user: shadow_core::auth::User,
    pub must_change_password: bool,
    pub kill_switch_triggered: bool,
}

async fn auth_login(
    State(s): State<Arc<AppState>>,
    Json(req): Json<LoginRequest>,
) -> Result<Json<LoginResponse>, ApiError> {
    let conn = s.conn.lock().unwrap();
    let us = shadow_core::auth::UserStore::new(&conn);
    let outcome = us
        .verify_account(&req.username, &req.password)
        .map_err(|e| ApiError::from_core(&e))?;
    match outcome {
        shadow_core::auth::AuthOutcome::Ok(user) => {
            let token = s.issue_token(&user.id);
            Ok(Json(LoginResponse { token, user, must_change_password: false, kill_switch_triggered: false }))
        }
        shadow_core::auth::AuthOutcome::MustChangePassword(user) => {
            // First-Login: temporäres Token, nur für /setup nutzbar.
            let token = s.issue_token(&user.id);
            Ok(Json(LoginResponse { token, user, must_change_password: true, kill_switch_triggered: false }))
        }
        shadow_core::auth::AuthOutcome::KillSwitchTriggered => {
            Err(ApiError::forbidden("Kill-Switch ausgelöst — Account-Daten wurden gelöscht."))
        }
        shadow_core::auth::AuthOutcome::InvalidCredentials => {
            Err(ApiError::unauthorized("Benutzername oder Passwort falsch"))
        }
    }
}

#[derive(Deserialize)]
pub struct SetupRequest {
    pub username: String,
    pub password: String,
    pub email: Option<String>,
    pub kill_switch: Option<String>,
}

async fn auth_setup(
    State(s): State<Arc<AppState>>,
    Json(req): Json<SetupRequest>,
) -> Result<Json<LoginResponse>, ApiError> {
    let conn = s.conn.lock().unwrap();
    let us = shadow_core::auth::UserStore::new(&conn);
    // Default-Admin muss noch aktiv sein, sonst ist Setup bereits erfolgt.
    if !us.verify_default_admin(shadow_core::auth::DEFAULT_ADMIN_PASSWORD).map_err(|e| ApiError::from_core(&e))? {
        return Err(ApiError::bad_request("Einrichtung bereits abgeschlossen — kein Default-Admin mehr aktiv."));
    }
    let user = us
        .create_admin_replace_default(
            &req.username,
            &req.password,
            req.email.as_deref(),
            req.kill_switch.as_deref(),
        )
        .map_err(|e| ApiError::from_core(&e))?;
    let token = s.issue_token(&user.id);
    Ok(Json(LoginResponse { token, user, must_change_password: false, kill_switch_triggered: false }))
}

async fn auth_me(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<shadow_core::auth::User>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let user = shadow_core::auth::UserStore::new(&conn)
        .get_user(&user_id)
        .map_err(|e| ApiError::from_core(&e))?
        .ok_or_else(|| ApiError::not_found("user"))?;
    Ok(Json(user))
}

// ════════════════════════════════════════════════════════════════
// USERS
// ════════════════════════════════════════════════════════════════

async fn users_list(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<Vec<shadow_core::auth::User>>, ApiError> {
    let _actor = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let users = shadow_core::auth::UserStore::new(&conn)
        .list_users()
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(users))
}

#[derive(Deserialize)]
pub struct CreateUserRequest {
    pub username: String,
    pub password: String,
    pub role: String,
    pub email: Option<String>,
    /// Unix-Sekunden; nur für Rolle 'test'.
    pub expires_at: Option<i64>,
}

async fn users_create(
    headers: HeaderMap,
    State(s): State<Arc<AppState>>,
    Json(req): Json<CreateUserRequest>,
) -> Result<Json<shadow_core::auth::User>, ApiError> {
    let actor = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let user = shadow_core::auth::UserStore::new(&conn)
        .create_user(&actor, &req.username, &req.password, &req.role, req.email.as_deref(), req.expires_at)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(user))
}

async fn users_delete(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(id): Path<String>) -> Result<Json<serde_json::Value>, ApiError> {
    let actor = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    shadow_core::auth::UserStore::new(&conn)
        .delete_user(&actor, &id)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"deleted": id})))
}

#[derive(Deserialize)]
pub struct SetPasswordRequest { pub new_password: String }

async fn users_set_password(
    headers: HeaderMap,
    State(s): State<Arc<AppState>>,
    Path(id): Path<String>,
    Json(req): Json<SetPasswordRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let actor = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    shadow_core::auth::UserStore::new(&conn)
        .set_password(&actor, &id, &req.new_password)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"updated": id})))
}

async fn users_deactivate_expired(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    let actor = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let ids = shadow_core::auth::UserStore::new(&conn)
        .deactivate_expired_test_users(&actor)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"deactivated": ids})))
}

// ════════════════════════════════════════════════════════════════
// SESSIONS / CHATS
// ════════════════════════════════════════════════════════════════

async fn sessions_list(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<Vec<shadow_core::session::SessionMeta>>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let sessions = shadow_core::session::SessionStore::new(&conn)
        .list_sessions(&user_id)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(sessions))
}

#[derive(Deserialize)]
pub struct CreateSessionRequest {
    pub title: Option<String>,
    pub model_id: Option<String>,
}

async fn sessions_create(
    headers: HeaderMap,
    State(s): State<Arc<AppState>>,
    Json(req): Json<CreateSessionRequest>,
) -> Result<Json<serde_json::Value>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let model_id = req.model_id.unwrap_or_else(|| "shadow-default".to_string());
    let title = req.title.unwrap_or_else(|| "Neuer Chat".to_string());
    let id = shadow_core::session::SessionStore::new(&conn)
        .create_session(&user_id, &model_id, &title)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"id": id, "model_id": model_id, "title": title})))
}

async fn sessions_get(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(id): Path<String>) -> Result<Json<shadow_core::session::SessionMeta>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let meta = shadow_core::session::SessionStore::new(&conn)
        .get_session(&id)
        .map_err(|e| ApiError::from_core(&e))?
        .ok_or_else(|| ApiError::not_found("session"))?;
    if meta.user_id != user_id {
        return Err(ApiError::forbidden("kein Zugriff auf diese Session"));
    }
    Ok(Json(meta))
}

#[derive(Deserialize)]
pub struct RenameSessionRequest { pub title: String }

async fn sessions_rename(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(id): Path<String>, Json(req): Json<RenameSessionRequest>) -> Result<Json<serde_json::Value>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let store = shadow_core::session::SessionStore::new(&conn);
    let meta = store.get_session(&id).map_err(|e| ApiError::from_core(&e))?.ok_or_else(|| ApiError::not_found("session"))?;
    if meta.user_id != user_id {
        return Err(ApiError::forbidden("kein Zugriff auf diese Session"));
    }
    store.rename_session(&id, &req.title).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"renamed": id, "title": req.title})))
}

async fn sessions_delete(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(id): Path<String>) -> Result<Json<serde_json::Value>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let store = shadow_core::session::SessionStore::new(&conn);
    let meta = store.get_session(&id).map_err(|e| ApiError::from_core(&e))?.ok_or_else(|| ApiError::not_found("session"))?;
    if meta.user_id != user_id {
        return Err(ApiError::forbidden("kein Zugriff auf diese Session"));
    }
    store.delete_session(&id).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"deleted": id})))
}

async fn sessions_messages(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(id): Path<String>) -> Result<Json<Vec<shadow_core::session::Message>>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let store = shadow_core::session::SessionStore::new(&conn);
    let meta = store.get_session(&id).map_err(|e| ApiError::from_core(&e))?.ok_or_else(|| ApiError::not_found("session"))?;
    if meta.user_id != user_id {
        return Err(ApiError::forbidden("kein Zugriff auf diese Session"));
    }
    let msgs = store.messages(&s.key, &id).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(msgs))
}

#[derive(Deserialize)]
pub struct SendMessageRequest { pub content: String }

#[derive(Serialize)]
pub struct SendMessageResponse {
    pub assistant_message: String,
    pub tokens_in: u32,
    pub tokens_out: u32,
    pub latency_ms: u64,
    pub finish_reason: String,
}

async fn sessions_send(
    headers: HeaderMap,
    State(s): State<Arc<AppState>>,
    Path(id): Path<String>,
    Json(req): Json<SendMessageRequest>,
) -> Result<Json<SendMessageResponse>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    // 1) Berechtigung prüfen + Nachrichten laden (innerhalb conn-lock).
    let (_model_id, history) = {
        let conn = s.conn.lock().unwrap();
        let store = shadow_core::session::SessionStore::new(&conn);
        let meta = store.get_session(&id).map_err(|e| ApiError::from_core(&e))?.ok_or_else(|| ApiError::not_found("session"))?;
        if meta.user_id != user_id {
            return Err(ApiError::forbidden("kein Zugriff auf diese Session"));
        }
        let msgs = store.messages(&s.key, &id).map_err(|e| ApiError::from_core(&e))?;
        let history: Vec<shadow_core::model::MessageInput> = msgs
            .into_iter()
            .filter(|m| m.role == "user" || m.role == "assistant")
            .map(|m| shadow_core::model::MessageInput { role: m.role, content: m.content })
            .collect();
        (meta.model_id, history)
    };

    // 2) User-Nachricht persistieren.
    {
        let conn = s.conn.lock().unwrap();
        shadow_core::session::SessionStore::new(&conn)
            .append_message(&s.key, &id, "user", &req.content, None)
            .map_err(|e| ApiError::from_core(&e))?;
    }

    // 3) Generierung über den Adapter (außerhalb conn-lock, da &mut).
    let mut history = history;
    history.push(shadow_core::model::MessageInput { role: "user".into(), content: req.content.clone() });
    let gen_req = shadow_core::model::GenerateRequest {
        session_id: id.clone(),
        messages: history,
        params: shadow_core::model::GenParams::default(),
        constraints: shadow_core::model::GenConstraints::default(),
    };

    let reply = std::sync::Arc::new(std::sync::Mutex::new(String::new()));
    let reply_inner = reply.clone();
    let result = {
        let mut adapter = s.adapter.lock().unwrap();
        adapter.stream(gen_req, Box::new(move |ev| {
            if let shadow_core::model::StreamEvent::Token { text, .. } = ev {
                reply_inner.lock().unwrap().push_str(&text);
            }
        })).map_err(|e| ApiError::from_core(&shadow_core::ShadowError::from(e)))?
    };
    let assistant_text = reply.lock().unwrap().clone();

    // 4) Assistant-Antwort persistieren.
    {
        let conn = s.conn.lock().unwrap();
        shadow_core::session::SessionStore::new(&conn)
            .append_message(&s.key, &id, "assistant", &assistant_text, Some(&format!("{:?}", result.finish_reason)))
            .map_err(|e| ApiError::from_core(&e))?;
    }

    Ok(Json(SendMessageResponse {
        assistant_message: assistant_text,
        tokens_in: result.tokens_in,
        tokens_out: result.tokens_out,
        latency_ms: result.latency_ms,
        finish_reason: format!("{:?}", result.finish_reason),
    }))
}

#[derive(Deserialize)]
pub struct MergeSessionsRequest {
    pub chat1: String,
    pub chat2: String,
    pub title: String,
}

async fn sessions_merge(headers: HeaderMap, State(s): State<Arc<AppState>>, Json(req): Json<MergeSessionsRequest>) -> Result<Json<serde_json::Value>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let new_id = shadow_core::session::SessionStore::new(&conn)
        .merge_sessions(&user_id, &req.chat1, &req.chat2, &req.title)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"merged_into": new_id, "sources": [req.chat1, req.chat2]})))
}

// ════════════════════════════════════════════════════════════════
// MODELS
// ════════════════════════════════════════════════════════════════

async fn models_list_enabled(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<Vec<shadow_core::model::ModelEntry>>, ApiError> {
    let _ = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let models = shadow_core::model::ModelRegistry::new(&conn)
        .list_enabled()
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(models))
}

async fn models_list_all(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<Vec<shadow_core::model::ModelEntry>>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let reg = shadow_core::model::ModelRegistry::new(&conn);
    // list_enabled existiert; für "all" nutzen wir dasselbe, da die Registry
    // im MVP keine separaten deaktivierten Einträge verwaltet.
    let models = reg.list_enabled().map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(models))
}

async fn models_upsert(headers: HeaderMap, State(s): State<Arc<AppState>>, Json(entry): Json<shadow_core::model::ModelEntry>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    shadow_core::model::ModelRegistry::new(&conn)
        .upsert(&entry)
        .map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"upserted": entry.model_id})))
}

#[derive(Deserialize)]
pub struct ToggleModelRequest { pub enabled: bool }

async fn models_toggle(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(id): Path<String>, Json(req): Json<ToggleModelRequest>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let reg = shadow_core::model::ModelRegistry::new(&conn);
    let mut entry = reg.get(&id).map_err(|e| ApiError::from_core(&e))?.ok_or_else(|| ApiError::not_found("model"))?;
    entry.enabled = req.enabled;
    reg.upsert(&entry).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(json!({"model": id, "enabled": req.enabled})))
}

async fn models_health(headers: HeaderMap, State(s): State<Arc<AppState>>, Path(_id): Path<String>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_user(bearer_token(&headers).as_deref())?;
    let status = {
        let mut adapter = s.adapter.lock().unwrap();
        adapter.health()
    };
    Ok(Json(json!({"status": format!("{:?}", status)})))
}

// ════════════════════════════════════════════════════════════════
// SETTINGS
// ════════════════════════════════════════════════════════════════

async fn settings_get(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let settings = shadow_core::settings::get_settings(&conn, &user_id).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(settings))
}

async fn settings_update(headers: HeaderMap, State(s): State<Arc<AppState>>, Json(patch): Json<serde_json::Value>) -> Result<Json<serde_json::Value>, ApiError> {
    let user_id = s.require_user(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let settings = shadow_core::settings::update_settings(&conn, &user_id, &user_id, patch).map_err(|e| ApiError::from_core(&e))?;
    Ok(Json(settings))
}

// ════════════════════════════════════════════════════════════════
// ADMIN
// ════════════════════════════════════════════════════════════════

#[derive(Serialize)]
pub struct SystemStatus {
    pub version: &'static str,
    pub data_dir: String,
    pub keystore_initialized: bool,
    pub user_count: usize,
    pub model_count: usize,
    pub engine: String,
    pub engine_status: String,
}

async fn admin_system(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<SystemStatus>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let users = shadow_core::auth::UserStore::new(&conn).list_users().map_err(|e| ApiError::from_core(&e))?;
    let models = shadow_core::model::ModelRegistry::new(&conn).list_enabled().map_err(|e| ApiError::from_core(&e))?;
    let kinit = shadow_core::keystore_is_initialized(&conn).map_err(|e| ApiError::from_core(&e))?;
    let engine = std::env::var("SHADOW_AI_CMD").unwrap_or_else(|_| "stub".to_string());
    let engine_status = {
        let mut adapter = s.adapter.lock().unwrap();
        format!("{:?}", adapter.health())
    };
    Ok(Json(SystemStatus {
        version: "2.0",
        data_dir: s.data_dir.display().to_string(),
        keystore_initialized: kinit,
        user_count: users.len(),
        model_count: models.len(),
        engine,
        engine_status,
    }))
}

#[derive(Deserialize)]
pub struct AuditQuery { pub limit: Option<i64> }

async fn admin_audit(headers: HeaderMap, State(s): State<Arc<AppState>>, Query(q): Query<AuditQuery>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    let conn = s.conn.lock().unwrap();
    let limit = q.limit.unwrap_or(100).clamp(1, 1000);
    let mut stmt = conn.prepare(
        "SELECT id, timestamp, actor, action, target, detail_json
         FROM audit_event ORDER BY timestamp DESC LIMIT ?1",
    ).map_err(|e| ApiError::internal(e.to_string()))?;
    let rows = stmt.query_map([limit], |r| {
        let detail: String = r.get(5)?;
        Ok(json!({
            "id": r.get::<_, String>(0)?,
            "timestamp": r.get::<_, i64>(1)?,
            "actor": r.get::<_, String>(2)?,
            "action": r.get::<_, String>(3)?,
            "target": r.get::<_, String>(4)?,
            "detail": serde_json::from_str::<serde_json::Value>(&detail).unwrap_or(json!({})),
        }))
    }).map_err(|e| ApiError::internal(e.to_string()))?;
    let events: Vec<serde_json::Value> = rows.filter_map(|r| r.ok()).collect();
    Ok(Json(json!(events)))
}

#[derive(Deserialize)]
pub struct BenchmarkRequest { pub model_id: String, pub runs: Option<usize> }

async fn admin_benchmark(headers: HeaderMap, State(s): State<Arc<AppState>>, Json(req): Json<BenchmarkRequest>) -> Result<Json<shadow_core::bench::BenchResult>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    let runs = req.runs.unwrap_or(3);
    let result = {
        let mut adapter = s.adapter.lock().unwrap();
        shadow_core::bench::run_benchmark(&mut **adapter, &req.model_id, runs)
            .map_err(|e| ApiError::from_core(&e))?
    };
    Ok(Json(result))
}

async fn admin_training(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    // Stub: Training ist nicht Teil der Chat-Anwendung; vorbereitet für die
    // LLM-Engine. Echte Werte liefert später die Engine-Schnittstelle.
    Ok(Json(json!({"status": "idle", "progress": 0, "note": "Training wird durch die Shadow LLM Engine gesteuert; Schnittstelle vorbereitet."})))
}

#[derive(Deserialize)]
pub struct TrainingUpdateRequest { pub status: String, pub progress: Option<u32> }

async fn admin_training_update(headers: HeaderMap, State(s): State<Arc<AppState>>, Json(req): Json<TrainingUpdateRequest>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    Ok(Json(json!({"acknowledged": true, "status": req.status, "progress": req.progress.unwrap_or(0)})))
}

async fn admin_nodes(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_admin(bearer_token(&headers).as_deref())?;
    // Stub: Node-Verwaltung ist für verteiltes Training vorgesehen.
    Ok(json!([{"id": "local", "role": "coordinator", "status": "online", "endpoint": "local"}]).into())
}

// ════════════════════════════════════════════════════════════════
// PLUGINS
// ════════════════════════════════════════════════════════════════

async fn plugins_list(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_user(bearer_token(&headers).as_deref())?;
    Ok(json!([
        {"id": "swarm", "name": "Schwarm-Modus", "status": "vorbereitet"},
        {"id": "target-agent", "name": "Ziel-Agent", "status": "vorbereitet"},
        {"id": "prompt-refiner", "name": "Prompt-Verfeinerer", "status": "vorbereitet"},
    ]).into())
}

// ════════════════════════════════════════════════════════════════
// ENGINE
// ════════════════════════════════════════════════════════════════

async fn engine_health(headers: HeaderMap, State(s): State<Arc<AppState>>) -> Result<Json<serde_json::Value>, ApiError> {
    let _ = s.require_user(bearer_token(&headers).as_deref())?;
    let status = {
        let mut adapter = s.adapter.lock().unwrap();
        adapter.health()
    };
    let engine = std::env::var("SHADOW_AI_CMD").unwrap_or_else(|_| "stub".to_string());
    Ok(json!({"engine": engine, "status": format!("{:?}", status)}).into())
}
