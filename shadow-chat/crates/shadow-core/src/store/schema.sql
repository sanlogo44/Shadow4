-- Shadow Platform MVP – Schema v3
-- Alle Klartext-Payloads gehören verschlüsselt; Metadaten bleiben lesbar.
-- v2: User-Accounts mit password_hash (Argon2id-PHC), email,
--     must_change_password (First-Login) und kill_switch_hash.
-- v3: Rolle 'test' (Test-User mit Ablaufdatum) + expires_at-Spalte.

CREATE TABLE IF NOT EXISTS user (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','user','test')),
    created_at    INTEGER NOT NULL,          -- Unix-Sekunden
    settings_json TEXT NOT NULL DEFAULT '{}',
    password_hash TEXT,                      -- Argon2id-PHC; NULL = kein Login
    email         TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    kill_switch_hash TEXT,                    -- SHA-256 der Notfall-Phrase (optional)
    expires_at    INTEGER                     -- Unix-Sekunden; NULL = kein Ablauf (nur 'test')
);

CREATE TABLE IF NOT EXISTS session (
    id             TEXT PRIMARY KEY,
    user_id        TEXT NOT NULL REFERENCES user(id),
    title          TEXT NOT NULL DEFAULT '',
    model_id       TEXT NOT NULL,
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL,
    system_prompt_enc  BLOB,               -- AES-256-GCM, nonce-Prefix
    params_json    TEXT NOT NULL DEFAULT '{}',
    archived       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_session_user ON session(user_id, updated_at);

CREATE TABLE IF NOT EXISTS message (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES session(id),
    role            TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
    content_enc     BLOB NOT NULL,          -- AES-256-GCM
    content_plain   INTEGER NOT NULL DEFAULT 0, -- 1 = unverschlüsselt (nur Stub/Debug)
    token_count_in  INTEGER NOT NULL DEFAULT 0,
    token_count_out INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    finish_reason   TEXT,
    created_at      INTEGER NOT NULL,
    parent_id       TEXT REFERENCES message(id)
);
CREATE INDEX IF NOT EXISTS idx_message_session ON message(session_id, created_at);

CREATE TABLE IF NOT EXISTS model_entry (
    model_id           TEXT PRIMARY KEY,
    adapter_type       TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    capabilities_json  TEXT NOT NULL DEFAULT '{}',
    context_window     INTEGER NOT NULL DEFAULT 8192,
    enabled            INTEGER NOT NULL DEFAULT 1,
    export_allowed     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS audit_event (
    id          TEXT PRIMARY KEY,
    timestamp   INTEGER NOT NULL,
    actor       TEXT NOT NULL,              -- user_id oder 'system'
    action      TEXT NOT NULL,              -- z.B. 'auth.login','export','config.change'
    target      TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_event(timestamp);

CREATE TABLE IF NOT EXISTS key_material (
    id          INTEGER PRIMARY KEY CHECK (id = 1),  -- Single-Row
    kdf         TEXT NOT NULL DEFAULT 'argon2id',
    kdf_salt    BLOB NOT NULL,
    kdf_params  TEXT NOT NULL,              -- JSON: m,t,p,version
    wrapped_key BLOB NOT NULL,              -- Master-Key, AES-GCM-verschlüsselt
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
INSERT OR IGNORE INTO schema_meta (version) VALUES (3);
