@echo off
REM One-time environment setup. Run from this folder.
REM Requires Python 3.10 or 3.11 already installed and on PATH.

python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Environment ready. To activate later: call .venv\Scripts\activate.bat
echo To run the app:   python app.py
echo To build the exe: build.bat
