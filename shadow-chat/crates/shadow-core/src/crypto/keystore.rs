//! Keystore: Persistenz des Master-Keys in der Tabelle key_material.
//!
//! `initialize` legt den wrapped Key an, `unlock` oeffnet ihn.
//! Danach entschluesselt der MasterKey alle Session-Daten.

use rusqlite::{Connection, OptionalExtension};
use crate::crypto::master_key::{KdfParams, MasterKey};
use crate::error::ShadowError;

pub fn is_initialized(conn: &Connection) -> Result<bool, ShadowError> {
    let n: i64 = conn.query_row(
        "SELECT COUNT(*) FROM key_material WHERE id = 1", [], |r| r.get(0))?;
    Ok(n > 0)
}

/// Erstellt den Keystore-Eintrag (frischer Master-Key, mit Passwort gewrapped).
/// Fails, wenn bereits initialisiert — Caller prueft via is_initialized.
pub fn initialize(conn: &Connection, password: &str) -> Result<MasterKey, ShadowError> {
    if is_initialized(conn)? {
        return Err(ShadowError::Forbidden(
            "keystore already initialized".into()));
    }
    let (key, salt, params) = MasterKey::derive(password)?;
    let wrapped = key.wrap_with_password(password, &salt)?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    conn.execute(
        "INSERT INTO key_material (id, kdf, kdf_salt, kdf_params, wrapped_key, created_at)
         VALUES (1, 'argon2id', ?1, ?2, ?3, ?4)",
        rusqlite::params![
            salt.as_slice(),
            serde_json::to_string(&params)?,
            wrapped,
            now,
        ],
    )?;
    Ok(key)
}

/// Oeffnet den Keystore mit dem Passwort.
pub fn unlock(conn: &Connection, password: &str) -> Result<MasterKey, ShadowError> {
    let row = conn
        .query_row(
            "SELECT kdf_salt, wrapped_key FROM key_material WHERE id = 1",
            [],
            |r| Ok((r.get::<_, Vec<u8>>(0)?, r.get::<_, Vec<u8>>(1)?)),
        )
        .optional()?
        .ok_or_else(|| ShadowError::NotFound("keystore not initialized".into()))?;
    let salt: [u8; 16] = row.0
        .try_into()
        .map_err(|_| ShadowError::Crypto("bad kdf_salt length".into()))?;
    MasterKey::open(password, &salt, &row.1)
}

/// KDF-Parameter des Keystores (fuer doctor/Anzeige).
pub fn kdf_params(conn: &Connection) -> Result<Option<KdfParams>, ShadowError> {
    let s: Option<String> = conn
        .query_row(
            "SELECT kdf_params FROM key_material WHERE id = 1",
            [],
            |r| r.get(0),
        )
        .optional()?;
    match s {
        Some(json) => Ok(Some(serde_json::from_str(&json)?)),
        None => Ok(None),
    }
}
