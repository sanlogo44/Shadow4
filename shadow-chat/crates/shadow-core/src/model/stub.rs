//! Deterministischer Stub-Adapter.
//!
//! Kein Netzwerk, kein Modell, kein GPU. Er dient als erste
//! `ModelAdapter`-Implementierung und beweist, dass der Core
//! modellunabhängig ist. Der Stub ist bewusst regelbasiert:
//! gleiche Eingabe + gleiche Seed => gleiche Ausgabe.

use std::time::{Duration, Instant};

use super::adapter::{
    EventSink, GenerateRequest, GenerateResult, HealthStatus, MessageInput,
    ModelAdapter, ModelConfig, StreamEvent,
};
use super::capabilities::ModelCapabilities;
use crate::error::{AdapterError, FinishReason};

pub struct StubAdapter {
    loaded: bool,
    /// Künstliche Verzögerung pro Token (für Tests: Duration::ZERO).
    token_delay: Duration,
}

impl StubAdapter {
    pub fn new() -> Self {
        Self { loaded: false, token_delay: Duration::from_millis(5) }
    }

    #[cfg(test)]
    fn with_delay(token_delay: Duration) -> Self {
        Self { loaded: false, token_delay }
    }
}

/// FNV-1a: kleiner, stabiler Hash für Determinismus (kein Krypto).
fn fnv1a(s: &str) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

fn build_reply(req: &GenerateRequest) -> String {
    let last_user = req
        .messages
        .iter()
        .rev()
        .find(|m| m.role == "user")
        .map(|m| m.content.as_str())
        .unwrap_or("");
    let h = fnv1a(last_user);
    match h % 4 {
        0 => format!("Stub[{h:016x}]: Verstanden — \"{last_user}\""),
        1 => format!(
            "Stub[{h:016x}]: {} Zeichen empfangen.",
            last_user.chars().count()
        ),
        2 => format!(
            "Stub[{h:016x}]: {} Wörter gezählt.",
            last_user.split_whitespace().count()
        ),
        _ => format!("Stub[{h:016x}]: Bereit für die nächste Eingabe."),
    }
}

/// Zerlegt die Antwort in "Token" (Wort-Granularität, stabiler für Tests).
fn tokenize(reply: &str) -> Vec<String> {
    reply
        .split_inclusive(char::is_whitespace)
        .map(|s| s.to_string())
        .collect()
}

impl ModelAdapter for StubAdapter {
    fn capabilities(&self) -> ModelCapabilities {
        ModelCapabilities { max_output_tokens: 512, ..Default::default() }
    }

    fn load(&mut self, _cfg: &ModelConfig) -> Result<(), AdapterError> {
        self.loaded = true;
        Ok(())
    }

    fn unload(&mut self) -> Result<(), AdapterError> {
        self.loaded = false;
        Ok(())
    }

    fn health(&mut self) -> HealthStatus {
        if self.loaded { HealthStatus::Ok } else { HealthStatus::Down }
    }

