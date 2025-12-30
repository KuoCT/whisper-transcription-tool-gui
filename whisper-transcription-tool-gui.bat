@echo off
setlocal
cd /d "%~dp0"
call install-uv.bat
call run-app.bat
