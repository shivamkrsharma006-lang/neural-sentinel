@echo off
title Neural Sentinel - Cloudflare Tunnel Setup Helper
echo ===================================================
echo   NEURAL SENTINEL - SECURE REMOTE ACCESS HELPER
echo ===================================================
echo.
echo This helper script guides you to securely expose your local Mini-PC
echo Neural Sentinel server to your mobile phone over the internet
echo using Cloudflare Tunnels (zero router port forwarding required).
echo.

:: 1. Check if cloudflared is installed
where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] 'cloudflared' CLI was not found on your system PATH.
    echo.
    echo Please follow these quick steps:
    echo 1. Download the Windows installer from: https://github.com/cloudflare/cloudflared/releases
    echo 2. Install it or add cloudflared.exe to your system PATH environment variables.
    echo 3. Re-run this script once installed.
    echo.
    pause
    exit /b
)

echo [OK] 'cloudflared' CLI is installed on this system.
echo.
echo Please choose an option:
echo [1] Login and Authorize Cloudflare (First-time setup only)
echo [2] Create a new Tunnel named 'neural-sentinel'
echo [3] Run the Secure Tunnel on port 8000
echo [4] Exit
echo.
set /p choice="Enter your choice (1-4): "

if "%choice%"=="1" (
    echo.
    echo Starting Cloudflare login... A browser window should open.
    cloudflared tunnel login
    echo.
    echo Completed login. Re-run this script to create a tunnel.
    pause
    exit /b
)

if "%choice%"=="2" (
    echo.
    echo Creating tunnel 'neural-sentinel'...
    cloudflared tunnel create neural-sentinel
    echo.
    echo Tunnel created successfully!
    echo.
    echo Next step: Associate a subdomain (e.g. sentinel.yourdomain.com) with the tunnel
    echo inside your Cloudflare Dashboard, pointing to http://localhost:8000.
    echo.
    pause
    exit /b
)

if "%choice%"=="3" (
    echo.
    echo Starting tunnel 'neural-sentinel' routing to http://localhost:8000...
    echo (Press Ctrl+C to terminate the tunnel session)
    echo.
    cloudflared tunnel run --url http://localhost:8000 neural-sentinel
    pause
    exit /b
)

if "%choice%"=="4" (
    exit /b
)

echo Invalid choice.
pause
