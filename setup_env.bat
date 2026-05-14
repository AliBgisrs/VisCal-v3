@echo off
setlocal

REM One-time environment setup. Run from this folder.
REM Requires Python 3.10 or 3.11 already installed and on PATH.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not on PATH. Install Python 3.10 or 3.11 first.
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment in .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed.
    exit /b 1
)

pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency install failed. See message above.
    exit /b 1
)

echo.
echo Environment ready.
echo   Activate later:  call .venv\Scripts\activate.bat
echo   Run the app:     run.bat
echo   Build the exe:   build.bat
endlocal
