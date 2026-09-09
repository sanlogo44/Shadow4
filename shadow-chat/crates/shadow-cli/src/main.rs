//! Shadow CLI – MVP-Skeleton.
//! Baut bewusst KEINE Modell-Logik; alles läuft über shadow_core.
//!
//! Befehle:
//!   init                          Store + Keystore + Default-Modelle einrichten
//!   login | logout                User-Session verwalten (First-Login-Flow)
//!   users                         User auflisten / anlegen / löschen
//!   models                        aktivierte Modelle anzeigen
//!   doctor                        Integritäts-Check (DB, Keystore, Modell-Hashes)
//!   sessions                      eigene Sessions auflisten
//!   export <session_id>           Session exportieren (mit Exportkontrolle)
//!   chat [model_id]               neuer Chat (interaktive Modellauswahl ohne Arg)
//!   chat resume <session_id>      Chat-Verlauf fortsetzen
//!   chat delete <session_id>      Chat löschen
//!   chat merge <s1> <s2> [titel]  Chats zusammenführen
//!   admin users|models|audit      Admin-Bereich

mod shell;

use shadow_core::auth::{AuthOutcome, UserStore};
use shadow_core::bench::run_benchmark;
use shadow_core::crypto::MasterKey;
use shadow_core::model::{
    GenConstraints, GenParams, GenerateRequest, MessageInput, ModelAdapter, ModelConfig,
    ModelEntry, ModelRegistry, PythonAdapter, StubAdapter, StreamEvent,
};
use shadow_core::session::{audit, SessionStore};
use shadow_core::store;
use shadow_core::{
    keystore_initialize, keystore_is_initialized, keystore_unlock,
    sha256_bytes, sha256_file,
};
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let data_dir = std::path::PathBuf::from(
        std::env::var("SHADOW_DATA_DIR").unwrap_or_else(|_| "./shadow-data".into()),
    );
    std::fs::create_dir_all(&data_dir).expect("data dir");

    let db_path = data_dir.join("shadow.db");
    let conn = store::open(&db_path).expect("open store");

    match args.get(1).map(String::as_str) {
        Some("init") => cmd_init(&conn),
        Some("login") => cmd_login(&conn, &data_dir),
        Some("logout") => cmd_logout(&data_dir),
        Some("users") => cmd_users(&conn, &args),
        Some("models") => cmd_models(&conn),
        Some("doctor") => cmd_doctor(&db_path),
        Some("sessions") => cmd_sessions(&conn, &data_dir),
        Some("export") => match args.get(2) {
            Some(sid) => cmd_export(&conn, &data_dir, sid, export_path(&data_dir, sid)),
            None => { eprintln!("Usage: export <session_id>"); std::process::exit(2); }
        },
        Some("chat") => cmd_chat_dispatch(&conn, &data_dir, &args),
        Some("admin") => cmd_admin(&conn, &args),
        Some("bench") | Some("benchmark") => cmd_bench(&conn, &data_dir, &args),
        Some("server") => {
            // HTTP-API-Server starten (Brücke Flutter ↔ Rust Core).
            let rest: Vec<String> = args.iter().skip(2).cloned().collect();
            if let Err(e) = shadow_server::run(rest) {
                eprintln!("Server-Fehler: {e}");
                std::process::exit(1);
            }
        }
        Some("shell") => shell::run(&conn, &data_dir),
        _ => {
            eprintln!("Befehle: init | login | logout | users | models | doctor | sessions | export <session_id>");
            eprintln!("          chat [model_id] | chat resume|delete|merge ... | admin users|models|audit");
            eprintln!("          bench|benchmark [model_id] [runs] | server [--host H] [--port P] [--data-dir D] | shell");
            std::process::exit(2);
        }
    }
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn password_or_warn() -> String {
    std::env::var("SHADOW_PASSWORD").unwrap_or_else(|_| {
        eprintln!("WARN: SHADOW_PASSWORD nicht gesetzt — nutze Entwicklungs-Passwort.");
        "dev-only-not-secure".into()
    })
}

