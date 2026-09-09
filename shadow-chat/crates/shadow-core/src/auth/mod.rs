//! User-Accounts: Login, First-Login-Bootstrap, Kill-Switch.
//!
//! Passwörter werden als Argon2id-PHC-String gespeichert (gleiche
//! Parameter wie der Keystore: 19 MiB, t=2, p=1). Der Kill-Switch
//! ist optional: Wird er als Passwort eingegeben, werden alle Sessions
//! und Nachrichten des Accounts gelöscht (Notfall-Löschung) und der
//! Zugriff verweigert. Jedes Event landet im Audit-Log.

use argon2::{
    password_hash::{rand_core::OsRng, PasswordHasher, PasswordVerifier, SaltString},
    Argon2,
};
use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use zeroize::Zeroize;
use zeroize::Zeroizing;

use crate::error::ShadowError;
use crate::session::audit;

/// Default-Account für den First-Login (wird nach Einrichtung gelöscht).
pub const DEFAULT_ADMIN_ID: &str = "default-admin";
pub const DEFAULT_ADMIN_NAME: &str = "Admin";
pub const DEFAULT_ADMIN_PASSWORD: &str = "1234";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: String,
    pub name: String,
    pub role: String, // 'admin' | 'user' | 'test'
    pub email: Option<String>,
    pub must_change_password: bool,
    pub created_at: i64,
    pub expires_at: Option<i64>, // Unix-Sekunden; nur 'test'-Rolle
}

pub enum AuthOutcome {
    Ok(User),
    /// Passwort falsch oder User unbekannt.
    InvalidCredentials,
    /// Kill-Switch ausgelöst: Account-Daten wurden gelöscht.
    KillSwitchTriggered,
    /// Account existiert, muss aber erst Passwort ändern (First-Login).
    MustChangePassword(User),
}

pub struct UserStore<'a> {
    conn: &'a Connection,
}

fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

impl<'a> UserStore<'a> {
    pub fn new(conn: &'a Connection) -> Self {
        Self { conn }
    }

    // ── Passwort-Hashes (Argon2id-PHC) ─────────────────────────

    fn hash_secret(secret: &str) -> Result<String, ShadowError> {
        let salt = SaltString::generate(&mut OsRng);
        let argon2 = Argon2::default();
        argon2
            .hash_password(secret.as_bytes(), &salt)
            .map(|h| h.to_string())
            .map_err(|e| ShadowError::Crypto(format!("argon2 hash: {e}")))
    }

    fn verify_secret(phc: &str, secret: &str) -> Result<bool, ShadowError> {
        let parsed = argon2::PasswordHash::new(phc)
            .map_err(|e| ShadowError::Crypto(format!("phc parse: {e}")))?;
        let mut pw = Zeroizing::new(secret.to_string());
        let ok = Argon2::default()
            .verify_password(pw.as_bytes(), &parsed)
            .is_ok();
        pw.zeroize();
        Ok(ok)
    }

    // ── First-Login-Bootstrap ──────────────────────────────────

