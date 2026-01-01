@echo off
setlocal

where uv >nul 2>&1
if %errorlevel%==0 (
  exit /b 0
)

echo Installing uv...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo uv installed. Please re-run whisper-transcription-tool-gui.bat to continue.
echo.
pause
exit /b 1
