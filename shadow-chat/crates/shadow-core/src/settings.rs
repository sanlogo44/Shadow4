//! User-Einstellungen (settings_json-Spalte der user-Tabelle).
//! Keys: theme ("dark"|"light"|"system"), language ("de"|"en"),
//!       default_model (model_id).

use rusqlite::Connection;
use serde_json::Value;

use crate::error::ShadowError;
use crate::session::audit;

pub const THEMES: [&str; 3] = ["dark", "light", "system"];
pub const LANGUAGES: [&str; 2] = ["de", "en"];

pub fn get_settings(conn: &Connection, user_id: &str) -> Result<Value, ShadowError> {
    let s: String = conn.query_row(
        "SELECT settings_json FROM user WHERE id = ?1",
        [user_id],
        |r| r.get(0),
    )?;
    Ok(serde_json::from_str(&s)?)
}

/// Mergt `patch` in die bestehenden Einstellungen (shallow) und auditiert.
pub fn update_settings(
    conn: &Connection,
    actor: &str,
    user_id: &str,
    patch: Value,
) -> Result<Value, ShadowError> {
    let mut cur = get_settings(conn, user_id)?;
    if let (Some(cur), Some(patch)) = (cur.as_object_mut(), patch.as_object()) {
        for (k, v) in patch {
            cur.insert(k.clone(), v.clone());
        }
    }
    conn.execute(
        "UPDATE user SET settings_json = ?2 WHERE id = ?1",
        rusqlite::params![user_id, cur.to_string()],
    )?;
    audit(conn, actor, "config.change", user_id, patch)?;
    Ok(cur)
}

pub fn theme(conn: &Connection, user_id: &str) -> Result<String, ShadowError> {
    let s = get_settings(conn, user_id)?;
    Ok(s.get("theme").and_then(Value::as_str).unwrap_or("system").to_string())
}

pub fn default_model(conn: &Connection, user_id: &str) -> Result<Option<String>, ShadowError> {
    let s = get_settings(conn, user_id)?;
    Ok(s.get("default_model").and_then(Value::as_str).map(String::from))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::Connection;

    fn mem() -> Connection {
        let c = Connection::open_in_memory().unwrap();
        c.execute_batch(crate::store::schema::V1).unwrap();
        c.execute(
            "INSERT INTO user (id, name, role, created_at) VALUES ('u1','U','user',0)",
            [],
        ).unwrap();
        c
    }

    #[test]
    fn patch_merge_and_theme() {
        let c = mem();
        let cur = update_settings(&c, "u1", "u1",
            serde_json::json!({"theme": "dark", "language": "en"})).unwrap();
        assert_eq!(cur["theme"], "dark");
        // Zweiter Patch überschreibt nur einen Key:
        let cur = update_settings(&c, "u1", "u1",
            serde_json::json!({"theme": "light"})).unwrap();
        assert_eq!(cur["theme"], "light");
        assert_eq!(cur["language"], "en");
        assert_eq!(theme(&c, "u1").unwrap(), "light");
        // Default: "system"
        assert_eq!(theme(&c, "xxx-missing").unwrap_or_default().is_empty(), true);
    }
}
