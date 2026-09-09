# Shadow Chat — Windows Server (x86_64)

Windows-Paket mit dem **Rust-Server/CLI** (`shadow.exe`).

> Hinweis zur Flutter-UI: Eine native Windows-Flutter-UI (.exe) kann nur auf
> einem Windows-Host mit Visual Studio-Toolchain gebaut werden. Dieses Paket
> enthält daher den Server + CLI. Als UI-Fallback dient `shadow-chat-web-ui`
> (Flutter-Web-Build, im Browser nutzbar, sobald der Server läuft).

## Inhalt

| Pfad | Bedeutung |
|---|---|
| `shadow.exe` | Rust-Server + CLI (PE32+, x86-64) |
| `data\` | Ablage der verschlüsselten SQLite-Daten (wird automatisch angelegt) |
| `start-shadow-server.bat` | Startet den Server auf Port 8787 |

## Start

Entpacken und Doppelklick auf `start-shadow-server.bat`, oder in der
Eingabeaufforderung (PowerShell/cmd):

```cmd
shadow.exe server --host 127.0.0.1 --port 8787 --data-dir .\data
```

Danach läuft die API unter `http://127.0.0.1:8787`.

## UI nutzen (Web-Fallback)

1. Server starten (siehe oben).
2. Das Paket `shadow-chat-web-ui` entpacken und den Ordner `web/` über einen
   lokalen Static-Server ausliefern, z. B.:
   ```bash
   cd web
   python -m http.server 8080
   ```
   (Windows: `py -m http.server 8080`)
3. Browser öffnen: `http://localhost:8080`
4. Die UI verbindet sich per Default mit `http://127.0.0.1:8787`. Die
   Server-Adresse lässt sich in den Einstellungen ändern.

## Erster Login

Beim ersten Start ist der Default-Admin `Admin` / `1234` angelegt. Nach dem
Login wird die Einrichtung eines neuen Admins erzwungen. Alle Chat-Inhalte
werden AES-256-GCM verschlüsselt, Passwörter als Argon2id-Hash gespeichert.

## CLI-Befehle

```cmd
shadow.exe login
shadow.exe chat
shadow.exe users
shadow.exe models
shadow.exe bench
shadow.exe server
```

## Umgebungsvariablen

- `SHADOW_PORT` — Server-Port (Standard 8787, nur für `start-shadow-server.bat`)
- `SHADOW_PASSWORD` — Keystore-Passwort (Standard `dev-only-not-secure`)
- `SHADOW_AI_CMD` — Kommando zur LLM Engine, z. B. `python3 -m shadow_ai`.
  Ohne Angabe läuft der StubAdapter (Modell `shadow-default`).

## Verifikation

- `shadow.exe` ist eine gültige PE32+-Executable für Windows x86-64.
- Funktionsverifikation (Login, Setup, Sessions, Schwarm, Ziel-Agent, Benchmark)
  erfolgte auf dem Linux-Server-Build mit identischem Quellcode.
- Ein Laufzeittest unter Windows selbst wurde in dieser Umgebung nicht
  durchgeführt (kein Windows-Host). Bei Bedarf bitte einmalig
  `shadow.exe server --port 8787` lokal prüfen.
