//! ShadowChat-Oberfläche: interaktive Shell über dem Core.
//!
//! Implementiert den Pseudocode "Shadow Chat Interface" aus der Spec:
//! Start → Login (inkl. First-Login) → Hauptmenü (Chats, Modelle,
//! Einstellungen, Admin) → Chat-Loop.

use shadow_core::auth::{AuthOutcome, UserStore};
use shadow_core::bench::run_benchmark;
use shadow_core::model::ModelRegistry;
use shadow_core::session::{audit, SessionStore};
use shadow_core::settings;

use crate::{
    build_adapter, cmd_chat, cmd_chat_delete, cmd_chat_merge, current_user_id,
    prompt, prompt_optional, prompt_password, select_model_interactive,
};

pub fn run(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    login_loop(conn, data_dir);
    main_menu(conn, data_dir);
}

// ── ShadowChat.start() / show_login() / show_first_login() ─────

fn logged_in(data_dir: &std::path::Path) -> bool {
    data_dir.join(".current_user").exists()
}

fn user_role(conn: &rusqlite::Connection, user_id: &str) -> String {
    conn.query_row(
        "SELECT role FROM user WHERE id = ?1",
        [user_id],
        |r| r.get(0),
    ).unwrap_or_else(|_| "user".into())
}

fn login_loop(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    while !logged_in(data_dir) {
        println!("\n=== ShadowChat Login ===");
        try_login(conn, data_dir);
    }
}

/// Ein Login-Versuch. Gibt false zurück statt zu exitieren (Shell-Loop).
fn try_login(conn: &rusqlite::Connection, data_dir: &std::path::Path) -> bool {
    let us = UserStore::new(conn);

    // ── First-Login: Default-Admin → neuer Admin (Spec: show_first_login) ──
    if us.is_first_start().unwrap_or(false) {
        println!("First-Login: Default-Account (Admin/1234).");
        us.bootstrap_default_admin().expect("bootstrap");
        let pw = prompt_password("Passwort [Admin]");
        if !us.verify_default_admin(&pw).unwrap_or(false) {
            eprintln!("Login fehlgeschlagen.");
            return false;
        }
        println!("\nNeuer Admin-Account (Default-Admin wird danach gelöscht):");
        let username = prompt("Username");
        let new_pw = prompt_password("Passwort");
        let email = prompt_optional("E-Mail (optional)");
        let kill_switch = prompt_optional("Kill-Switch-Phrase (optional)");
        match us.create_admin_replace_default(&username, &new_pw, email.as_deref(), kill_switch.as_deref()) {
            Ok(admin) => {
                std::fs::write(data_dir.join(".current_user"), &admin.id).expect("session");
                println!("Willkommen, {}! First-Login abgeschlossen.", admin.name);
                true
            }
            Err(e) => { eprintln!("Fehler: {e}"); false }
        }
    } else {
        // ── Normaler Login (Spec: show_login) ──
        let username = prompt("Username");
        let password = prompt_password("Passwort");
        match us.verify_account(&username, &password).expect("verify") {
            AuthOutcome::Ok(user) => {
                std::fs::write(data_dir.join(".current_user"), &user.id).expect("session");
                println!("Angemeldet als {} ({}).", user.name, user.role);
                true
            }
            AuthOutcome::MustChangePassword(user) => {
                println!("Passwort-Change erforderlich ({}).", user.name);
                let new_pw = prompt_password("Neues Passwort");
                us.set_password(&user.id, &user.id, &new_pw).expect("set_password");
                std::fs::write(data_dir.join(".current_user"), &user.id).expect("session");
                println!("Passwort geändert. Angemeldet als {}.", user.name);
                true
            }
            AuthOutcome::InvalidCredentials => {
                eprintln!("Login fehlgeschlagen.");
                false
            }
            AuthOutcome::KillSwitchTriggered => {
                eprintln!("Kill-Switch ausgelöst — Account-Daten wurden gelöscht.");
                false
            }
        }
    }
}

// ── Hauptmenü (Spec: ShadowChat nach Login) ────────────────────

