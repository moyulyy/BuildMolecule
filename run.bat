@echo off
setlocal
cd /d "%~dp0"

rem Prefer pythonw.exe from the venv: GUI launch without a console window.
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.pyw"
    exit /b 0
)

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe "main.pyw"
    exit /b 0
)

rem Fallback: no pythonw available, use python (console visible for debugging).
python main.py
if errorlevel 1 pause
endlocal