    /// True, wenn noch kein Account mit Passwort existiert.
    pub fn is_first_start(&self) -> Result<bool, ShadowError> {
        let n: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM user WHERE password_hash IS NOT NULL",
            [],
            |r| r.get(0),
        )?;
        Ok(n == 0)
    }

    /// Legt den Default-Admin (Admin/1234) an. Nur für First-Login.
    pub fn bootstrap_default_admin(&self) -> Result<(), ShadowError> {
        if !self.is_first_start()? {
            return Err(ShadowError::Forbidden(
                "bootstrap nur bei First-Login erlaubt".into(),
            ));
        }
        let hash = Self::hash_secret(DEFAULT_ADMIN_PASSWORD)?;
        self.conn.execute(
            "INSERT INTO user
                (id, name, role, created_at, settings_json,
                 password_hash, must_change_password)
             VALUES (?1,?2,'admin',?3,'{}',?4,1)",
            rusqlite::params![DEFAULT_ADMIN_ID, DEFAULT_ADMIN_NAME, now_unix(), hash],
        )?;
        audit(self.conn, "system", "auth.bootstrap_default_admin", DEFAULT_ADMIN_ID, serde_json::json!({}))?;
        Ok(())
    }

    /// Prüft Default-Admin-Zugang (First-Login-Schritt 1).
    pub fn verify_default_admin(&self, password: &str) -> Result<bool, ShadowError> {
        let row = self
            .conn
            .query_row(
                "SELECT password_hash FROM user WHERE id = ?1",
                [DEFAULT_ADMIN_ID],
                |r| r.get::<_, Option<String>>(0),
            )
            .optional()?;
        match row.flatten() {
            Some(phc) => Self::verify_secret(&phc, password),
            None => Ok(false),
        }
    }

    // ── Account-Verwaltung ─────────────────────────────────────

    /// Erstellt einen neuen Account. `actor` = ausführender Admin (Audit).
    /// Für Rolle 'test' kann ein Ablaufdatum (Unix-Sekunden) gesetzt werden;
    /// nach Ablauf wird der Account bei jedem Login deaktiviert.
    pub fn create_user(
        &self,
        actor: &str,
        username: &str,
        password: &str,
        role: &str,
        email: Option<&str>,
        expires_at: Option<i64>,
    ) -> Result<User, ShadowError> {
        if role != "admin" && role != "user" && role != "test" {
            return Err(ShadowError::Forbidden(format!("ungültige Rolle: {role}")));
        }
        if username.trim().is_empty() || password.len() < 4 {
            return Err(ShadowError::Forbidden(
                "Username leer oder Passwort kürzer als 4 Zeichen".into(),
            ));
        }
        if role == "admin" && expires_at.is_some() {
            return Err(ShadowError::Forbidden(
                "Ablaufdatum nur für Test-User erlaubt".into(),
            ));
        }
        let id = uuid::Uuid::new_v4().to_string();
        let hash = Self::hash_secret(password)?;
        self.conn.execute(
            "INSERT INTO user
                (id, name, role, created_at, settings_json,
                 password_hash, email, expires_at)
             VALUES (?1,?2,?3,?4,'{}',?5,?6,?7)",
            rusqlite::params![id, username, role, now_unix(), hash, email, expires_at],
        )?;
        audit(
            self.conn,
            actor,
            "user.create",
            &id,
            serde_json::json!({"name": username, "role": role, "expires_at": expires_at}),
        )?;
        self.get_user(&id)?.ok_or_else(|| ShadowError::NotFound(id))
    }

    /// First-Login-Schritt 2: Ersetzt den Default-Admin durch den neuen Admin.
    /// `kill_switch` ist optional und wird als SHA-256-Hash abgelegt.
    pub fn create_admin_replace_default(
        &self,
        username: &str,
        password: &str,
        email: Option<&str>,
        kill_switch: Option<&str>,
    ) -> Result<User, ShadowError> {
        if !self.verify_default_admin(DEFAULT_ADMIN_PASSWORD)? {
            return Err(ShadowError::Forbidden(
                "Default-Admin nicht aktiv — ungültiger Aufruf".into(),
            ));
        }
        let ks_hash = kill_switch
            .filter(|k| !k.is_empty())
            .map(crate::crypto::sha256_bytes_from_str);
        let user = self.create_user("system", username, password, "admin", email, None)?;
        if let Some(h) = ks_hash {
            self.conn.execute(
                "UPDATE user SET kill_switch_hash = ?2 WHERE id = ?1",
                rusqlite::params![user.id, h],
            )?;
        }
        // Default-Admin entfernen — First-Login abgeschlossen.
        self.conn.execute(
            "DELETE FROM user WHERE id = ?1",
            [DEFAULT_ADMIN_ID],
        )?;
        audit(
            self.conn,
            "system",
            "auth.default_admin_replaced",
            &user.id,
            serde_json::json!({"kill_switch_set": kill_switch.is_some()}),
        )?;
        Ok(user)
    }

    pub fn get_user(&self, user_id: &str) -> Result<Option<User>, ShadowError> {
        let row = self
            .conn
            .query_row(
                "SELECT id, name, role, email, must_change_password, created_at, expires_at
                 FROM user WHERE id = ?1",
                [user_id],
                |r| {
                    Ok(User {
                        id: r.get(0)?,
                        name: r.get(1)?,
                        role: r.get(2)?,
                        email: r.get(3)?,
                        must_change_password: r.get::<_, i64>(4)? != 0,
                        created_at: r.get(5)?,
                        expires_at: r.get(6)?,
                    })
                },
            )
            .optional()?;
        Ok(row)
    }

    pub fn find_by_name(&self, username: &str) -> Result<Option<User>, ShadowError> {
        let row = self
            .conn
            .query_row(
                "SELECT id, name, role, email, must_change_password, created_at, expires_at
                 FROM user WHERE name = ?1",
                [username],
                |r| {
                    Ok(User {
                        id: r.get(0)?,
                        name: r.get(1)?,
                        role: r.get(2)?,
                        email: r.get(3)?,
                        must_change_password: r.get::<_, i64>(4)? != 0,
                        created_at: r.get(5)?,
                        expires_at: r.get(6)?,
                    })
                },
            )
            .optional()?;
        Ok(row)
    }

    pub fn list_users(&self) -> Result<Vec<User>, ShadowError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, name, role, email, must_change_password, created_at, expires_at
             FROM user ORDER BY created_at",
        )?;
        let rows = stmt.query_map([], |r| {
            Ok(User {
                id: r.get(0)?,
                name: r.get(1)?,
                role: r.get(2)?,
                email: r.get(3)?,
                must_change_password: r.get::<_, i64>(4)? != 0,
                created_at: r.get(5)?,
                expires_at: r.get(6)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn delete_user(&self, actor: &str, user_id: &str) -> Result<(), ShadowError> {
        // Sessions + Nachrichten des Users mit entfernen.
        let tx = self.conn.unchecked_transaction()?;
        tx.execute(
            "DELETE FROM message WHERE session_id IN
                (SELECT id FROM session WHERE user_id = ?1)",
            [user_id],
        )?;
        tx.execute("DELETE FROM session WHERE user_id = ?1", [user_id])?;
        tx.execute("DELETE FROM user WHERE id = ?1", [user_id])?;
        tx.commit()?;
        audit(
            self.conn,
            actor,
            "user.delete",
            user_id,
            serde_json::json!({}),
        )?;
        Ok(())
    }

    /// Setzt ein neues Passwort (Passwort-Change nach First-Login).
    pub fn set_password(&self, actor: &str, user_id: &str, new_password: &str) -> Result<(), ShadowError> {
        let hash = Self::hash_secret(new_password)?;
        self.conn.execute(
            "UPDATE user SET password_hash = ?2, must_change_password = 0 WHERE id = ?1",
            rusqlite::params![user_id, hash],
        )?;
        audit(self.conn, actor, "user.password_change", user_id, serde_json::json!({}))?;
        Ok(())
    }

    /// Deaktiviert alle Test-User, deren Ablaufdatum überschritten ist.
    /// 'Deaktivierung' = Sessions (und damit Chat-Zugriff) werden gelöscht,
    /// der Account bleibt zur Nachvollziehbarkeit erhalten. Liefert die
    /// IDs der deaktivierten Accounts. Sollte vor jedem Login aufgerufen
    /// werden (automatische Deaktivierung).
    pub fn deactivate_expired_test_users(&self, actor: &str) -> Result<Vec<String>, ShadowError> {
        let now = now_unix();
        let mut stmt = self.conn.prepare(
            "SELECT id FROM user WHERE role = 'test' AND expires_at IS NOT NULL AND expires_at < ?1",
        )?;
        let ids: Vec<String> = stmt
            .query_map([now], |r| r.get(0))?
            .collect::<Result<Vec<_>, _>>()?;
        drop(stmt);
        for id in &ids {
            let tx = self.conn.unchecked_transaction()?;
            tx.execute(
                "DELETE FROM message WHERE session_id IN
                    (SELECT id FROM session WHERE user_id = ?1)",
                [id],
            )?;
            tx.execute("DELETE FROM session WHERE user_id = ?1", [id])?;
            tx.commit()?;
            audit(self.conn, actor, "user.test_expired_deactivated", id, serde_json::json!({"now": now}))?;
        }
        Ok(ids)
    }

    // ── Login ──────────────────────────────────────────────────

    /// Prüft Zugangsdaten. Berücksichtigt Kill-Switch,
    /// must_change_password und Ablaufdatum (Test-User). Loggt
    /// Erfolg/Misserfolg ins Audit-Log.
    pub fn verify_account(&self, username: &str, password: &str) -> Result<AuthOutcome, ShadowError> {
        // Automatische Deaktivierung abgelaufener Test-User vorab ausführen.
        let _ = self.deactivate_expired_test_users("system")?;

        let user = match self.find_by_name(username)? {
            Some(u) => u,
            None => {
                audit(self.conn, "anonymous", "auth.login.failed", username, serde_json::json!({"reason":"unknown_user"}))?;
                return Ok(AuthOutcome::InvalidCredentials);
            }
        };

        // Test-User mit erreichtem Ablaufdatum: Login verweigern.
        if user.role == "test" {
            if let Some(exp) = user.expires_at {
                if exp <= now_unix() {
                    audit(self.conn, &user.id, "auth.login.expired", username, serde_json::json!({}))?;
                    return Ok(AuthOutcome::InvalidCredentials);
                }
            }
        }

        // 1) Kill-Switch? → Daten des Accounts löschen, Zugriff verweigern.
        let ks: Option<String> = self.conn.query_row(
            "SELECT kill_switch_hash FROM user WHERE id = ?1",
            [&user.id],
            |r| r.get(0),
        ).optional()?.flatten();
        if let Some(ks_hash) = ks {
            if crate::crypto::sha256_bytes_from_str(password) == ks_hash {
                self.delete_user(&user.id, &user.id)?; // Selbstlöschung
                audit(self.conn, &user.id, "auth.kill_switch", &user.id, serde_json::json!({}))?;
                return Ok(AuthOutcome::KillSwitchTriggered);
            }
        }

        // 2) Normales Passwort?
        let phc: Option<String> = self.conn.query_row(
            "SELECT password_hash FROM user WHERE id = ?1",
            [&user.id],
            |r| r.get(0),
        ).optional()?.flatten();
        let ok = match phc {
            Some(h) => Self::verify_secret(&h, password)?,
            None => false,
        };
        if !ok {
            audit(self.conn, &user.id, "auth.login.failed", username, serde_json::json!({"reason":"wrong_password"}))?;
            return Ok(AuthOutcome::InvalidCredentials);
        }

        audit(self.conn, &user.id, "auth.login", username, serde_json::json!({}))?;
        if user.must_change_password {
            return Ok(AuthOutcome::MustChangePassword(user));
        }
        Ok(AuthOutcome::Ok(user))
    }
}

// ── Tests ────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_store() -> Connection {
        let conn = Connection::open_in_memory().unwrap();
        // schema V1 enthält bereits die v2-Spalten (password_hash, email,
        // must_change_password, kill_switch_hash).
        conn.execute_batch(crate::store::schema::V1).unwrap();
        conn
    }

    #[test]
    fn first_login_flow() {
        let conn = mem_store();
        let us = UserStore::new(&conn);
        assert!(us.is_first_start().unwrap());

        us.bootstrap_default_admin().unwrap();
        assert!(us.verify_default_admin("1234").unwrap());
        assert!(!us.verify_default_admin("falsch").unwrap());

        // Kein normaler Login mit Default-Admin möglich (must_change_password):
        match us.verify_account("Admin", "1234").unwrap() {
            AuthOutcome::MustChangePassword(_) => {}
            _ => panic!("erwartet MustChangePassword"),
        }

        let admin = us.create_admin_replace_default(
            "root", "geheim", Some("root@example.org"), Some("abracadabra"),
        ).unwrap();
        assert_eq!(admin.role, "admin");
        assert!(us.get_user(DEFAULT_ADMIN_ID).unwrap().is_none());
        assert!(!us.is_first_start().unwrap());

        // Normaler Login:
        match us.verify_account("root", "geheim").unwrap() {
            AuthOutcome::Ok(u) => assert_eq!(u.name, "root"),
            _ => panic!("erwartet Ok"),
        }
        assert!(matches!(
            us.verify_account("root", "falsch").unwrap(),
            AuthOutcome::InvalidCredentials
        ));

        // Kill-Switch löscht den Account:
        assert!(matches!(
            us.verify_account("root", "abracadabra").unwrap(),
            AuthOutcome::KillSwitchTriggered
        ));
        assert!(us.find_by_name("root").unwrap().is_none());
    }

    #[test]
    fn create_and_delete_user() {
        let conn = mem_store();
        let us = UserStore::new(&conn);
        us.bootstrap_default_admin().unwrap();
        us.create_admin_replace_default("a", "aaaa", None, None).unwrap();
        let u = us.create_user("a", "bob", "bobpass", "user", None, None).unwrap();
        assert_eq!(us.list_users().unwrap().len(), 2);
        us.delete_user("a", &u.id).unwrap();
        assert_eq!(us.list_users().unwrap().len(), 1);
    }
}
