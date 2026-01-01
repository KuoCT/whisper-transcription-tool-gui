@echo off
setlocal
cd /d "%~dp0"
call install-uv.bat
if %errorlevel% neq 0 exit /b %errorlevel%
call run-app.bat
