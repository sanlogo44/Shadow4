//! Shadow Server – HTTP-API-Bibliothek zwischen Flutter-Oberfläche und Rust Core.
//!
//! Wird vom `shadow server`-CLI-Kommando aufgerufen und kann auch als
//! eigenständige Binary (`shadow-server`) laufen.

pub mod error;
pub mod routes;
pub mod state;

pub use state::AppState;

use std::net::SocketAddr;
use std::sync::Arc;

use shadow_core::model::ModelAdapter;
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;

/// Parst die CLI-Argumente (host, port, data-dir).
pub fn parse_args(args: &[String]) -> (String, u16, std::path::PathBuf) {
    let mut host = "127.0.0.1".to_string();
    let mut port: u16 = 8787;
    let mut data_dir = std::path::PathBuf::from("./shadow-data");
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--host" if i + 1 < args.len() => { host = args[i + 1].clone(); i += 2; }
            "--port" if i + 1 < args.len() => { port = args[i + 1].parse().unwrap_or(8787); i += 2; }
            "--data-dir" if i + 1 < args.len() => { data_dir = std::path::PathBuf::from(&args[i + 1]); i += 2; }
            _ => { i += 1; }
        }
    }
    (host, port, data_dir)
}

/// Startet den Server asynchron.
pub async fn run_async(args: Vec<String>) -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "shadow_server=info,tower_http=info".into()),
        )
        .init();

    let (host, port, data_dir) = parse_args(&args);
    let (conn, key) = state::open_store(&data_dir)?;

    // Default-Modell registrieren, falls keines vorhanden.
    let reg = shadow_core::model::ModelRegistry::new(&conn);
    let entry = shadow_core::model::ModelEntry::new("shadow-default", "stub", "Shadow Model");
    let _ = reg.upsert(&entry);

    let mut adapter = AppState::build_adapter();
    // Adapter mit dem Default-Modell laden (Stub: immer erfolgreich;
    // LLM-Engine: startet den Python-Prozess und wartet auf hello_ack).
    {
        let cfg = shadow_core::model::ModelConfig {
            model_id: "shadow-default".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        };
        if let Err(e) = adapter.load(&cfg) {
            tracing::warn!("Modell-Adapter konnte nicht geladen werden: {e}. Der Server läuft, Chat ist erst nach Laden verfügbar.");
        }
    }
    let state = Arc::new(AppState {
        conn: std::sync::Mutex::new(conn),
        key,
        tokens: std::sync::RwLock::new(std::collections::HashMap::new()),
        data_dir: data_dir.clone(),
        adapter: std::sync::Mutex::new(adapter),
    });

    let addr: SocketAddr = format!("{}:{}", host, port).parse()?;
    let router = routes::router(state)
        .layer(CorsLayer::very_permissive())
        .layer(TraceLayer::new_for_http());

    tracing::info!("Shadow Server lauscht auf http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, router).await?;
    Ok(())
}

/// Blockierender Einstieg (für das `shadow server`-CLI-Kommando).
pub fn run(args: Vec<String>) -> Result<(), Box<dyn std::error::Error>> {
    let rt = tokio::runtime::Runtime::new()?;
    rt.block_on(run_async(args))
}

/// Alias-Trait-Import, damit `dyn ModelAdapter` in Signaturen aufgelöst wird.
#[allow(unused_imports)]
use shadow_core::model::ModelAdapter as _ModelAdapterTrait;
