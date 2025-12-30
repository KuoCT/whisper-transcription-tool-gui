@echo off
setlocal
cd /d "%~dp0"

call install-uv.bat

where git >nul 2>&1
if %errorlevel% neq 0 (
  echo git not found. Please install Git first.
  exit /b 1
)

git pull --rebase
if %errorlevel% neq 0 exit /b %errorlevel%

uv sync
if %errorlevel% neq 0 exit /b %errorlevel%

call run-app.bat
