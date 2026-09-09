//! Minimaler Benchmark: Latenz + Durchsatz eines Modell-Adapters.
//!
//! Ergebnisse landen als Audit-Event ('admin.benchmark') beim Aufrufer.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

use serde::Serialize;

use crate::error::ShadowError;
use crate::model::{
    GenConstraints, GenParams, GenerateRequest, MessageInput, ModelAdapter, StreamEvent,
};

#[derive(Debug, Clone, Serialize)]
pub struct BenchResult {
    pub model_id: String,
    pub runs: usize,
    pub prompt_tokens: usize,
    pub total_tokens: usize,
    pub avg_latency_ms: f64,
    pub tokens_per_sec: f64,
}

pub const DEFAULT_BENCH_PROMPT: &str =
    "Benchmark: Antworte mit genau einem kurzen Satz. Zeichenzaehler an.";

/// Führt `runs` Generierungen mit einem festen Prompt durch und misst
/// Gesamtlatenz sowie Token-Durchsatz (Token = Stream-Events).
pub fn run_benchmark(
    adapter: &mut dyn ModelAdapter,
    model_id: &str,
    runs: usize,
) -> Result<BenchResult, ShadowError> {
    if runs == 0 {
        return Err(ShadowError::Forbidden("runs muss >= 1 sein".into()));
    }
    let prompt_tokens = DEFAULT_BENCH_PROMPT.split_whitespace().count();
    let mut total_latency_ms = 0u128;
    let mut total_tokens = 0usize;

    for _ in 0..runs {
        let req = GenerateRequest {
            session_id: format!("bench-{}", uuid::Uuid::new_v4()),
            messages: vec![MessageInput {
                role: "user".into(),
                content: DEFAULT_BENCH_PROMPT.into(),
            }],
            params: GenParams::default(),
            constraints: GenConstraints::default(),
        };
        let counter = Arc::new(AtomicUsize::new(0));
        let inner = counter.clone();
        let t0 = Instant::now();
        adapter.stream(req, Box::new(move |ev| {
            if let StreamEvent::Token { .. } = ev {
                inner.fetch_add(1, Ordering::Relaxed);
            }
        }))?;
        let tokens = counter.load(Ordering::Relaxed);
        total_latency_ms += t0.elapsed().as_millis();
        total_tokens += tokens;
    }

    let avg_latency_ms = total_latency_ms as f64 / runs as f64;
    let secs = total_latency_ms as f64 / 1000.0;
    let tokens_per_sec = if secs > 0.0 { total_tokens as f64 / secs } else { 0.0 };

    Ok(BenchResult {
        model_id: model_id.into(),
        runs,
        prompt_tokens,
        total_tokens,
        avg_latency_ms,
        tokens_per_sec,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{ModelConfig, StubAdapter};

    #[test]
    fn bench_stub_runs() {
        let mut adapter = StubAdapter::new();
        adapter.load(&ModelConfig {
            model_id: "stub".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        }).unwrap();
        let res = run_benchmark(&mut adapter, "stub", 2).unwrap();
        assert_eq!(res.runs, 2);
        assert!(res.total_tokens >= 2); // Stub antwortet deterministisch
    }
}
