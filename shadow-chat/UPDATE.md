# Shadow2 – Update: Auth, Chat-Verwaltung, Admin-Bereich

Erweitert das MVP-Skeleton um die aus dem Pseudocode abgeleiteten Features.
Alle Änderungen sind rückwärtskompatibel (Migration v1 → v2).

## Neue / geänderte Dateien

| Datei | Änderung |
|---|---|
| `crates/shadow-core/src/auth/mod.rs` | **Neu.** UserStore: Argon2id-PHC-Hashes, First-Login-Bootstrap (Admin/1234), `verify_account` (inkl. Kill-Switch + `must_change_password`), `create_user`, `delete_user`, `set_password`, Audit-Log-Integration, Unit-Tests |
| `crates/shadow-core/src/session/mod.rs` | `delete_session`, `merge_sessions` (kopiert Nachrichten zeitlich sortiert in neue Session, archiviert Quellen), `rename_session` ergänzt |
| `crates/shadow-core/src/store/schema.sql` | **v2.** `user` um `password_hash`, `email`, `must_change_password`, `kill_switch_hash` erweitert |
| `crates/shadow-core/src/store/mod.rs` | Migration `migrate_v2` (idempotent, ALTER TABLE + `schema_meta.version = 2`) |
| `crates/shadow-core/src/crypto/hash.rs` | `sha256_bytes_from_str` (für Kill-Switch-Hash) |
| `crates/shadow-core/src/crypto/mod.rs` | Re-Export ergänzt |
| `crates/shadow-core/src/lib.rs` | `pub mod auth` + Re-Exports |
| `crates/shadow-cli/src/main.rs` | Neue Befehle: `login`, `logout`, `users`, `chat resume|delete|merge`, `admin users|models|audit`; interaktive Modellauswahl bei `chat` ohne Argument; `doctor` prüft Admin-Account; Login-State in `data/.current_user` |
| `Cargo.toml` / `crates/shadow-cli/Cargo.toml` | Dependency `rpassword = "7"` (Passwort-Prompt ohne Echo) |

## CLI-Befehle (neu)

```
shadow init                     # wie gehabt (+ Keystore)
shadow login                    # First-Login: Admin/1234 → neuen Admin anlegen
                                # Danach: normaler Login, Kill-Switch wird geprüft
shadow logout
shadow users                    # Liste
shadow users create <name> <role> [email]
shadow users delete <id>
shadow chat                     # interaktive Modellauswahl → neuer Chat
shadow chat <model_id>          # direkt mit Modell
shadow chat resume <sid>        # Verlauf laden und fortfahren
shadow chat delete <sid>
shadow chat merge <s1> <s2> [titel]
shadow admin users|models|audit [n]
```

## Semantik

- **First-Login** (`is_first_start`): kein Account mit `password_hash` →
  Default-Admin `Admin/1234` wird angelegt (`must_change_password = 1`),
  nach erfolgreicher Verifizierung wird der neue Admin gespeichert und der
  Default-Admin **gelöscht** (`create_admin_replace_default`).
- **Kill-Switch**: optionale Phrase, wird als SHA-256-Hash abgelegt. Wird sie
  als Passwort eingegeben, werden Sessions + Nachrichten des Accounts
  gelöscht (`session.delete`-Kaskade) und der Zugriff verweigert.
- **Merge**: Nachrichten von `chat1` und `chat2` werden zeitlich sortiert in
  eine neue Session kopiert (`content_enc` bleibt gültig — gleicher
  Master-Key), Quell-Sessions werden `archived = 1` (weich gelöscht).
- **Audit**: `auth.login`, `auth.login.failed`, `auth.kill_switch`,
  `user.create`, `user.delete`, `user.password_change`, `session.open`,
  `session.delete`, `session.merge`, `export`, `export.denied`.

## Sicherheitshinweise (MVP)

- Login-State in `.current_user` (User-ID im Klartext) ist ein MVP-Platzhalter;
  für Production: kurzlebige Session-Tokens (Hash in DB) oder OS-Keyring.
