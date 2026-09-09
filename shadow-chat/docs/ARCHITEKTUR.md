# Shadow Chat — UI & Verwaltungsplattform

Modulare Chat-Oberfläche und Verwaltungsplattform für **Shadow**. Die UI
(Flutter) spricht über eine lokale HTTP-API mit dem **Rust Core** (`shadow-core`),
der wiederum die **Shadow LLM Engine** anbindet. Die AI-Logik selbst ist nicht
Teil dieser Anwendung — sie läuft in der separaten LLM Engine und wird über eine
Schnittstelle verbunden.

```
┌─────────────┐   HTTP/JSON   ┌──────────────────┐   Adapter   ┌──────────────────┐
│  Flutter UI │ ────────────▶│  shadow-server   │ ──────────▶│ Shadow LLM Engine │
│  (shadow_chat)│ ◀──────────│  (Rust, axum)    │ ◀──────────│  (Python module)  │
└─────────────┘               └──────────────────┘            └──────────────────┘
                                      │
                                      ▼
                            ┌──────────────────┐
                            │  shadow-core     │  Verschlüsselung, Auth,
                            │  (Rust)          │  Sessions, Modelle, Benchmark
                            └──────────────────┘
```

## Komponenten

| Komponente | Pfad | Sprache | Status |
|---|---|---|---|
| Flutter UI | `flutter_ui/` | Dart | ✅ implementiert, build-verifiziert (Web + Desktop-Scaffolds) |
| shadow-server (HTTP-API) | `crates/shadow-server/` | Rust | ✅ implementiert, smoke-getestet |
| shadow-core (Logik) | `crates/shadow-core/` | Rust | ✅ implementiert (10 Tests grün) |
| shadow-cli | `crates/shadow-cli/` | Rust | ✅ implementiert |
| Shadow LLM Engine | `shadow-ai/` | Python | 🔌 Adapter vorhanden (Stub-Adapter aktiv bis Engine verbunden) |

## Funktionen

### Login & Benutzer
- Erster Start: Default-Admin `Admin` / `1234` → Login erzwingt Einrichtung
  eines neuen Admins (Benutzername, Passwort, optionale E-Mail, optionales
  Kill-Switch-Passwort). Alle Daten verschlüsselt.
- Rollen: **Admin** (Benutzer/Modelle/Einstellungen/Benchmark/Training/Nodes),
  **User** (Chat, eigene Chats, freigegebene Modelle), **Test User** (wie User +
  Ablaufdatum + automatische Deaktivierung).
- Passwörter als Argon2id-PHC-String, Chat-Inhalte AES-256-GCM verschlüsselt.

### Chat
- Markdown-Rendering (`flutter_markdown`), Code-Blöcke, Dateien vorbereitet.
- Chat-Historien-Sidebar: einklappen, löschen, umbenennen, zusammenführen.
- Modell-Dropdown (spricht mit der LLM Engine über den Core).
- Chat-Menü: **Schwarm-Modus**, **Ziel-Agent**, **Prompt-Verfeinerer**
  (Schnittstellen vorbereitet, "ready for future integration").

### Design
- Dark Mode (`#000000` Hintergrund), Light Mode (`#ffffff`), Dark/Light/System.
- Highlight-Farbe standardmäßig `#16C916`, vom Nutzer änderbar via
  RGB/Hex/Farbrad (`flutter_colorpicker`). Theme & Sprache werden beim Server
  persistiert.

### Einstellungen
Sprache, Design, Modelle, Benutzer, API, Plugins, Datenschutz.

### Admin-Dashboard
Benutzerübersicht, Modellübersicht, Systemstatus, Benchmark-Bereich,
Node-Verwaltung, Trainingsstatus, API-Verbindung, Audit-Log.

## Sicherheit
- Chat-Inhalte AES-256-GCM verschlüsselt (Master-Key via Argon2id).
- Passwörter als Argon2id-PHC-String gehasht.
- Token-basierte Session-Authentifizierung (Bearer-Token, In-Memory-Token-Map).
- SHA-256 Manipulationserkennung für Modelle und Exports (Core-seitig vorhanden).
- Kill-Switch: optionales Notfall-Passwort löscht alle Account-Daten (Core-seitig).

> Hinweis: Die Verschlüsselung gilt für Chat-Inhalte und Passwörter im Core. Die API ist lokal sowie netzwerkfähig (`--host 0.0.0.0`) und CORS ist aktiviert.

## Build & Ausführung

### Voraussetzungen
- Rust (stable, ≥ 1.74) + `cargo`
- Flutter (≥ 3.19) / Dart SDK (≥ 3.3)
- Python 3 (optional, für die Shadow LLM Engine)

### Rust Core + API-Server bauen
```bash
# Im Workspace-Root (enthält Cargo.toml):
cargo build --release

# API-Server starten (Standard: 127.0.0.1:8787)
./target/release/shadow-cli server --port 8787 --data-dir ./shadow-data

# Mit LLM Engine (Python-Modul shadow_ai):
SHADOW_AI_CMD="python3 -m shadow_ai" \
  ./target/release/shadow-cli server --port 8787 --data-dir ./shadow-data
```

