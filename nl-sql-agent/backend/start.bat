@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
if "%API_PORT%"=="" set API_PORT=8000
uvicorn agent.main:app --reload --port %API_PORT%
