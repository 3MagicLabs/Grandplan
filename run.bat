@echo off
REM grandplan — launch the tray app against your Obsidian vault (native Windows).
REM Edit VAULT to point at your vault. Pass extra flags through, e.g.:  run.bat --model qwen2.5:7b
REM First-time setup is in docs/QUICKSTART-WINDOWS.md.
setlocal

REM --- CONFIGURE: set your vault path here (uncomment + edit), or set VAULT in your environment ---
REM set "VAULT=C:\Users\YourName\OneDrive\Documents\GrandNotes"

if "%VAULT%"=="" set "VAULT=%USERPROFILE%\OneDrive\Documents\GrandNotes"

cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo .venv not found. Run the one-time setup first ^(see docs\QUICKSTART-WINDOWS.md^).
  exit /b 1
)
call ".venv\Scripts\activate.bat"

echo Launching grandplan against: %VAULT%
python -m grandplan gui -o "%VAULT%" --llm --embeddings %*
