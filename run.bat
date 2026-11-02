@echo off
setlocal
title Vision Monitor

echo =======================================================
echo          Starting Vision Monitor Development Mode
echo =======================================================
echo.

cd /d "%~dp0"

REM 1. Locate Backend Directory
set "BACKEND_DIR=%~dp0backend"
if not exist "%BACKEND_DIR%" (
    if exist "%~dp0vision-ai-backend" (
        set "BACKEND_DIR=%~dp0vision-ai-backend"
    )
)

REM 2. Locate Python Interpreter (.venv or system Python)
set "PYTHON_CMD="
if exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%BACKEND_DIR%\.venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%~dp0.venv\Scripts\python.exe"
) else (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_CMD=python"
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Python environment was not found.
    echo Please install Python 3.10+ or run setup.bat.
    pause
    exit /b 1
)

REM 3. Verify Required Packages
"%PYTHON_CMD%" -c "import uvicorn, fastapi, cv2" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Required backend packages uvicorn, fastapi, cv2 are missing or not working.
    echo Run setup.bat to install the Python dependencies, then run run.bat again.
    pause
    exit /b 1
)

REM 4. Locate Frontend Directory
set "FRONTEND_DIR="
if exist "%~dp0frontend\package.json" (
    set "FRONTEND_DIR=%~dp0frontend"
) else if exist "%~dp0vision-ai-frontend\package.json" (
    set "FRONTEND_DIR=%~dp0vision-ai-frontend"
) else (
    echo [ERROR] Could not find frontend\package.json.
    pause
    exit /b 1
)

REM 5. Locate npm
if exist "%LOCALAPPDATA%\Programs\node-v20.18.0-win-x64\npm.cmd" (
    set "PATH=%LOCALAPPDATA%\Programs\node-v20.18.0-win-x64;%PATH%"
)
if exist "%ProgramFiles%\nodejs\npm.cmd" (
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
)
if exist "%ProgramFiles(x86)%\nodejs\npm.cmd" (
    set "PATH=%ProgramFiles(x86)%\nodejs;%PATH%"
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm.cmd was not found.
    echo Install Node.js or run setup.bat to install Node.js.
    pause
    exit /b 1
)

REM 6. Free Ports 8000 & 5173 if lingering
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5173 ^| findstr LISTENING 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

REM 7. Start Backend API
echo [1/2] Starting Vision Monitor Backend API (Port 8000)...
start "Vision Monitor - Backend API" /d "%BACKEND_DIR%" cmd /k ""%PYTHON_CMD%" -m uvicorn app.main:app --reload --reload-dir app --host 127.0.0.1 --port 8000 --no-use-colors"
if errorlevel 1 (
    echo [ERROR] Could not start the backend console.
    pause
    exit /b 1
)

REM 8. Start Frontend UI
echo [2/2] Starting Vision Monitor Frontend UI (Port 5173)...
start "Vision Monitor - Frontend UI" /d "%FRONTEND_DIR%" cmd /k "npm.cmd run dev"
if errorlevel 1 (
    echo [ERROR] Could not start the frontend console.
    pause
    exit /b 1
)

echo.
echo =======================================================
echo [SUCCESS] Development servers are starting up!
echo.
echo   • Frontend Application : http://localhost:5173
echo   • Backend Health Check : http://localhost:8000/health
echo   • API Documentation    : http://localhost:8000/docs
echo =======================================================
echo.
