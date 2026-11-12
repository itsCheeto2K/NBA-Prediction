@echo off
if /i "%~1"=="--run" goto setup
start "NBA Dashboard" "%ComSpec%" /d /k ""%~f0" --run"
exit /b

:setup
setlocal
cd /d "%~dp0"
title NBA Dashboard - Ctrl+C to stop
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"

if not exist "run_app.py" (
    echo [ERROR] Put this BAT file in the same folder as run_app.py.
    exit /b 1
)

rem Prefer the project's virtual environment, then installed Python.
for %%P in (".venv\Scripts\python.exe" "venv\Scripts\python.exe" "..\.venv\Scripts\python.exe" "..\venv\Scripts\python.exe") do (
    if exist "%%~P" (
        set "APP_PYTHON=%%~fP"
        goto run
    )
)
python -c "import sys; sys.exit(sys.version_info.major != 3)" >nul 2>&1
if not errorlevel 1 (
    set "APP_PYTHON=python"
    goto run
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "APP_PYTHON=py"
    goto run
)
echo [ERROR] Python 3 was not found. Install Python or use the project venv.
exit /b 1

:run
echo.
echo Starting dashboard: http://localhost:8000
echo Press Ctrl+C, then Y and Enter to stop this batch.
echo Answer N to restart the app after interruption.
echo.
if /i "%APP_PYTHON%"=="py" (
    py -3 -u "%~dp0run_app.py"
) else (
    "%APP_PYTHON%" -u "%~dp0run_app.py"
)
echo.
echo App exited with code %errorlevel%. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto run
