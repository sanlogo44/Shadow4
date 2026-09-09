//! Shadow Core – MVP-Skeleton
//!
//! Enthält: Adapter-Trait, Stub- und Python-Adapter, Modell-Registry,
//! Session-Store (SQLite), Keystore + Master-Key (Argon2id/AES-256-GCM),
//! SHA-256-Integritaetspruefung, User-Accounts (Login/First-Login/Kill-Switch),
//! User-Einstellungen (Theme/Sprache) und einen Modell-Benchmark.

pub mod auth;
pub mod bench;
pub mod crypto;
pub mod error;
pub mod model;
pub mod session;
pub mod settings;
pub mod store;

pub use auth::{AuthOutcome, User, UserStore, DEFAULT_ADMIN_NAME, DEFAULT_ADMIN_PASSWORD};
pub use bench::{run_benchmark, BenchResult};
pub use crypto::{
    is_initialized as keystore_is_initialized, keystore_initialize, keystore_unlock,
    sha256_bytes, sha256_file, MasterKey,
};
pub use error::{AdapterError, FinishReason, ShadowError};
pub use model::{GenerateRequest, GenerateResult, GenConstraints, GenParams,
                HealthStatus, ModelAdapter, ModelCapabilities, ModelConfig,
                ModelEntry, ModelRegistry, PythonAdapter, StubAdapter,
                StreamEvent};