- `users create` ohne vorherigen Login akzeptiert aktuell jeden Actor
  (`"cli"`) — vor Production hinter `login` + Rollencheck (`role == admin`) setzen.
- `SHADOW_PASSWORD`-Warnung wie gehabt: nie ohne Env-Var in Produktion nutzen.

## Tests

```bash
cargo test -p shadow-core      # auth-, store-, hash-Tests (in-memory SQLite)
cargo build                    # CLI mit neuen Befehlen
```


---

# Runde 2: ShadowChat-Oberfläche + Benchmark + Einstellungen

## Neue / geänderte Dateien

| Datei | Änderung |
|---|---|
| `crates/shadow-core/src/bench.rs` | **Neu.** `run_benchmark(adapter, model_id, runs)`: festen Prompt `runs`-mal streamen, Ø-Latenz (ms) + Token-Durchsatz messen. `BenchResult` als JSON serialisierbar; Unit-Test gegen StubAdapter |
| `crates/shadow-core/src/settings.rs` | **Neu.** `get_settings` / `update_settings` (shallow Merge in `user.settings_json`, auditiert als `config.change`), `theme`, `default_model`. Keys: `theme` (dark/light/system), `language` (de/en), `default_model` |
| `crates/shadow-core/src/lib.rs` | `pub mod bench;` + `pub mod settings;`, Re-Exports |
| `crates/shadow-cli/src/shell.rs` | **Neu.** Interaktive ShadowChat-Shell — 1:1-Mapping des Pseudocodes (siehe unten) |
| `crates/shadow-cli/src/main.rs` | `mod shell;`, Befehle `shell` und `bench [model_id] [runs]`, Adapter-Bau in `build_adapter()` extrahiert (wird von `cmd_chat`, `cmd_bench` und der Shell geteilt) |

## Pseudocode-Mapping (Spec → Implementierung)

| Pseudocode | Shell/CLI |
|---|---|
| `ShadowChat.start()` | `shell::run()` → `login_loop()` → `main_menu()` |
| `show_first_login()` | `try_login()` mit `is_first_start()` → `bootstrap_default_admin()` → `create_admin_replace_default()` |
| `show_login()` | `try_login()` mit `verify_account()` inkl. `MustChangePassword`-Zweig |
| `open_chat()` | `cmd_chat(..., resume)` lädt `chat_history` (Spec: `LOAD chat_history`) |
| `create_chat()` / `delete_chat()` / `merge_chat()` | `chats_menu()` → `cmd_chat` / `cmd_chat_delete` / `cmd_chat_merge` |
| `select_model()` | `select_model_interactive()` bzw. `models_menu()` (setzt `default_model`) |
| `settings()` / `change_theme()` | `settings_menu()`: Theme (Dark/Light/System), Sprache (de/en) |
| `admin_panel()` | `admin_menu()`: Users, Audit-Log, **Benchmark** — nur sichtbar bei `role == "admin"` |
| `run_benchmark()` | `run_benchmark()` in `bench.rs`, CLI: `shadow bench [model_id] [runs]`, Audit: `admin.benchmark` |

## Benutzung

```bash
shadow init
shadow shell        # interaktive Oberfläche (Login → Hauptmenü)
# oder einzeln:
shadow bench stub 5
shadow bench        # interaktive Modellauswahl
```

## Bekannte MVP-Grenzen (unverändert aus Runde 1)

- Login-State weiterhin `.current_user` (Klartext-User-ID) — Production: Token.
- Benchmark misst Stream-Events als "Tokens" (Stub/Echo), keine echten
  Tokenzahlen — echte Zählung kommt mit Usage-Events (`StreamEvent::Usage`).
- Theme wird gespeichert, aber nicht visualisiert (kein TUI-Framework).
  Sinnvoller nächster Schritt: Ratatui/eframe-Frontend, das `settings.theme`
  tatsächlich rendert.
