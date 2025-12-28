@echo off
set VENV=.venv\Scripts\activate
set GUI=gui.py

:: 啟動虛擬環境
call %VENV%
python %GUI%