    fn stream(
        &mut self,
        req: GenerateRequest,
        mut events: EventSink,
    ) -> Result<GenerateResult, AdapterError> {
        if !self.loaded {
            return Err(AdapterError::Unavailable("stub not loaded".into()));
        }

        let started = Instant::now();
        let deadline = Duration::from_millis(req.constraints.deadline_ms);
        let tokens_in: u32 = req
            .messages
            .iter()
            .map(|m: &MessageInput| m.content.split_whitespace().count() as u32)
            .sum();

        let reply = build_reply(&req);
        let mut out = String::new();
        let mut tokens_out: u32 = 0;

        for (i, tok) in tokenize(&reply).into_iter().enumerate() {
            if started.elapsed() > deadline {
                events(StreamEvent::Finish { reason: FinishReason::Cancelled });
                return Ok(GenerateResult {
                    tokens_in,
                    tokens_out,
                    latency_ms: started.elapsed().as_millis() as u64,
                    finish_reason: FinishReason::Cancelled,
                });
            }
            if tokens_out >= req.params.max_tokens {
                events(StreamEvent::Finish { reason: FinishReason::Length });
                return Ok(GenerateResult {
                    tokens_in,
                    tokens_out,
                    latency_ms: started.elapsed().as_millis() as u64,
                    finish_reason: FinishReason::Length,
                });
            }

            if !self.token_delay.is_zero() {
                std::thread::sleep(self.token_delay);
            }
            out.push_str(&tok);
            tokens_out += 1;
            events(StreamEvent::Token { text: tok, index: i as u32 });

            if req.constraints.stop_sequences.iter().any(|s| out.contains(s)) {
                events(StreamEvent::Finish { reason: FinishReason::Stop });
                return Ok(GenerateResult {
                    tokens_in,
                    tokens_out,
                    latency_ms: started.elapsed().as_millis() as u64,
                    finish_reason: FinishReason::Stop,
                });
            }
        }

        events(StreamEvent::Usage { tokens_in, tokens_out });
        events(StreamEvent::Finish { reason: FinishReason::Stop });
        Ok(GenerateResult {
            tokens_in,
            tokens_out,
            latency_ms: started.elapsed().as_millis() as u64,
            finish_reason: FinishReason::Stop,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{GenConstraints, GenParams, GenerateRequest, StreamEvent};

    fn req(user: &str, params: GenParams, constraints: GenConstraints) -> GenerateRequest {
        GenerateRequest {
            session_id: "s1".into(),
            messages: vec![
                crate::model::MessageInput { role: "system".into(), content: "sys".into() },
                crate::model::MessageInput { role: "user".into(), content: user.into() },
            ],
            params,
            constraints,
        }
    }

    use std::sync::{Arc, Mutex};

    fn collect(a: &mut StubAdapter, r: GenerateRequest) -> (Vec<String>, GenerateResult) {
        let toks = Arc::new(Mutex::new(Vec::new()));
        let inner = toks.clone();
        let res = a
            .stream(r, Box::new(move |ev| {
                if let StreamEvent::Token { text, .. } = ev {
                    inner.lock().unwrap().push(text);
                }
            }))
            .unwrap();
        let collected = toks.lock().unwrap().clone();
        (collected, res)
    }

    #[test]
    fn deterministic_same_input_same_output() {
        let mut a = StubAdapter::with_delay(Duration::ZERO);
        a.load(&ModelConfig {
            model_id: "stub".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        }).unwrap();
        let p = GenParams::default();
        let c = GenConstraints::default();
        let (t1, _) = collect(&mut a, req("Hallo Shadow", p.clone(), c.clone()));
        let (t2, _) = collect(&mut a, req("Hallo Shadow", p, c));
        assert_eq!(t1, t2);
    }

    #[test]
    fn max_tokens_truncates() {
        let mut a = StubAdapter::with_delay(Duration::ZERO);
        a.load(&ModelConfig {
            model_id: "stub".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        }).unwrap();
        let (_, res) = collect(&mut a, req(
            "eine recht lange eingabe mit vielen wörtern",
            GenParams { max_tokens: 3, ..Default::default() },
            GenConstraints::default(),
        ));
        assert_eq!(res.finish_reason, FinishReason::Length);
        assert!(res.tokens_out <= 3);
    }

    #[test]
    fn deadline_cancels() {
        let mut a = StubAdapter::with_delay(Duration::from_millis(50));
        a.load(&ModelConfig {
            model_id: "stub".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        }).unwrap();
        let (_, res) = collect(&mut a, req(
            "zeitkritisch",
            GenParams { max_tokens: 10_000, ..Default::default() },
            GenConstraints { deadline_ms: 30, ..Default::default() },
        ));
        assert_eq!(res.finish_reason, FinishReason::Cancelled);
    }

    #[test]
    fn unloaded_adapter_is_unavailable() {
        let mut a = StubAdapter::with_delay(Duration::ZERO);
        let res = a.stream(req("x", GenParams::default(), GenConstraints::default()),
                           Box::new(|_| {}));
        assert!(matches!(res.unwrap_err(), AdapterError::Unavailable(_)));
    }
}
