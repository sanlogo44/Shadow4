use rusqlite::{Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use crate::error::ShadowError;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelEntry {
    pub model_id: String,
    pub adapter_type: String, // z.B. "stub", "python-openweight"
    pub display_name: String,
    pub capabilities_json: serde_json::Value,
    pub context_window: u32,
    pub enabled: bool,
    pub export_allowed: bool,
}

impl ModelEntry {
    pub fn new(model_id: &str, adapter_type: &str, display_name: &str) -> Self {
        Self {
            model_id: model_id.to_string(),
            adapter_type: adapter_type.to_string(),
            display_name: display_name.to_string(),
            capabilities_json: serde_json::json!({}),
            context_window: 8192,
            enabled: true,
            export_allowed: false,
        }
    }
}

/// SQLite-gestützte Modell-Registry.
pub struct ModelRegistry<'a> {
    conn: &'a Connection,
}

impl<'a> ModelRegistry<'a> {
    pub fn new(conn: &'a Connection) -> Self {
        Self { conn }
    }

    pub fn upsert(&self, entry: &ModelEntry) -> Result<(), ShadowError> {
        self.conn.execute(
            "INSERT INTO model_entry
                (model_id, adapter_type, display_name, capabilities_json,
                 context_window, enabled, export_allowed)
             VALUES (?1,?2,?3,?4,?5,?6,?7)
             ON CONFLICT(model_id) DO UPDATE SET
                adapter_type=excluded.adapter_type,
                display_name=excluded.display_name,
                capabilities_json=excluded.capabilities_json,
                context_window=excluded.context_window,
                enabled=excluded.enabled,
                export_allowed=excluded.export_allowed",
            rusqlite::params![
                entry.model_id,
                entry.adapter_type,
                entry.display_name,
                entry.capabilities_json.to_string(),
                entry.context_window,
                entry.enabled as i32,
                entry.export_allowed as i32,
            ],
        )?;
        Ok(())
    }

    pub fn get(&self, model_id: &str) -> Result<Option<ModelEntry>, ShadowError> {
        let row = self.conn.query_row(
            "SELECT model_id, adapter_type, display_name, capabilities_json,
                    context_window, enabled, export_allowed
             FROM model_entry WHERE model_id = ?1",
            [model_id],
            |r| {
                Ok(ModelEntry {
                    model_id: r.get(0)?,
                    adapter_type: r.get(1)?,
                    display_name: r.get(2)?,
                    capabilities_json: serde_json::from_str(&r.get::<_, String>(3)?)
                        .unwrap_or(serde_json::json!({})),
                    context_window: r.get::<_, u32>(4)?,
                    enabled: r.get::<_, i32>(5)? != 0,
                    export_allowed: r.get::<_, i32>(6)? != 0,
                })
            },
        ).optional()?;
        Ok(row)
    }

    pub fn list_enabled(&self) -> Result<Vec<ModelEntry>, ShadowError> {
        let mut stmt = self.conn.prepare(
            "SELECT model_id, adapter_type, display_name, capabilities_json,
                    context_window, enabled, export_allowed
             FROM model_entry WHERE enabled = 1 ORDER BY model_id")?;
        let rows = stmt.query_map([], |r| {
            Ok(ModelEntry {
                model_id: r.get(0)?,
                adapter_type: r.get(1)?,
                display_name: r.get(2)?,
                capabilities_json: serde_json::from_str(&r.get::<_, String>(3)?)
                    .unwrap_or(serde_json::json!({})),
                context_window: r.get::<_, u32>(4)?,
                enabled: r.get::<_, i32>(5)? != 0,
                export_allowed: r.get::<_, i32>(6)? != 0,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }
}
