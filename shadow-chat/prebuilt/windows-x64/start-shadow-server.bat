@echo off
REM Startet den Shadow-Server (Rust) auf Port 8787.
REM Hinweis: Die native Windows-Flutter-UI muss auf einem Windows-Host mit
REM Visual Studio gebaut werden. Als UI-Fallback dient shadow-chat-web-ui
REM (im Browser unter http://127.0.0.1:8787 erreichbar, sobald der Server läuft).
setlocal
set "HERE=%~dp0"
set "PORT=8787"
if not "%SHADOW_PORT%"=="" set "PORT=%SHADOW_PORT%"
if not exist "%HERE%data" mkdir "%HERE%data"
echo ] Starte Shadow-Server auf http://127.0.0.1:%PORT% ...
"%HERE%shadow.exe" server --host 127.0.0.1 --port %PORT% --data-dir "%HERE%data"
endlocal
