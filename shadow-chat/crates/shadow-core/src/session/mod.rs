use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use crate::crypto::MasterKey;
use crate::error::ShadowError;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub id: String,
    pub session_id: String,
    pub role: String,
    pub content: String,
    pub finish_reason: Option<String>,
    pub created_at: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMeta {
    pub id: String,
    pub user_id: String,
    pub title: String,
    pub model_id: String,
    pub created_at: i64,
    pub updated_at: i64,
}

pub struct SessionStore<'a> {
    conn: &'a Connection,
}

fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

impl<'a> SessionStore<'a> {
    pub fn new(conn: &'a Connection) -> Self {
        Self { conn }
    }

    pub fn append_message(
        &self,
        key: &MasterKey,
        session_id: &str,
        role: &str,
        content: &str,
        finish_reason: Option<&str>,
    ) -> Result<String, ShadowError> {
        let id = uuid::Uuid::new_v4().to_string();
        let sealed = key.seal(content.as_bytes())?;
        let now = now_unix();
        let tx = self.conn.unchecked_transaction()?;
        tx.execute(
            "INSERT INTO message
                (id, session_id, role, content_enc, content_plain,
                 finish_reason, created_at)
             VALUES (?1,?2,?3,?4,0,?5,?6)",
            rusqlite::params![id, session_id, role, sealed, finish_reason, now],
        )?;
        tx.execute(
            "UPDATE session SET updated_at = ?2 WHERE id = ?1",
            rusqlite::params![session_id, now],
        )?;
        tx.commit()?;
        Ok(id)
    }