/// Entsperrt den Keystore; initialisiert ihn beim ersten Lauf (dev-freundlich).
fn open_keystore(conn: &rusqlite::Connection) -> MasterKey {
    let pw = password_or_warn();
    if keystore_is_initialized(conn).expect("keystore check") {
        keystore_unlock(conn, &pw).expect("keystore unlock (falsches Passwort?)")
    } else {
        keystore_initialize(conn, &pw).expect("keystore init")
    }
}

fn export_path(data_dir: &std::path::Path, session_id: &str) -> PathBuf {
    data_dir.join(format!("export-{session_id}.json"))
}

// ── User-Session (Login-State, MVP: Datei im data_dir) ─────────

fn current_user_file(data_dir: &std::path::Path) -> PathBuf {
    data_dir.join(".current_user")
}

fn current_user_id(data_dir: &std::path::Path) -> String {
    std::fs::read_to_string(current_user_file(data_dir))
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| {
            eprintln!("WARN: nicht eingeloggt — nutze Legacy-User 'local-admin'.");
            "local-admin".into()
        })
}

fn prompt(line: &str) -> String {
    print!("{line}: ");
    std::io::stdout().flush().unwrap();
    let mut s = String::new();
    std::io::stdin().read_line(&mut s).unwrap();
    s.trim().to_string()
}

fn prompt_optional(line: &str) -> Option<String> {
    let s = prompt(line);
    if s.is_empty() { None } else { Some(s) }
}

fn prompt_password(line: &str) -> String {
    rpassword::prompt_password(format!("{line}: ")).unwrap_or_else(|_| prompt(line))
}

/// Parst ein optionales Ablaufdatum für Test-User.
/// `+7`  → in 7 Tagen (Unix-Sekunden)
/// `1234567890` → absolute Unix-Sekunden
fn parse_expiry(arg: Option<&str>) -> Option<i64> {
    let s = arg?.trim();
    if s.is_empty() {
        return None;
    }
    let now = now();
    if let Some(days_str) = s.strip_prefix('+') {
        let days: i64 = days_str.parse().ok()?;
        Some(now + days * 86_400)
    } else {
        s.parse::<i64>().ok()
    }
}

// ── init / login / logout / users ──────────────────────────────

fn cmd_init(conn: &rusqlite::Connection) {
    conn.execute(
        "INSERT OR IGNORE INTO user (id, name, role, created_at)
         VALUES ('local-admin', 'Local Admin', 'admin', ?1)",
        [now()],
    ).expect("seed user");

    let reg = ModelRegistry::new(conn);
    reg.upsert(&ModelEntry::new("stub", "stub", "Deterministischer Stub"))
        .expect("seed stub");
    let mut py = ModelEntry::new("python-echo", "python-echo", "Python Echo (AI Layer)");
    py.capabilities_json = serde_json::json!({"note": "via shadow_ai Prozess"});
    reg.upsert(&py).expect("seed python-echo");

    // Keystore gleich mit anlegen, damit init == "fertig einrichten".
    open_keystore(conn);
    println!("OK: Store + Keystore initialisiert ({} aktive Modelle)",
             reg.list_enabled().unwrap().len());
}

