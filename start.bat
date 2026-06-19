@echo off
title Neural Sentinel
color 0A

echo ============================================================
echo  Neural Sentinel v3.0  -  AI Surveillance Platform
echo ============================================================
echo.

REM ── Resolve our root directory (no trailing backslash issues)
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM ── Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause
    exit /b
)

REM ── Create venv if missing
if not exist "%ROOT%\backend\venv" (
    echo [1/3] Creating Python virtual environment...
    python -m venv "%ROOT%\backend\venv"
    echo [2/3] Installing backend dependencies...
    "%ROOT%\backend\venv\Scripts\pip" install -r "%ROOT%\backend\requirements.txt"
    echo.
)

REM ── Copy .env if missing
if not exist "%ROOT%\backend\.env" (
    copy "%ROOT%\backend\.env.example" "%ROOT%\backend\.env" >nul
    echo [INFO] Created backend\.env - edit it to add alert keys.
    echo.
)

REM ── Start backend in a new window that stays open on error
echo [3/3] Starting backend on http://localhost:8000 ...
start "Neural Sentinel Backend" cmd /k "cd /d "%ROOT%\backend" && call venv\Scripts\activate.bat && python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info || (echo. & echo [ERROR] Backend failed to start! Check the error above. & pause)"

REM ── Wait for backend to initialize (8 seconds)
echo Waiting for backend to initialize (8 seconds)...
ping -n 9 127.0.0.1 >nul

REM ── Start frontend
where node >nul 2>&1
if errorlevel 1 (
    echo.
    echo [WARN] Node.js not found. Frontend will not start.
    echo Download from: https://nodejs.org/en/download
    echo Backend is running at: http://localhost:8000
) else (
    if not exist "%ROOT%\frontend\node_modules" (
        echo Installing frontend dependencies...
        cd /d "%ROOT%\frontend"
        call npm install
        cd /d "%ROOT%"
        echo.
    )
    echo Starting frontend on http://localhost:5173 ...
    start "Neural Sentinel Frontend" cmd /k "cd /d "%ROOT%\frontend" && npm run dev || (echo. & echo [ERROR] Frontend failed to start! Check the error above. & pause)"
    REM Wait 4 seconds for Vite to start then open browser
    ping -n 5 127.0.0.1 >nul
    start http://localhost:5173
)

echo.
echo ============================================================
echo  Backend:   http://localhost:8000
echo  Frontend:  http://localhost:5173
echo  API Docs:  http://localhost:8000/docs
echo.
echo  For phone access, run ipconfig to find your LAN IP.
echo  Keep both terminal windows open to keep the system running.
echo ============================================================
echo.
pause
