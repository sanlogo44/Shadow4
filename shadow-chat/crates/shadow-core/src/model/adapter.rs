use serde::{Deserialize, Serialize};
use crate::error::{AdapterError, FinishReason};
use super::capabilities::ModelCapabilities;

pub type EventSink = Box<dyn FnMut(StreamEvent) + Send>;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenParams {
    pub temperature: f32,
    pub top_p: f32,
    pub max_tokens: u32,
    pub seed: Option<u64>,
}

impl Default for GenParams {
    fn default() -> Self {
        Self { temperature: 0.7, top_p: 0.95, max_tokens: 1024, seed: None }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenConstraints {
    /// Hartes Token-Budget für diese Anfrage.
    pub max_cost_tokens: u32,
    /// Deadline in Millisekunden; Adapter muss danach abbrechen.
    pub deadline_ms: u64,
    pub stop_sequences: Vec<String>,
}

impl Default for GenConstraints {
    fn default() -> Self {
        Self {
            max_cost_tokens: 4096,
            deadline_ms: 120_000,
            stop_sequences: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessageInput {
    pub role: String, // "system" | "user" | "assistant"
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenerateRequest {
    pub session_id: String,
    pub messages: Vec<MessageInput>,
    pub params: GenParams,
    pub constraints: GenConstraints,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenerateResult {
    pub tokens_in: u32,
    pub tokens_out: u32,
    pub latency_ms: u64,
    pub finish_reason: FinishReason,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum StreamEvent {
    Token { text: String, index: u32 },
    Usage { tokens_in: u32, tokens_out: u32 },
    Finish { reason: FinishReason },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HealthStatus {
    Ok,
    Degraded,
    Down,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ModelConfig {
    pub model_id: String,
    /// Adapter-spezifisch; Core validiert nur Existenz, nicht Inhalt.
    pub adapter_config: serde_json::Value,
    /// Erwarteter SHA-256 der Modell-Datei(en) für Integritätsprüfung.
    pub expected_sha256: Option<String>,
}

/// Der einzige Kontaktpunkt zwischen Core und Modell.
///
/// Regeln:
/// - Adapter erhält KEINE DB-Handles, KEINE User-Objekte, KEINE Pfade
///   außerhalb von `ModelConfig`.
/// - Abbruch ist Pflicht: `stream` muss spätestens bei Deadline beenden
///   und `Finish { reason: Cancelled }` liefern.
pub trait ModelAdapter: Send {
    /// Statische Fähigkeiten, ohne das Modell zu laden.
    fn capabilities(&self) -> ModelCapabilities;

    fn load(&mut self, cfg: &ModelConfig) -> Result<(), AdapterError>;
    fn unload(&mut self) -> Result<(), AdapterError>;
    fn health(&mut self) -> HealthStatus;

    /// Streaming-Generierung. `events` wird synchron aufgerufen.
    fn stream(
        &mut self,
        req: GenerateRequest,
        events: EventSink,
    ) -> Result<GenerateResult, AdapterError>;
}
