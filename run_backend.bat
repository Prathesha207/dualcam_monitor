@echo off
setlocal
title Vision Monitor Backend

echo =======================================================
echo          Starting Camera Service Backend
echo =======================================================
echo.

cd /d "%~dp0backend"

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0backend\.venv\Scripts\python.exe"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
)

echo Using Python: %PYTHON_EXE%
echo Starting server on http://127.0.0.1:8000 ...
echo API Documentation: http://127.0.0.1:8000/docs
echo.

"%PYTHON_EXE%" run.py

if errorlevel 1 (
    echo.
    echo [ERROR] Backend exited with an error.
    pause
)

