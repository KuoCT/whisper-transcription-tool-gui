@echo off
setlocal
cd /d "%~dp0"

set "RELAUNCH=0"
if /i "%~1"=="--relaunch" set "RELAUNCH=1"

call install-uv.bat
if %errorlevel% neq 0 exit /b %errorlevel%

where git >nul 2>&1
if %errorlevel% neq 0 (
  echo git not found. Please install Git first.
  exit /b 1
)

git pull --rebase
if %errorlevel% neq 0 exit /b %errorlevel%

uv sync
if %errorlevel% neq 0 exit /b %errorlevel%

if %RELAUNCH%==1 (
  start "" /b "%~dp0whisper-transcription-tool-gui.bat"
  exit /b 0
)

call run-app.bat
