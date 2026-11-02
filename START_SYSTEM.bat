@echo off
title Universal AI Trading Platform - Launcher
color 0B
cls
echo ======================================================================
echo       UNIVERSAL AI MULTI-ASSET TRADING INTELLIGENCE SYSTEM
echo ======================================================================
echo.
echo [1/3] Checking MetaTrader 5 Terminal status...
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I /N "terminal64.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] MetaTrader 5 is already running.
) else (
    echo [INFO] Starting MetaTrader 5 terminal...
    if exist "C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe" (
        start "" "C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe"
        timeout /t 3 /nobreak >nul
    ) else (
        echo [NOTICE] Default MT5 path not found. Please start MT5 manually.
    )
)

echo.
echo [2/3] Initializing Python Trading Intelligence Engine & Bridge Server...
cd /d "D:\Tradinig system"

echo [3/3] Opening Interactive Visual Dashboard at http://127.0.0.1:8050 ...
echo.
python run_system.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] System stopped with exit code %ERRORLEVEL%.
    pause
)