fn main_menu(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    loop {
        let user_id = current_user_id(data_dir);
        let role = user_role(conn, &user_id);
        let name: String = conn.query_row(
            "SELECT name FROM user WHERE id = ?1", [&user_id], |r| r.get(0))
            .unwrap_or_else(|_| user_id.clone());
        let theme = settings::theme(conn, &user_id).unwrap_or_else(|_| "system".into());

        println!("\n=== ShadowChat ===  ({name}, Rolle: {role}, Theme: {theme})");
        println!("1) Chats            2) Neuer Chat");
        println!("3) Modelle          4) Einstellungen");
        if role == "admin" {
            println!("5) Admin");
        }
        println!("0) Logout / Beenden");

        match prompt("Auswahl").as_str() {
            "1" => chats_menu(conn, data_dir),
            "2" => new_chat(conn, data_dir),
            "3" => models_menu(conn, data_dir),
            "4" => settings_menu(conn, data_dir),
            "5" if role == "admin" => admin_menu(conn, data_dir),
            "0" => {
                let _ = std::fs::remove_file(data_dir.join(".current_user"));
                if !prompt("Beenden? [j/n]").starts_with('j') {
                    login_loop(conn, data_dir);
                } else {
                    break;
                }
            }
            other => println!("Ungültige Auswahl: {other}"),
        }
    }
}

// ── Chats (Spec: open_chat / create_chat / delete_chat / merge_chat) ──

fn chats_menu(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let user_id = current_user_id(data_dir);
    let store = SessionStore::new(conn);
    let sessions = store.list_sessions(&user_id).expect("sessions");

    println!("\n--- Deine Chats ---");
    if sessions.is_empty() {
        println!("(keine)");
    }
    for (i, s) in sessions.iter().enumerate() {
        println!("  [{}] {}  (model={}, updated={})",
                 i + 1, s.title, s.model_id, s.updated_at);
    }
    println!("r) Fortsetzen   d) Löschen   m) Merge   b) Zurück");
    match prompt("Aktion").as_str() {
        "r" => {
            let sel = prompt("Nummer");
            if let Ok(n) = sel.parse::<usize>() {
                if let Some(s) = sessions.get(n - 1) {
                    cmd_chat(conn, data_dir, None, Some(&s.id)); // open_chat()
                }
            }
        }
        "d" => {
            let sel = prompt("Nummer");
            if let Ok(n) = sel.parse::<usize>() {
                if let Some(s) = sessions.get(n - 1) {
                    cmd_chat_delete(conn, data_dir, &s.id);
                }
            }
        }
        "m" => {
            let a = prompt("Erste Session (Nummer)");
            let b = prompt("Zweite Session (Nummer)");
            if let (Ok(na), Ok(nb)) = (a.parse::<usize>(), b.parse::<usize>()) {
                if let (Some(s1), Some(s2)) = (sessions.get(na - 1), sessions.get(nb - 1)) {
                    let title = prompt_optional("Titel der neuen Session")
                        .unwrap_or_else(|| "Zusammengeführt".into());
                    cmd_chat_merge(conn, data_dir, &s1.id, &s2.id, &title);
                }
            }
        }
        _ => {}
    }
}

fn new_chat(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let user_id = current_user_id(data_dir);
    // Default-Modell aus Einstellungen, sonst interaktiv (Spec: select_model).
    let model_id = match settings::default_model(conn, &user_id).expect("settings") {
        Some(m) => {
            println!("Default-Modell: {m}");
            m
        }
        None => select_model_interactive(conn),
    };
    cmd_chat(conn, data_dir, Some(&model_id), None);
}

// ── Modelle (Spec: select_model) ───────────────────────────────

