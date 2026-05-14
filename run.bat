@echo off
setlocal
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo [WARN] No .venv found. Run setup_env.bat first if dependencies are missing.
)
python app.py
endlocal
