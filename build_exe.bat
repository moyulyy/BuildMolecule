@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Build a portable one-folder application: dist\MK-MOLE\MK-MOLE.exe
rem Fast startup (no one-file extraction). CHGNet is installed separately
rem into dist\MK-MOLE\chgnet_env by install_chgnet.bat.

python -m pip install --disable-pip-version-check pyinstaller
python -m PyInstaller --noconfirm --clean MK-MOLE.spec
if errorlevel 1 goto :fail

if not exist "dist\MK-MOLE\MK-MOLE.exe" goto :fail

copy /Y "install_chgnet.bat" "dist\MK-MOLE\" >nul
copy /Y "requirements-chgnet.txt" "dist\MK-MOLE\" >nul
copy /Y "README.md" "dist\MK-MOLE\" >nul
copy /Y "LICENSE" "dist\MK-MOLE\" >nul
copy /Y "THIRD_PARTY_NOTICES.md" "dist\MK-MOLE\" >nul
if exist "docs" xcopy /E /I /Y "docs" "dist\MK-MOLE\docs" >nul
rem Remove the old one-file build if present, to avoid confusion.
if exist "dist\MK-MOLE.exe" del /Q "dist\MK-MOLE.exe"

echo.
echo ============================================================
echo  Portable folder ready:
echo    %CD%\dist\MK-MOLE\MK-MOLE.exe
echo  To enable CHGNet, run install_chgnet.bat inside that folder.
echo ============================================================
if not defined MK_MOLE_NO_PAUSE pause
exit /b 0

:fail
echo [ERROR] PyInstaller build failed.
if not defined MK_MOLE_NO_PAUSE pause
exit /b 1
