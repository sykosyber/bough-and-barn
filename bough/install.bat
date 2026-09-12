@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist pyproject.toml (
  echo Run this from C:\hackathon\bough
  exit /b 1
)
where py >nul 2>&1
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11+ from python.org
  echo and tick "Add python.exe to PATH".
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo git is required: OSAHR is installed from GitHub.
  echo Install Git for Windows, then run this again.
  exit /b 1
)
py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -U pip
python -m pip install -e ".[dev]"
python -m pytest -q
echo.
echo Install ok. Try: python -m bough bits -n 4
exit /b 0
