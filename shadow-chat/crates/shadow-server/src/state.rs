//! Applikationszustand des Shadow-Servers.
//!
//! Hält die SQLite-Verbindung (hinter einem Mutex, da rusqlite::Connection
//! nicht Sync ist), den entsperrten Master-Key, eine In-Memory-Session-Token-
//! Map sowie den konfigurierten Modell-Adapter (Stub oder Shadow LLM Engine).

use std::collections::HashMap;
use std::sync::{Mutex, RwLock};

use rusqlite::Connection;
use shadow_core::crypto::MasterKey;
use shadow_core::model::{ModelAdapter, PythonAdapter, StubAdapter};
use shadow_core::ShadowError;

use crate::error::ApiError;

pub struct AppState {
    pub conn: Mutex<Connection>,
    pub key: MasterKey,
    /// Session-Token -> User-ID. MVP: In-Memory; bei Serverneustart müssen
    /// Clients sich neu einloggen (sicherer als persistente Tokens).
    pub tokens: RwLock<HashMap<String, String>>,
    /// Datenverzeichnis (für Exporte, Audit-Pfade).
    pub data_dir: std::path::PathBuf,
    /// Modell-Adapter hinter Mutex (stream benötigt &mut).
    pub adapter: Mutex<Box<dyn ModelAdapter>>,
}

impl AppState {
    /// Legt den Adapter an: Stub (immer verfügbar) oder, falls
    /// SHADOW_AI_CMD gesetzt ist, den Python-Adapter zur LLM-Engine.
    pub fn build_adapter() -> Box<dyn ModelAdapter> {
        if let Ok(cmd) = std::env::var("SHADOW_AI_CMD") {
            let parts: Vec<String> = cmd.split_whitespace().map(String::from).collect();
            if !parts.is_empty() {
                return Box::new(PythonAdapter::new(parts));
            }
        }
        Box::new(StubAdapter::new())
    }

    /// Prüft das Bearer-Token und liefert die zugehörige User-ID.
    pub fn require_user(&self, token: Option<&str>) -> Result<String, ApiError> {
        let token = token
            .and_then(|t| t.strip_prefix("Bearer ").or_else(|| Some(t)))
            .ok_or_else(|| ApiError::unauthorized("kein Token"))?;
        let tokens = self.tokens.read().unwrap();
        let user_id = tokens
            .get(token)
            .cloned()
            .ok_or_else(|| ApiError::unauthorized("ungültiges oder abgelaufenes Token"))?;
        Ok(user_id)
    }

    /// Lädt den User und stellt sicher, dass er Admin ist.
    pub fn require_admin(&self, token: Option<&str>) -> Result<String, ApiError> {
        let user_id = self.require_user(token)?;
        let conn = self.conn.lock().unwrap();
        let user = shadow_core::auth::UserStore::new(&conn)
            .get_user(&user_id)
            .map_err(|e| ApiError::from_core(&e))?
            .ok_or_else(|| ApiError::not_found("user"))?;
        if user.role != "admin" {
            return Err(ApiError::forbidden("Admin-Rechte erforderlich"));
        }
        Ok(user_id)
    }

    /// Erstellt ein neues zufälliges Session-Token für einen User.
    pub fn issue_token(&self, user_id: &str) -> String {
        let token = uuid::Uuid::new_v4().to_string();
        self.tokens.write().unwrap().insert(token.clone(), user_id.to_string());
        token
    }
}

/// Hilfsfunktion: SQLite-Verbindung + Keystore öffnen/initialisieren.
pub fn open_store(data_dir: &std::path::Path) -> Result<(Connection, MasterKey), ShadowError> {
    std::fs::create_dir_all(data_dir).map_err(|e| ShadowError::Io(e))?;
    let db_path = data_dir.join("shadow.db");
    let conn = shadow_core::store::open(&db_path)?;
    let pw = std::env::var("SHADOW_PASSWORD").unwrap_or_else(|_| {
        tracing::warn!("SHADOW_PASSWORD nicht gesetzt — nutze Entwicklungs-Passwort.");
        "dev-only-not-secure".to_string()
    });
    let key = if shadow_core::keystore_is_initialized(&conn)? {
        shadow_core::keystore_unlock(&conn, &pw)?
    } else {
        shadow_core::keystore_initialize(&conn, &pw)?
    };
    // Beim ersten Start den Default-Admin (Admin/1234) anlegen, falls noch
    // kein Account existiert.
    let us = shadow_core::auth::UserStore::new(&conn);
    if us.is_first_start()? {
        us.bootstrap_default_admin()?;
        tracing::info!("First-Login-Admin (Admin/1234) angelegt — bitte beim ersten Login ändern.");
    }
    Ok((conn, key))
}