fn cmd_login(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let us = UserStore::new(conn);

    if us.is_first_start().expect("first_start check") {
        // ── First-Login: Default-Admin → neuer Admin ──
        println!("First-Login: Default-Account aktivieren (Admin/1234).");
        us.bootstrap_default_admin().expect("bootstrap default admin");
        let pw = prompt_password("Passwort [Admin]");
        if !us.verify_default_admin(&pw).expect("verify default") {
            eprintln!("Login fehlgeschlagen.");
            std::process::exit(1);
        }
        println!("\nNeuer Admin-Account (der Default-Admin wird danach gelöscht):");
        let username = prompt("Username");
        let new_pw = prompt_password("Passwort");
        let email = prompt_optional("E-Mail (optional)");
        let kill_switch = prompt_optional("Kill-Switch-Phrase (optional)");
        match us.create_admin_replace_default(&username, &new_pw, email.as_deref(), kill_switch.as_deref()) {
            Ok(admin) => {
                std::fs::write(current_user_file(data_dir), &admin.id).expect("session schreiben");
                println!("Willkommen, {}! First-Login abgeschlossen.", admin.name);
            }
            Err(e) => {
                eprintln!("Fehler: {e}");
                std::process::exit(1);
            }
        }
        return;
    }

    // ── Normaler Login ──
    let username = prompt("Username");
    let password = prompt_password("Passwort");
    match us.verify_account(&username, &password).expect("verify") {
        AuthOutcome::Ok(user) => {
            std::fs::write(current_user_file(data_dir), &user.id).expect("session schreiben");
            println!("Angemeldet als {} ({}).", user.name, user.role);
        }
        AuthOutcome::MustChangePassword(user) => {
            println!("Passwort-Change erforderlich ({}).", user.name);
            let new_pw = prompt_password("Neues Passwort");
            us.set_password(&user.id, &user.id, &new_pw).expect("set_password");
            std::fs::write(current_user_file(data_dir), &user.id).expect("session schreiben");
            println!("Passwort geändert. Angemeldet als {}.", user.name);
        }
        AuthOutcome::InvalidCredentials => {
            eprintln!("Login fehlgeschlagen.");
            std::process::exit(1);
        }
        AuthOutcome::KillSwitchTriggered => {
            eprintln!("Kill-Switch ausgelöst — Account-Daten wurden gelöscht.");
            std::process::exit(1);
        }
    }
}

fn cmd_logout(data_dir: &std::path::Path) {
    let _ = std::fs::remove_file(current_user_file(data_dir));
    println!("Abgemeldet.");
}

/// users                     → Liste
/// users create <name> <role> [email]
/// users delete <id>
fn cmd_users(conn: &rusqlite::Connection, args: &[String]) {
    let us = UserStore::new(conn);
    match args.get(2).map(String::as_str) {
        Some("create") => {
            let name = args.get(3).cloned().unwrap_or_else(|| prompt("Username"));
            let role = args.get(4).cloned().unwrap_or_else(|| "user".into());
            let email = args.get(5).cloned();
            let pw = prompt_password("Passwort");
            let expires_at = parse_expiry(args.get(6).map(String::as_str));
            match us.create_user(&current_user_placeholder(), &name, &pw, &role, email.as_deref(), expires_at) {
                Ok(u) => println!("User {} angelegt ({}, Rolle {}, Ablauf: {}).", u.name, u.id, u.role,
                    expires_at.map(|e| format!("{e}")).unwrap_or_else(|| "kein".into())),
                Err(e) => { eprintln!("Fehler: {e}"); std::process::exit(1); }
            }
        }
        Some("delete") => {
            let id = match args.get(3) {
                Some(i) => i.clone(),
                None => { eprintln!("Usage: users delete <id>"); std::process::exit(2); }
            };
            us.delete_user("cli", &id).expect("delete user");
            println!("User {id} gelöscht.");
        }
        _ => {
            println!("{:<38}  {:<10}  {:<6}  E-Mail", "ID", "Name", "Rolle");
            for u in us.list_users().expect("list users") {
                println!("{:<38}  {:<10}  {:<6}  {}",
                         u.id, u.name, u.role, u.email.unwrap_or_default());
            }
        }
    }
}

/// MVP: `users create` ohne vorherigen Login — Actor-Platzhalter.
fn current_user_placeholder() -> String {
    "cli".into()
}

// ── models / doctor ────────────────────────────────────────────

fn cmd_models(conn: &rusqlite::Connection) {
    let reg = ModelRegistry::new(conn);
    for m in reg.list_enabled().expect("list models") {
        println!("{}  [{}]  export={}", m.model_id, m.adapter_type, m.export_allowed);
    }
}

/// Erwartet Modell-Datei-Hash aus adapter_config.weights_path/sha256.
fn configured_model_file(entry: &ModelEntry) -> Option<(PathBuf, String)> {
    let cfg = entry.capabilities_json.as_object()?;
    let path = cfg.get("weights_path")?.as_str()?;
    let sha = cfg.get("sha256")?.as_str()?;
    Some((PathBuf::from(path), sha.to_string()))
}

