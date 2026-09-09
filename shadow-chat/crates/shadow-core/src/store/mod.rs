use rusqlite::Connection;
use crate::error::ShadowError;

pub mod schema {
    pub const V1: &str = include_str!("schema.sql");
}

/// Öffnet (oder erstellt) den Shadow-Store und führt Migrationen aus.
pub fn open(path: &std::path::Path) -> Result<Connection, ShadowError> {
    let conn = Connection::open(path)?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    migrate(&conn)?;
    Ok(conn)
}

fn migrate(conn: &Connection) -> Result<(), ShadowError> {
    use rusqlite::OptionalExtension;
    // schema_meta vorab sicherstellen, damit der Versions-Lesezugriff bei
    // einer frischen Datenbank nicht fehlschlägt.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)",
        [],
    )?;
    let version: i64 = conn.query_row(
        "SELECT version FROM schema_meta LIMIT 1",
        [],
        |r| r.get(0),
    ).optional()?.unwrap_or(0);

    if version < 1 {
        conn.execute_batch(schema::V1)?;
    }
    if version < 2 {
        migrate_v2(conn)?;
    }
    if version < 3 {
        migrate_v3(conn)?;
    }
    Ok(())
}

/// Schema v2: User-Accounts bekommen Passwort-Hashes, E-Mail,
/// Pflicht-Passwort-Change (First-Login) und optionalen Kill-Switch.
/// `password_hash IS NULL` = Account ohne Login (Legacy, z. B. local-admin).
fn migrate_v2(conn: &Connection) -> Result<(), ShadowError> {
    let has_pw: i64 = conn.query_row(
        "SELECT COUNT(*) FROM pragma_table_info('user') WHERE name = 'password_hash'",
        [],
        |r| r.get(0),
    )?;
    if has_pw == 0 {
        conn.execute_batch(
            "ALTER TABLE user ADD COLUMN password_hash TEXT;
             ALTER TABLE user ADD COLUMN email TEXT;
             ALTER TABLE user ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0;
             ALTER TABLE user ADD COLUMN kill_switch_hash TEXT;",
        )?;
    }
    conn.execute("UPDATE schema_meta SET version = 2", [])?;
    Ok(())
}

/// Schema v3: Rolle 'test' (Test-User mit Ablaufdatum) + expires_at-Spalte.
/// SQLite kann CHECK-Constraints nicht per ALTER ändern → Tabelle wird
/// neu erstellt, Daten übernommen und die alte Tabelle ersetzt.
fn migrate_v3(conn: &Connection) -> Result<(), ShadowError> {
    let needs_col: i64 = conn.query_row(
        "SELECT COUNT(*) FROM pragma_table_info('user') WHERE name = 'expires_at'",
        [],
        |r| r.get(0),
    )?;
    if needs_col == 0 {
        // Tabelle mit erweitertem CHECK + neuer Spalte neu aufbauen.
        conn.execute_batch(
            "CREATE TABLE user_v3 (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                role          TEXT NOT NULL CHECK (role IN ('admin','user','test')),
                created_at    INTEGER NOT NULL,
                settings_json TEXT NOT NULL DEFAULT '{}',
                password_hash TEXT,
                email         TEXT,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                kill_switch_hash TEXT,
                expires_at    INTEGER
             );
             INSERT INTO user_v3 (id, name, role, created_at, settings_json,
                                  password_hash, email, must_change_password,
                                  kill_switch_hash, expires_at)
             SELECT id, name, role, created_at, settings_json,
                    password_hash, email, must_change_password,
                    kill_switch_hash, NULL
             FROM user;
             DROP TABLE user;
             ALTER TABLE user_v3 RENAME TO user;",
        )?;
    }
    conn.execute("UPDATE schema_meta SET version = 3", [])?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migration_v1_to_v2() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(schema::V1).unwrap();
        conn.execute("UPDATE schema_meta SET version = 1", []).unwrap();
        migrate_v2(&conn).unwrap();
        let v: i64 = conn.query_row("SELECT version FROM schema_meta", [], |r| r.get(0)).unwrap();
        assert_eq!(v, 2);
        // Idempotent:
        migrate_v2(&conn).unwrap();
    }
}
