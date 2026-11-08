@echo off
rem Starts the API (port 8765) and the React dev server (port 5173), then opens the app.
cd /d "%~dp0"
if not exist frontend\node_modules (cd frontend && call npm install && cd ..)
start "Resume Studios API" cmd /k "cd backend && python -m uvicorn app.main:app --port 8765 --reload"
start "Resume Studios Web" cmd /k "cd frontend && npm run dev"
timeout /t 4 >nul
start "" http://localhost:5173