Umgebungsvariablen:
- `SHADOW_PASSWORD` — Keystore-Passwort (Standard: `dev-only-not-secure`).
- `SHADOW_AI_CMD` — Kommando zur LLM Engine (space-separiert, z. B. `python3 -m shadow_ai`).
  Ohne Angabe läuft der `StubAdapter` (Modell `shadow-default`).

### Flutter UI bauen
```bash
cd flutter_ui
flutter pub get
flutter analyze          # statische Analyse
flutter run -d chrome    # Web (Entwicklung)
# oder Desktop:
flutter run -d windows   # / -d linux / -d macos
# Release-Build:
flutter build web        # -> build/web/
flutter build windows    # / linux / macos / apk
```

### CLI
```bash
shadow login
shadow chat
shadow users
shadow models
shadow benchmark
shadow server            # startet die HTTP-API
```

## API-Endpunkte (Auszug)
```
GET  /api/auth/status            # first_start, version
POST /api/auth/login             # {username, password} -> token
POST /api/auth/setup             # neuen Admin anlegen
GET  /api/users                  # Benutzerliste
POST /api/users                  # Benutzer anlegen (role: user|admin|test, expires_at)
GET  /api/sessions               # Chat-Sessions
POST /api/sessions               # Session erstellen
POST /api/sessions/:id/messages  # Nachricht senden -> Assistant-Antwort
POST /api/sessions/:id/merge     # Sessions zusammenführen
GET  /api/models                 # freigegebene Modelle
POST /api/admin/benchmark        # Benchmark ausführen
GET  /api/admin/audit            # Audit-Log
GET  /api/engine/health          # LLM-Engine-Status
```

## Architektur-Entscheidungen
- **shadow-server** als Brücke Flutter ↔ Core: axum REST-API, die `shadow-core`
  kapselt. Library + Binary, damit `shadow server` den Server in-Process startet.
- **Adapter-Pattern** im Core: `StubAdapter` (Default, ohne Engine),
  `PythonAdapter` (mit `SHADOW_AI_CMD`). Damit ist die UI modellunabhängig und
  später an die eigene LLM Engine anschließbar.
- **State-Management** in Flutter: Provider (`ChangeNotifier`). Auth, Theme,
  Sessions und Modelle in einem zentralen `AppState`.

## Status-Liste

| Bereich | Status | Hinweis |
|---|---|---|
| Login / Setup-Flow | ✅ | Default-Admin → neuer Admin, verschlüsselt |
| Rollen (Admin/User/Test) | ✅ | Test-User mit Ablauf + Auto-Deaktivierung |
| Chat (Markdown, Code, Sidebar) | ✅ | Rename/Delete/Merge implementiert |
| Modell-Dropdown | ✅ | Spricht mit Core/Engine |
| Design (Dark/Light/System) | ✅ | Highlight-Farbe via Farbrad änderbar |
| Einstellungen (alle Bereiche) | ✅ | Sprache/Design/Modelle/Benutzer/API/Plugins/Datenschutz |
| Admin-Dashboard | ✅ | Status, Benchmark, Audit, Benutzer- & Modell-Verwaltung (Anlegen/Löschen/Passwort-Reset/Deaktivieren) |
| Verschlüsselung & Auth | ✅ | AES-256-GCM (Chat), Argon2id (Passwörter), Token-Session |
| CORS / Netzwerk | ✅ | `CorsLayer::very_permissive()`, `--host 0.0.0.0` für Netzwerk-Bindung |
| Schwarm-Modus / Ziel-Agent / Prompt-Verfeinerer | 🔌 | UI-Platzhalter, Schnittstelle vorbereitet |
| Node-Verwaltung / Training | 🔌 | Dashboard-Stubs, Engine-seitig nicht angebunden |
| LLM Engine | 🔌 | Python-Adapter vorhanden, Stub aktiv bis Engine verbunden |

> ✅ = implementiert & build-/smoke-verifiziert · 🔌 = Schnittstelle vorbereitet, nicht vollständig angebunden

## Smoke-Test-Ergebnisse (verifiziert)
- `GET /api/auth/status` → first_start, version
- `POST /api/auth/login` (Admin/1234) → token, must_change_password=true
- `POST /api/auth/setup` → ersetzt Default-Admin, neuer token
- `POST /api/sessions` → Session erstellt
- `POST /api/sessions/:id/messages` → Stub-Antwort
- `POST /api/admin/benchmark` → Tokens/s, Latenz
- `GET /api/engine/health` → engine: stub, status: Ok
- Test-User mit `expires_at` (Unix-Sekunden) erstellt und aufgelistet
- `cargo build` workspace kompiliert; `cargo test` 10 passed, 2 ignored (Python-Engine)
- `flutter analyze` — No issues found; `flutter build web` erfolgreich; Desktop-Scaffolds (windows/linux/macos/web) generiert
