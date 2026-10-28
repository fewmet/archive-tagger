@echo off
title Local Files Tagger
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto run

echo First run: setting up Local Files Tagger (takes a minute, only happens once)...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo.
  echo Python wasn't found. Install it from python.org ^(tick "Add python.exe to PATH"^), then run this again.
  pause
  exit /b 1
)
%PY% -m venv .venv
if errorlevel 1 (
  echo Couldn't create the Python environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installing the tagging libraries failed. Check your internet and run this again.
  rmdir /s /q .venv
  pause
  exit /b 1
)
rem the app window; if this fails the tagger opens in your browser instead
".venv\Scripts\python.exe" -m pip install pywebview
echo Done.

:run
start "" ".venv\Scripts\pythonw.exe" app.py
