//! PythonAdapter: ModelAdapter über Shadow Node Protocol v1 (JSONL/stdio).
//!
//! Spawnt die Python AI Layer als Kindprozess und spricht das Protokoll
//! aus shadow-ai/shadow_ai/protocol.py. Enforcing: Deadline wird clientseitig
//! überwacht; bei Überschreitung wird `cancel` gesendet und auf `finish`
//! gewartet (Kindprozess bleibt konsistent).

use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::mpsc::{channel, Receiver};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use super::adapter::{
    EventSink, GenerateRequest, GenerateResult, HealthStatus, ModelAdapter, ModelConfig,
    StreamEvent,
};
use super::capabilities::ModelCapabilities;
use crate::error::{AdapterError, FinishReason};

const HELLO_TIMEOUT: Duration = Duration::from_secs(15);

struct ChildIo {
    child: Child,
    stdin: ChildStdin,
    rx: Receiver<Result<Value, String>>,
}

impl ChildIo {
    fn spawn(cmd: &[String]) -> Result<Self, AdapterError> {
        let mut child = Command::new(&cmd[0])
            .args(&cmd[1..])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| AdapterError::Unavailable(format!("spawn: {e}")))?;

        let stdin = child.stdin.take().ok_or_else(|| {
            AdapterError::Internal("no stdin pipe".into())
        })?;
        let stdout: ChildStdout = child.stdout.take().ok_or_else(|| {
            AdapterError::Internal("no stdout pipe".into())
        })?;

        let (tx, rx) = channel::<Result<Value, String>>();
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut line = String::new();
            loop {
                line.clear();
                match reader.read_line(&mut line) {
                    Ok(0) => break, // EOF
                    Ok(_) => {
                        let v = serde_json::from_str::<Value>(line.trim())
                            .map_err(|e| format!("bad json: {e}"));
                        if tx.send(v).is_err() {
                            break;
                        }
                    }
                    Err(e) => {
                        let _ = tx.send(Err(format!("read: {e}")));
                        break;
                    }
                }
            }
        });

        Ok(Self { child, stdin, rx })
    }

    fn send(&mut self, msg: &Value) -> Result<(), AdapterError> {
        let line = serde_json::to_string(msg)
            .map_err(|e| AdapterError::Internal(format!("encode: {e}")))?;
        self.stdin
            .write_all(line.as_bytes())
            .and_then(|_| self.stdin.write_all(b"\n"))
            .and_then(|_| self.stdin.flush())
            .map_err(|e| AdapterError::Unavailable(format!("write: {e}")))
    }

    fn recv(&self, timeout: Duration) -> Result<Value, AdapterError> {
        match self.rx.recv_timeout(timeout) {
            Ok(Ok(v)) => Ok(v),
            Ok(Err(e)) => Err(AdapterError::Internal(e)),
            Err(_) => Err(AdapterError::Unavailable("timeout or process dead".into())),
        }
    }
}

impl Drop for ChildIo {
    fn drop(&mut self) {
        let _ = self.send(&json!({"v":1,"type":"shutdown"}));
        let _ = self.child.wait();
    }
}

pub struct PythonAdapter {
    cmd: Vec<String>,
    io: Option<ChildIo>,
    loaded: bool,
}

impl PythonAdapter {
    pub fn new(cmd: Vec<String>) -> Self {
        Self { cmd, io: None, loaded: false }
    }

    /// Standard: shadow-ai Package aus dem Repo.
    pub fn shadow_ai_default() -> Self {
        Self::new(vec!["python3".into(), "-m".into(), "shadow_ai".into()])
    }
}

fn map_error_code(code: &str, message: &str) -> AdapterError {
    match code {
        "auth" => AdapterError::Auth,
        "rate_limited" => AdapterError::RateLimited,
        "context_overflow" => AdapterError::ContextOverflow,
        "unavailable" => AdapterError::Unavailable(message.into()),
        "cancelled" => AdapterError::Cancelled,
        _ => AdapterError::Internal(format!("{code}: {message}")),
    }
}

fn map_finish(reason: &str) -> FinishReason {
    match reason {
        "stop" => FinishReason::Stop,
        "length" => FinishReason::Length,
        "cancelled" => FinishReason::Cancelled,
        _ => FinishReason::Error,
    }
}

impl ModelAdapter for PythonAdapter {
    fn capabilities(&self) -> ModelCapabilities {
        ModelCapabilities::default()
    }

    fn load(&mut self, cfg: &ModelConfig) -> Result<(), AdapterError> {
        if self.io.is_none() {
            let mut io = ChildIo::spawn(&self.cmd)?;
            io.send(&json!({"v":1,"type":"hello"}))?;
            let ack = io.recv(HELLO_TIMEOUT)?;
            if ack.get("type") != Some(&Value::from("hello_ack")) {
                return Err(AdapterError::Internal(format!("no hello_ack: {ack}")));
            }
            self.io = Some(io);
        }
        let io = self.io.as_mut().unwrap();
        io.send(&json!({"v":1,"type":"load","config":{
            "model_id": cfg.model_id,
            "adapter_config": cfg.adapter_config,
            "expected_sha256": cfg.expected_sha256,
        }}))?;
        let resp = io.recv(Duration::from_secs(120))?;
        match resp.get("type").and_then(Value::as_str) {
            Some("ok") => {
                self.loaded = true;
                Ok(())
            }
            Some("error") => Err(map_error_code(
                resp.get("code").and_then(Value::as_str).unwrap_or("internal"),
                resp.get("message").and_then(Value::as_str).unwrap_or(""),
            )),
            _ => Err(AdapterError::Internal(format!("unexpected load response: {resp}"))),
        }
    }

