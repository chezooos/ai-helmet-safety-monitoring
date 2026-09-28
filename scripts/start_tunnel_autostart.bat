@echo off
timeout /t 8 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\COM\Desktop\lg\scripts\start_server.ps1"
start "" /MIN "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:5000 --no-autoupdate