fn cmd_doctor(db_path: &std::path::Path) {
    let conn = match store::open(db_path) {
        Ok(c) => c,
        Err(e) => { eprintln!("FAIL: Store nicht lesbar: {e}"); std::process::exit(1); }
    };
    let mut problems = 0;

    // 1) DB-Integritaet (SQLite-Quick-Check)
    match conn.query_row("PRAGMA quick_check", [], |r| r.get::<_, String>(0)) {
        Ok(s) if s == "ok" => println!("OK   DB quick_check"),
        other => { println!("FAIL DB quick_check: {other:?}"); problems += 1; }
    }

    // 2) Keystore vorhanden?
    match keystore_is_initialized(&conn) {
        Ok(true) => println!("OK   Keystore initialisiert"),
        Ok(false) => { println!("WARN Keystore fehlt — `shadow init` ausführen"); problems += 1; }
        Err(e) => { println!("FAIL Keystore: {e}"); problems += 1; }
    }

    // 3) Mindestens ein admin-fähiger Account mit Passwort?
    let admins: i64 = conn.query_row(
        "SELECT COUNT(*) FROM user WHERE role = 'admin' AND password_hash IS NOT NULL",
        [], |r| r.get(0)).unwrap_or(0);
    if admins == 0 {
        println!("WARN Kein Admin mit Passwort — `shadow login` startet First-Login.");
        problems += 1;
    } else {
        println!("OK   Admin-Account vorhanden ({admins})");
    }

    // 4) Modell-Datei-Hashes (Tamper Detection)
    let reg = ModelRegistry::new(&conn);
    for m in reg.list_enabled().expect("models") {
        if let Some((path, expected)) = configured_model_file(&m) {
            if !path.exists() {
                println!("FAIL {}: Datei fehlt ({})", m.model_id, path.display());
                problems += 1;
            } else {
                match sha256_file(&path) {
                    Ok(actual) if actual == expected => {
                        println!("OK   {}: Hash stimmt", m.model_id);
                    }
                    Ok(actual) => {
                        println!("FAIL {}: Hash mismatch\n  erwartet {expected}\n  ist      {actual}", m.model_id);
                        problems += 1;
                    }
                    Err(e) => { println!("FAIL {}: {e}", m.model_id); problems += 1; }
                }
            }
        }
    }

    if problems > 0 {
        println!("\n{problems} Problem(e) — siehe FAIL/WARN-Zeilen oben.");
        std::process::exit(1);
    }
    println!("\nAlles in Ordnung.");
}

// ── sessions / export ──────────────────────────────────────────

fn cmd_sessions(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let user_id = current_user_id(data_dir);
    let store = SessionStore::new(conn);
    for s in store.list_sessions(&user_id).expect("sessions") {
        println!("{}  {}  model={}  updated={}",
                 s.id, s.title, s.model_id, s.updated_at);
    }
}

