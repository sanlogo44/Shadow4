# Shadow Chat — Web-UI

Flutter-Web-Build der Shadow-Chat-Oberfläche. Dient als plattformunabhängiges
UI-Fallback (insbesondere für Windows, wo keine native Flutter-UI gebaut
wurde) und läuft in jedem modernen Browser.

> Voraussetzung: Der **Shadow-Server** muss lokal (oder im Netzwerk) laufen.
> Nutze dafür `shadow-chat-linux-x64` oder `shadow-chat-windows-server-x64`.

## Start

1. **Server starten** (in einem anderen Terminal/Fenster), z. B.:
   ```bash
   shadow server --host 127.0.0.1 --port 8787 --data-dir ./data
   ```
   Unter Windows entsprechend `shadow.exe server …`.

2. **Web-UI ausliefern** aus diesem Ordner:
   ```bash
   cd web
   python -m http.server 8080
   ```
   Unter Windows: `py -m http.server 8080`.

3. **Browser öffnen**: `http://localhost:8080`

Die UI verbindet sich per Default mit `http://127.0.0.1:8787`. Die
Server-Adresse lässt sich auf dem Login-Screen oder in den Einstellungen
ändern (z. B. für Netzwerk-Server `http://<server-ip>:8787`).

## Hinweise

- CORS ist im Server aktiviert, daher funktioniert der Zugriff aus dem Browser.
- Beim Web-Build ist `flutter build web` bereits erfolgt (kein Flutter SDK nötig).
- Für einen produktiven Einsatz empfiehlt sich ein echter Webserver (nginx/caddy)
  statt des Python-Entwicklungsservers.

## Funktionen

Markdown-Rendering, Code-Blöcke, Chat-Historie, Modell-Dropdown,
**Schwarm-Modus** und **Ziel-Agent** (über das Chat-Menü oben rechts).