    fn unload(&mut self) -> Result<(), AdapterError> {
        self.io = None; // Drop sendet shutdown und wartet auf Kind
        self.loaded = false;
        Ok(())
    }

    fn health(&mut self) -> HealthStatus {
        if !self.loaded {
            return HealthStatus::Down;
        }
        match &mut self.io {
            Some(io) => {
                if io.child.try_wait().ok().flatten().is_none() {
                    HealthStatus::Ok
                } else {
                    HealthStatus::Down
                }
            }
            None => HealthStatus::Down,
        }
    }

    fn stream(
        &mut self,
        req: GenerateRequest,
        mut events: EventSink,
    ) -> Result<GenerateResult, AdapterError> {
        if !self.loaded {
            return Err(AdapterError::Unavailable("model not loaded".into()));
        }
        let io = self.io.as_mut().unwrap();
        let started = Instant::now();
        let deadline = Duration::from_millis(req.constraints.deadline_ms);

        io.send(&json!({"v":1,"type":"stream","request":req}))?;

        let mut tokens_in = 0u32;
        let mut tokens_out = 0u32;
        let mut cancel_sent = false;

        loop {
            let remaining = deadline.saturating_sub(started.elapsed());
            // Puffer für Netz-/Prozess-Latenz, aber hart begrenzt.
            let wait = remaining.max(Duration::from_millis(50)).min(Duration::from_secs(2));
            let msg = io.recv(wait)?;

            if started.elapsed() > deadline && !cancel_sent {
                cancel_sent = true;
                io.send(&json!({"v":1,"type":"cancel"}))?;
            }

            match msg.get("type").and_then(Value::as_str) {
                Some("token") => {
                    tokens_out += 1;
                    events(StreamEvent::Token {
                        text: msg.get("text").and_then(Value::as_str).unwrap_or("").to_string(),
                        index: msg.get("index").and_then(Value::as_u64).unwrap_or(0) as u32,
                    });
                }
                Some("usage") => {
                    tokens_in = msg.get("tokens_in").and_then(Value::as_u64).unwrap_or(0) as u32;
                    events(StreamEvent::Usage { tokens_in, tokens_out });
                }
                Some("finish") => {
                    let reason = map_finish(
                        msg.get("reason").and_then(Value::as_str).unwrap_or("error"));
                    let reason = if cancel_sent && reason == FinishReason::Stop {
                        FinishReason::Cancelled // Client-seitiger Deadline-Abbruch
                    } else {
                        reason
                    };
                    events(StreamEvent::Finish { reason });
                    return Ok(GenerateResult {
                        tokens_in,
                        tokens_out,
                        latency_ms: started.elapsed().as_millis() as u64,
                        finish_reason: reason,
                    });
                }
                Some("error") => {
                    return Err(map_error_code(
                        msg.get("code").and_then(Value::as_str).unwrap_or("internal"),
                        msg.get("message").and_then(Value::as_str).unwrap_or(""),
                    ));
                }
                other => {
                    return Err(AdapterError::Internal(format!("unexpected msg: {other:?}")));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{GenConstraints, GenParams, MessageInput};

    use std::sync::{Arc, Mutex};

    fn echo_cmd() -> Vec<String> {
        let py = std::env::var("SHADOW_AI_DIR")
            .unwrap_or_else(|_| "../../shadow-ai".into());
        vec![
            "python3".into(),
            "-c".into(),
            format!("import sys; sys.path.insert(0, {:?}); from shadow_ai.server import main; main()", py),
        ]
    }

    fn req(user: &str) -> GenerateRequest {
        GenerateRequest {
            session_id: "s1".into(),
            messages: vec![MessageInput { role: "user".into(), content: user.into() }],
            params: GenParams::default(),
            constraints: GenConstraints::default(),
        }
    }

    #[test]
    #[ignore = "benötigt lauffähige Shadow LLM Engine (python3 + shadow-ai Paket)"]
    fn end_to_end_echo() {
        let mut a = PythonAdapter::new(echo_cmd());
        a.load(&ModelConfig {
            model_id: "echo".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        }).unwrap();
        assert_eq!(a.health(), HealthStatus::Ok);

        let out = Arc::new(Mutex::new(String::new()));
        let out_inner = out.clone();
        let res = a.stream(req("Hallo Rust"), Box::new(move |ev| {
            if let StreamEvent::Token { text, .. } = ev {
                out_inner.lock().unwrap().push_str(&text);
            }
        })).unwrap();
        let out = out.lock().unwrap().clone();
        assert!(out.contains("Hallo Rust"));
        assert_eq!(res.finish_reason, FinishReason::Stop);
    }

    #[test]
    #[ignore = "benötigt lauffähige Shadow LLM Engine (python3 + shadow-ai Paket)"]
    fn deadline_enforced_client_side() {
        let mut a = PythonAdapter::new(echo_cmd());
        a.load(&ModelConfig {
            model_id: "echo".into(),
            adapter_config: serde_json::json!({}),
            expected_sha256: None,
        }).unwrap();
        let res = a.stream(GenerateRequest {
            session_id: "s2".into(),
            messages: vec![MessageInput {
                role: "user".into(),
                content: "dieser request soll sehr lange dauern".into(),
            }],
            params: GenParams { max_tokens: 10_000, ..Default::default() },
            constraints: GenConstraints { deadline_ms: 1, ..Default::default() },
        }, Box::new(|_| {})).unwrap();
        assert_eq!(res.finish_reason, FinishReason::Cancelled);
    }
}