fn models_menu(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let reg = ModelRegistry::new(conn);
    let models = reg.list_enabled().expect("models");
    println!("\n--- Modelle ---");
    for (i, m) in models.iter().enumerate() {
        println!("  [{}] {}  [{}]  export={}",
                 i + 1, m.model_id, m.adapter_type, m.export_allowed);
    }
    let sel = prompt("Als Default setzen (Nummer, leer = nichts ändern)");
    if sel.is_empty() { return; }
    if let Ok(n) = sel.parse::<usize>() {
        if let Some(m) = models.get(n - 1) {
            let user_id = current_user_id(data_dir);
            settings::update_settings(conn, &user_id, &user_id,
                serde_json::json!({"default_model": m.model_id})).expect("settings");
            println!("Default-Modell: {}", m.model_id);
        }
    }
}

// ── Einstellungen (Spec: settings() / change_theme()) ──────────

fn settings_menu(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let user_id = current_user_id(data_dir);
    loop {
        let cur = settings::get_settings(conn, &user_id).expect("settings");
        println!("\n--- Einstellungen ---  (aktuell: {cur})");
        println!("1) Theme    2) Sprache    3) Default-Modell    b) Zurück");
        match prompt("Auswahl").as_str() {
            "1" => {
                println!("  [1] Dark   [2] Light   [3] System");
                let t = match prompt("Theme").as_str() {
                    "1" => "dark", "2" => "light", "3" => "system",
                    _ => continue,
                };
                settings::update_settings(conn, &user_id, &user_id,
                    serde_json::json!({"theme": t})).expect("settings");
                println!("Theme: {t}");
            }
            "2" => {
                println!("  [1] Deutsch   [2] English");
                let l = match prompt("Sprache").as_str() {
                    "1" => "de", "2" => "en", _ => continue,
                };
                settings::update_settings(conn, &user_id, &user_id,
                    serde_json::json!({"language": l})).expect("settings");
                println!("Sprache: {l}");
            }
            "3" => {
                models_menu(conn, data_dir);
            }
            _ => break,
        }
    }
}

// ── Admin (Spec: admin_panel() / run_benchmark()) ──────────────

fn admin_menu(conn: &rusqlite::Connection, data_dir: &std::path::Path) {
    let user_id = current_user_id(data_dir);
    loop {
        println!("\n--- Admin ---");
        println!("1) Users    2) Audit-Log    3) Benchmark    b) Zurück");
        match prompt("Auswahl").as_str() {
            "1" => {
                println!("{:<38}  {:<10}  {:<6}", "ID", "Name", "Rolle");
                for u in UserStore::new(conn).list_users().expect("users") {
                    println!("{:<38}  {:<10}  {:<6}", u.id, u.name, u.role);
                }
            }
            "2" => {
                let mut stmt = conn.prepare(
                    "SELECT timestamp, actor, action, target FROM audit_event
                     ORDER BY timestamp DESC LIMIT 20").unwrap();
                let rows = stmt.query_map([], |r| {
                    Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?, r.get::<_, String>(3)?))
                }).unwrap();
                for r in rows {
                    let (ts, actor, action, target) = r.unwrap();
                    println!("{ts}  {actor:<12}  {action:<28}  {target}");
                }
            }
            "3" => {
                let model_id = select_model_interactive(conn);
                let reg = ModelRegistry::new(conn);
                let entry = match reg.get(&model_id).expect("registry") {
                    Some(e) if e.enabled => e,
                    _ => { eprintln!("Modell nicht aktiviert."); continue; }
                };
                let mut adapter = build_adapter(&entry);
                let runs: usize = prompt("Durchläufe [3]")
                    .parse().unwrap_or(3);
                match run_benchmark(&mut *adapter, &entry.model_id, runs) {
                    Ok(res) => {
                        println!("Modell:          {}", res.model_id);
                        println!("Durchläufe:      {}", res.runs);
                        println!("Ø Latenz:        {:.1} ms", res.avg_latency_ms);
                        println!("Tokens gesamt:   {}", res.total_tokens);
                        println!("Durchsatz:       {:.1} Tokens/s", res.tokens_per_sec);
                        audit(conn, &user_id, "admin.benchmark", &res.model_id,
                              serde_json::to_value(&res).unwrap()).expect("audit");
                    }
                    Err(e) => eprintln!("Benchmark fehlgeschlagen: {e}"),
                }
            }
            _ => break,
        }
    }
}