/// Exportiert eine Session als JSON. Exportkontrolle: nur wenn das
/// Session-Modell export_allowed=true hat. Jeder Export wird auditiert.
fn cmd_export(conn: &rusqlite::Connection, data_dir: &std::path::Path, session_id: &str, out: PathBuf) {
    let user_id = current_user_id(data_dir);
    let store = SessionStore::new(conn);
    let session = match store.get_session(session_id).expect("session") {
        Some(s) => s,
        None => { eprintln!("Session {session_id} nicht gefunden."); std::process::exit(1); }
    };
    if session.user_id != user_id {
        audit(conn, &user_id, "export.denied", session_id,
              serde_json::json!({"reason": "not_owner"})).expect("audit");
        eprintln!("Export VERWEIGERT: Session gehört nicht zum aktuellen User.");
        std::process::exit(1);
    }

    let reg = ModelRegistry::new(conn);
    let entry = reg.get(&session.model_id).expect("registry")
        .unwrap_or_else(|| ModelEntry::new(&session.model_id, "?", "?"));

    let detail = serde_json::json!({"session": session_id, "model": session.model_id});
    if !entry.export_allowed {
        audit(conn, &user_id, "export.denied", session_id, detail).expect("audit");
        eprintln!("Export VERWEIGERT: Modell '{}' ist nicht exportierbar (export_allowed=false).",
                  session.model_id);
        std::process::exit(1);
    }

    let key = open_keystore(conn);
    let messages = store.messages(&key, session_id).expect("messages");

    let export = serde_json::json!({
        "format": "shadow-export/v1",
        "session": session,
        "exported_at": now(),
        "messages": messages,
    });
    std::fs::write(&out, serde_json::to_string_pretty(&export).unwrap())
        .expect("write export");

    audit(conn, &user_id, "export", session_id,
          serde_json::json!({"file": out.to_string_lossy(), "bytes":
              std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0)}))
        .expect("audit");
    println!("Export geschrieben: {} (SHA-256 {})",
             out.display(), sha256_bytes(&std::fs::read(&out).unwrap()));
}

// ── chat ───────────────────────────────────────────────────────

fn cmd_chat_dispatch(conn: &rusqlite::Connection, data_dir: &std::path::Path, args: &[String]) {
    match args.get(2).map(String::as_str) {
        Some("resume") => match args.get(3) {
            Some(sid) => cmd_chat(conn, data_dir, None, Some(sid.as_str())),
            None => { eprintln!("Usage: chat resume <session_id>"); std::process::exit(2); }
        },
        Some("delete") => match args.get(3) {
            Some(sid) => cmd_chat_delete(conn, data_dir, sid),
            None => { eprintln!("Usage: chat delete <session_id>"); std::process::exit(2); }
        },
        Some("merge") => {
            let (s1, s2) = match (args.get(3), args.get(4)) {
                (Some(a), Some(b)) => (a.clone(), b.clone()),
                _ => { eprintln!("Usage: chat merge <s1> <s2> [titel]"); std::process::exit(2); }
            };
            let title = args.get(5).cloned().unwrap_or_else(|| "Zusammengeführt".into());
            cmd_chat_merge(conn, data_dir, &s1, &s2, &title);
        }
        // chat <model_id> oder chat (interaktive Auswahl)
        Some(model_id) => cmd_chat(conn, data_dir, Some(model_id), None),
        None => cmd_chat(conn, data_dir, None, None),
    }
}

fn cmd_chat_delete(conn: &rusqlite::Connection, data_dir: &std::path::Path, sid: &str) {
    let user_id = current_user_id(data_dir);
    let store = SessionStore::new(conn);
    match store.get_session(sid).expect("get session") {
        Some(s) if s.user_id == user_id => {}
        _ => { eprintln!("Session nicht gefunden oder nicht deine."); std::process::exit(1); }
    }
    store.delete_session(sid).expect("delete session");
    audit(conn, &user_id, "session.delete", sid, serde_json::json!({})).expect("audit");
    println!("Session {sid} gelöscht.");
}

fn cmd_chat_merge(conn: &rusqlite::Connection, data_dir: &std::path::Path, s1: &str, s2: &str, title: &str) {
    let user_id = current_user_id(data_dir);
    let store = SessionStore::new(conn);
    match store.merge_sessions(&user_id, s1, s2, title) {
        Ok(new_id) => {
            audit(conn, &user_id, "session.merge", &new_id,
                  serde_json::json!({"from": [s1, s2]})).expect("audit");
            println!("Sessions zusammengeführt → {new_id} (Quellen archiviert).");
        }
        Err(e) => { eprintln!("Merge fehlgeschlagen: {e}"); std::process::exit(1); }
    }
}

