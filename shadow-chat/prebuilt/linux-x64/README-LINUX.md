# Shadow Chat — Linux (x86_64)

Komplett-Paket für Linux: **Rust-Server/CLI** (`shadow`, statisch gelinkt) +
**Flutter-UI** (Desktop-Binary).

## Inhalt

| Pfad | Bedeutung |
|---|---|
| `server/shadow` | Rust-Server + CLI (statisch gelinkt, keine glibc-Abhängigkeit) |
| `ui/shadow_chat` | Flutter-Desktop-UI (GTK) + `lib/`, `data/` |
| `data/` | Ablage der verschlüsselten SQLite-Daten (wird automatisch angelegt) |
| `start-shadow.sh` | Startet Server + UI gemeinsam |

## Start

```bash
chmod +x start-shadow.sh
./start-shadow.sh
```

Das Skript startet den Server auf `http://127.0.0.1:8787`, wartet bis er
bereit ist und öffnet dann die Flutter-UI. Beim Schließen der UI wird auch der
Server beendet.

Alternativ nur den Server starten:

```bash
./server/shadow server --port 8787 --data-dir ./data
```

## Erster Login

Beim ersten Start ist der Default-Admin `Admin` / `1234` angelegt. Nach dem
Login wird die Einrichtung eines neuen Admins erzwungen (Benutzername,
Passwort, optionale E-Mail, optionales Kill-Switch-Passwort). Alle Chat-Inhalte
werden AES-256-GCM verschlüsselt, Passwörter als Argon2id-Hash gespeichert.

## Chat-Funktionen

- **Modell-Dropdown** unten rechts (spricht mit der Engine)
- **Chat-Menü** (Hub-Symbol): **Schwarm-Modus** (Multiple-Agenten-Antwort mit
  Synthese), **Ziel-Agent** (Antwort über ein bestimmtes Modell), Prompt-Verfeinerer (Stub)
- Markdown-Rendering, Code-Blöcke, Chat-Historien-Sidebar (umbenennen/löschen/zusammenführen)

> Die Schwarm-Synthese ist deterministisch (Markdown-Konkatenation). Sobald die
> Shadow LLM Engine angebunden ist, kann sie durch eine echte modellbasierte
> Konsolidierung ersetzt werden — die API-Oberfläche bleibt identisch.

## Systemvoraussetzungen

- Linux x86_64
- Flutter-Linux-Runtime: GTK 3, libstdc++, liblzma. Auf Ubuntu/Debian:
  ```bash
  sudo apt-get install -y libgtk-3-0 libstdc++6 liblzma5
  ```
- Der Server ist statisch gelinkt (Musl) und hat keine glibc-Versionsbindung.

## CLI-Befehle

```bash
./server/shadow login
./server/shadow chat
./server/shadow users
./server/shadow models
./server/shadow bench
./server/shadow server
```

## Umgebungsvariablen

- `SHADOW_PORT` — Server-Port (Standard 8787, nur für `start-shadow.sh`)
- `SHADOW_PASSWORD` — Keystore-Passwort (Standard `dev-only-not-secure`)
- `SHADOW_AI_CMD` — Kommando zur LLM Engine, z. B. `python3 -m shadow_ai`.
  Ohne Angabe läuft der StubAdapter (Modell `shadow-default`).

## Netzwerk-Betrieb

Der Server lauscht standardmäßig nur lokal. Für Netzwerk-Zugriff:
`./server/shadow server --host 0.0.0.0 --port 8787`. CORS ist aktiviert.
