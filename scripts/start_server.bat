@echo off
REM Keep AI helmet monitoring server running
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_server.ps1"
