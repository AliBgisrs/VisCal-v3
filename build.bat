@echo off
setlocal

REM Activate venv if present
if exist .venv\Scripts\activate.bat call .venv\Scripts\activate.bat

REM Verify Python is reachable
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not on PATH. Install Python 3.10 or 3.11 and re-run setup_env.bat.
    exit /b 1
)

REM Make sure PyInstaller is installed
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        exit /b 1
    )
)

REM Clean previous artifacts
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

REM Build using the spec file
python -m PyInstaller --noconfirm viscalc.spec
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    exit /b 1
)

echo.
echo Build complete: dist\VIScalculator.exe
endlocal
