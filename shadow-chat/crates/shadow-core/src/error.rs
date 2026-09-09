use thiserror::Error;

/// Normierte Fehlerklassen für Adapter und Core.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum AdapterError {
    #[error("authentication failed")]
    Auth,
    #[error("rate limited")]
    RateLimited,
    #[error("context window exceeded")]
    ContextOverflow,
    #[error("model unavailable: {0}")]
    Unavailable(String),
    #[error("cancelled")]
    Cancelled,
    #[error("internal adapter error: {0}")]
    Internal(String),
}

/// Warum eine Generierung endete.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum FinishReason {
    Stop,
    Length,
    Cancelled,
    Error,
}

#[derive(Debug, Error)]
pub enum ShadowError {
    #[error("store error: {0}")]
    Store(#[from] rusqlite::Error),
    #[error("crypto error: {0}")]
    Crypto(String),
    #[error("adapter error: {0}")]
    Adapter(#[from] AdapterError),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("serialization error: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("forbidden: {0}")]
    Forbidden(String),
}