/// Interaktive Modellauswahl, wenn kein model_id übergeben wurde.
fn select_model_interactive(conn: &rusqlite::Connection) -> String {
    let reg = ModelRegistry::new(conn);
    let models = reg.list_enabled().expect("list models");
    if models.is_empty() {
        eprintln!("Keine aktivierten Modelle — `shadow init` ausführen.");
        std::process::exit(1);
    }
    println!("Verfügbare Modelle:");
    for (i, m) in models.iter().enumerate() {
        println!("  [{}] {}  ({})", i + 1, m.model_id, m.display_name);
    }
    let sel = prompt("Nummer oder Modell-ID");
    if let Ok(n) = sel.parse::<usize>() {
        if (1..=models.len()).contains(&n) {
            return models[n - 1].model_id.clone();
        }
    }
    if models.iter().any(|m| m.model_id == sel) {
        sel
    } else {
        eprintln!("Ungültige Auswahl: {sel}");
        std::process::exit(2);
    }
}

/// Baut UND lädt einen Adapter für einen Registry-Eintrag.
pub(crate) fn build_adapter(entry: &ModelEntry) -> Box<dyn ModelAdapter> {
    let mut adapter: Box<dyn ModelAdapter> = match entry.adapter_type.as_str() {
        "stub" => Box::new(StubAdapter::new()),
        "python-echo" => {
            let mut py = PythonAdapter::shadow_ai_default();
            // SHADOW_AI_DIR auf den Prozess vererben, damit `import shadow_ai` klappt.
            if let Ok(dir) = std::env::var("SHADOW_AI_DIR") {
                py = PythonAdapter::new(vec![
                    "python3".into(), "-c".into(),
                    format!(
                        "import sys, runpy; sys.path.insert(0, {dir:?}); \
                         runpy.run_module('shadow_ai', run_name='__main__')"
                    ),
                ]);
            }
            Box::new(py)
        }
        other => {
            eprintln!("Adapter '{other}' im MVP nicht verfügbar.");
            std::process::exit(1);
        }
    };
    adapter.load(&ModelConfig {
        model_id: entry.model_id.clone(),
        adapter_config: entry.capabilities_json.clone(),
        expected_sha256: None,
    }).expect("adapter load");
    adapter
}

/// bench [model_id] [runs] — Latenz/Durchsatz eines Modells messen.
fn cmd_bench(conn: &rusqlite::Connection, data_dir: &std::path::Path, args: &[String]) {
    let user_id = current_user_id(data_dir);
    let model_id = match args.get(2) {
        Some(m) => m.clone(),
        None => select_model_interactive(conn),
    };
    let runs: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(3);

    let reg = ModelRegistry::new(conn);
    let entry = match reg.get(&model_id).expect("registry") {
        Some(e) if e.enabled => e,
        _ => { eprintln!("Modell '{model_id}' nicht aktiviert."); std::process::exit(1); }
    };

    let mut adapter = build_adapter(&entry);
    match run_benchmark(&mut *adapter, &entry.model_id, runs) {
        Ok(res) => {
            println!("{}", serde_json::to_string_pretty(&res).unwrap());
            audit(conn, &user_id, "admin.benchmark", &res.model_id,
                  serde_json::to_value(&res).unwrap()).expect("audit");
        }
        Err(e) => { eprintln!("Benchmark fehlgeschlagen: {e}"); std::process::exit(1); }
    }
}