    pub fn messages(
        &self,
        key: &MasterKey,
        session_id: &str,
    ) -> Result<Vec<Message>, ShadowError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, session_id, role, content_enc, finish_reason, created_at
             FROM message WHERE session_id = ?1 ORDER BY created_at")?;
        let rows = stmt.query_map([session_id], |r| {
            let sealed: Vec<u8> = r.get(3)?;
            let bytes = key.open_sealed(&sealed)
                .map_err(|e| rusqlite::Error::ToSqlConversionFailure(Box::new(e)))?;
            let content = String::from_utf8(bytes)
                .map_err(|e| rusqlite::Error::ToSqlConversionFailure(Box::new(e)))?;
            Ok(Message {
                id: r.get(0)?,
                session_id: r.get(1)?,
                role: r.get(2)?,
                content,
                finish_reason: r.get(4)?,
                created_at: r.get(5)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn create_session(
        &self,
        user_id: &str,
        model_id: &str,
        title: &str,
    ) -> Result<String, ShadowError> {
        let id = uuid::Uuid::new_v4().to_string();
        let now = now_unix();
        self.conn.execute(
            "INSERT INTO session (id, user_id, title, model_id, created_at, updated_at)
             VALUES (?1,?2,?3,?4,?5,?5)",
            rusqlite::params![id, user_id, model_id, title, now],
        )?;
        Ok(id)
    }

    /// Löscht eine Session inkl. aller Nachrichten (harte Löschung).
    /// Der Aufrufer ist für die Berechtigungsprüfung verantwortlich.
    pub fn delete_session(&self, session_id: &str) -> Result<(), ShadowError> {
        let tx = self.conn.unchecked_transaction()?;
        tx.execute("DELETE FROM message WHERE session_id = ?1", [session_id])?;
        tx.execute("DELETE FROM session WHERE id = ?1", [session_id])?;
        tx.commit()?;
        Ok(())
    }

    /// Fasst zwei Sessions zu einer neuen zusammen. Die Nachrichten werden
    /// zeitlich sortiert übernommen (content_enc bleibt gültig, da derselbe
    /// Master-Key). Die Quell-Sessions werden archiviert, nicht gelöscht.
    pub fn merge_sessions(
        &self,
        user_id: &str,
        chat1: &str,
        chat2: &str,
        new_title: &str,
    ) -> Result<String, ShadowError> {
        if chat1 == chat2 {
            return Err(ShadowError::Forbidden(
                "kann Session nicht mit sich selbst mergen".into(),
            ));
        }
        let m1 = self.get_session(chat1)?.ok_or_else(|| ShadowError::NotFound(chat1.into()))?;
        let m2 = self.get_session(chat2)?.ok_or_else(|| ShadowError::NotFound(chat2.into()))?;
        if m1.user_id != user_id || m2.user_id != user_id {
            return Err(ShadowError::Forbidden(
                "merge nur für eigene Sessions erlaubt".into(),
            ));
        }
        let new_id = self.create_session(user_id, &m1.model_id, new_title)?;
        let now = now_unix();

        // Nachrichten beider Sessions zeitlich sortiert in die neue kopieren.
        // content_enc kann direkt übernommen werden (gleicher Master-Key),
        // bekommt aber neue IDs und das neue session_id.
        let mut stmt = self.conn.prepare(
            "SELECT role, content_enc, content_plain, token_count_in, token_count_out,
                    latency_ms, finish_reason, created_at
             FROM message WHERE session_id IN (?1, ?2) ORDER BY created_at")?;
        let rows = stmt.query_map([chat1, chat2], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Vec<u8>>(1)?,
                r.get::<_, i64>(2)?,
                r.get::<_, i64>(3)?,
                r.get::<_, i64>(4)?,
                r.get::<_, i64>(5)?,
                r.get::<_, Option<String>>(6)?,
                r.get::<_, i64>(7)?,
            ))
        })?;
        let copied: Vec<_> = rows.collect::<Result<_, _>>()?;
        drop(stmt);

        let tx = self.conn.unchecked_transaction()?;
        for (role, content_enc, plain, tin, tout, latency, finish, created) in copied {
            tx.execute(
                "INSERT INTO message
                    (id, session_id, role, content_enc, content_plain,
                     token_count_in, token_count_out, latency_ms,
                     finish_reason, created_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10)",
                rusqlite::params![
                    uuid::Uuid::new_v4().to_string(), new_id, role, content_enc,
                    plain, tin, tout, latency, finish, created,
                ],
            )?;
        }
        tx.execute(
            "UPDATE session SET archived = 1, updated_at = ?3 WHERE id IN (?1, ?2)",
            rusqlite::params![chat1, chat2, now],
        )?;
        tx.commit()?;
        Ok(new_id)
    }

    pub fn rename_session(&self, session_id: &str, title: &str) -> Result<(), ShadowError> {
        self.conn.execute(
            "UPDATE session SET title = ?2, updated_at = ?3 WHERE id = ?1",
            rusqlite::params![session_id, title, now_unix()],
        )?;
        Ok(())
    }

    pub fn get_session(&self, session_id: &str) -> Result<Option<SessionMeta>, ShadowError> {
        let row = self.conn.query_row(
            "SELECT id, user_id, title, model_id, created_at, updated_at
             FROM session WHERE id = ?1",
            [session_id],
            |r| Ok(SessionMeta {
                id: r.get(0)?,
                user_id: r.get(1)?,
                title: r.get(2)?,
                model_id: r.get(3)?,
                created_at: r.get(4)?,
                updated_at: r.get(5)?,
            }),
        ).optional()?;
        Ok(row)
    }

    pub fn list_sessions(&self, user_id: &str) -> Result<Vec<SessionMeta>, ShadowError> {
        let mut stmt = self.conn.prepare(
            "SELECT id, user_id, title, model_id, created_at, updated_at
             FROM session WHERE user_id = ?1 AND archived = 0
             ORDER BY updated_at DESC")?;
        let rows = stmt.query_map([user_id], |r| Ok(SessionMeta {
            id: r.get(0)?,
            user_id: r.get(1)?,
            title: r.get(2)?,
            model_id: r.get(3)?,
            created_at: r.get(4)?,
            updated_at: r.get(5)?,
        }))?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }
}

/// Schreibt ein Audit-Event (Admin-Aktionen: export, model.switch, ...).
pub fn audit(
    conn: &Connection,
    actor: &str,
    action: &str,
    target: &str,
    detail: serde_json::Value,
) -> Result<(), ShadowError> {
    conn.execute(
        "INSERT INTO audit_event (id, timestamp, actor, action, target, detail_json)
         VALUES (?1,?2,?3,?4,?5,?6)",
        rusqlite::params![
            uuid::Uuid::new_v4().to_string(),
            now_unix(),
            actor,
            action,
            target,
            detail.to_string(),
        ],
    )?;
    Ok(())
}