fn cmd_chat(
    conn: &rusqlite::Connection,
    data_dir: &std::path::Path,
    model_id: Option<&str>,
    resume_session: Option<&str>,
) {
    let user_id = current_user_id(data_dir);
    let reg = ModelRegistry::new(conn);

    // Fortsetzen: Modell aus der Session übernehmen.
    let (model_id, session_id) = if let Some(sid) = resume_session {
        let store = SessionStore::new(conn);
        let meta = match store.get_session(sid).expect("get session") {
            Some(m) if m.user_id == user_id => m,
            _ => { eprintln!("Session nicht gefunden oder nicht deine."); std::process::exit(1); }
        };
        (meta.model_id, sid.to_string())
    } else {
        let mid = match model_id {
            Some(m) => m.to_string(),
            None => select_model_interactive(conn),
        };
        let store = SessionStore::new(conn);
        let sid = store.create_session(&user_id, &mid, "CLI-Chat").expect("create session");
        (mid, sid)
    };

    let entry = match reg.get(&model_id).expect("registry") {
        Some(e) if e.enabled => e,
        _ => {
            eprintln!("Modell '{model_id}' nicht aktiviert. `shadow init` ausführen?");
            std::process::exit(1);
        }
    };

    let mut adapter = build_adapter(&entry);

    let key = open_keystore(conn);
    let sessions = SessionStore::new(conn);

    // Beim Fortsetzen: Chat-Verlauf laden.
    let mut history: Vec<MessageInput> = Vec::new();
    if resume_session.is_some() {
        for m in sessions.messages(&key, &session_id).expect("history") {
            history.push(MessageInput { role: m.role, content: m.content });
        }
        println!("Session {session_id} fortgesetzt ({} Nachrichten).", history.len());
    } else {
        println!("Session {session_id} — leere Eingabe beendet (/exit).");
    }
    audit(conn, &user_id, "session.open", &session_id,
          serde_json::json!({"model": model_id})).expect("audit");

    let stdin = std::io::stdin();
    loop {
        print!("> ");
        std::io::stdout().flush().unwrap();
        let mut line = String::new();
        if stdin.read_line(&mut line).unwrap() == 0 { break; }
        let input = line.trim();
        if input.is_empty() || input == "/exit" { break; }

        sessions.append_message(&key, &session_id, "user", input, None)
            .expect("persist user msg");
        history.push(MessageInput { role: "user".into(), content: input.into() });

        let req = GenerateRequest {
            session_id: session_id.clone(),
            messages: history.clone(),
            params: GenParams::default(),
            constraints: GenConstraints::default(),
        };

        let reply = Arc::new(Mutex::new(String::new()));
        let reply_inner = reply.clone();
        let res = adapter.stream(req, Box::new(move |ev| match ev {
            StreamEvent::Token { text, .. } => {
                reply_inner.lock().unwrap().push_str(&text);
                print!("{text}");
                std::io::stdout().flush().unwrap();
            }
            StreamEvent::Usage { .. } => {}
            StreamEvent::Finish { reason } => println!("\n[{reason:?}]"),
        })).expect("stream");
        let reply = reply.lock().unwrap().clone();

        sessions.append_message(
            &key, &session_id, "assistant", &reply,
            Some(&format!("{:?}", res.finish_reason)),
        ).expect("persist assistant msg");
        history.push(MessageInput { role: "assistant".into(), content: reply });
    }
}

// ── admin ──────────────────────────────────────────────────────

fn cmd_admin(conn: &rusqlite::Connection, args: &[String]) {
    match args.get(2).map(String::as_str) {
        Some("users") => {
            println!("{:<38}  {:<10}  {:<6}", "ID", "Name", "Rolle");
            for u in UserStore::new(conn).list_users().expect("users") {
                println!("{:<38}  {:<10}  {:<6}", u.id, u.name, u.role);
            }
        }
        Some("models") => {
            let reg = ModelRegistry::new(conn);
            println!("{:<14}  {:<12}  {:<7}  {}", "Modell", "Adapter", "enabled", "export");
            // list() gibt alle Einträge; falls nicht vorhanden, Fallback auf list_enabled.
            for m in reg.list_enabled().expect("models") {
                println!("{:<14}  {:<12}  {:<7}  {}",
                         m.model_id, m.adapter_type, m.enabled, m.export_allowed);
            }
        }
        Some("audit") => {
            let limit: i64 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(20);
            let mut stmt = conn.prepare(
                "SELECT timestamp, actor, action, target FROM audit_event
                 ORDER BY timestamp DESC LIMIT ?1").unwrap();
            let rows = stmt.query_map([limit], |r| {
                Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?, r.get::<_, String>(3)?))
            }).unwrap();
            for r in rows {
                let (ts, actor, action, target) = r.unwrap();
                println!("{ts}  {actor:<12}  {action:<28}  {target}");
            }
        }
        _ => {
            eprintln!("Usage: admin users | admin models | admin audit [n]");
            std::process::exit(2);
        }
    }
}
