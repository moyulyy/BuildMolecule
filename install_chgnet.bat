@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo  MK-MOLE - CHGNet relaxation environment installer
echo ============================================================
echo.

set "VENV=%~dp0chgnet_env"
set "CPY=%VENV%\Scripts\python.exe"

rem ------------------------------------------------------------------
rem 1. Find a Python 3.10-3.12 base interpreter (torch has no 3.14
rem    wheels on many CUDA builds). Prefer the local Miniconda Python.
rem ------------------------------------------------------------------
set "BASE_PY="
if exist "%ProgramData%\miniconda3\python.exe" set "BASE_PY=%ProgramData%\miniconda3\python.exe"
if not defined BASE_PY if exist "%USERPROFILE%\miniconda3\python.exe" set "BASE_PY=%USERPROFILE%\miniconda3\python.exe"

if defined BASE_PY (
    echo [PY] Using %BASE_PY%
) else (
    echo [PY] No local Miniconda found, trying the py launcher...
    py -3.11 --version >nul 2>nul && set "BASE_CMD=py -3.11"
    if not defined BASE_CMD py -3.12 --version >nul 2>nul && set "BASE_CMD=py -3.12"
    if not defined BASE_CMD py -3.10 --version >nul 2>nul && set "BASE_CMD=py -3.10"
    if not defined BASE_CMD (
        echo [ERROR] Python 3.10-3.12 was not found.
        echo         Install Miniconda or Python 3.10/3.11/3.12 and run this again.
        if not defined MK_MOLE_NO_PAUSE pause
        exit /b 1
    )
)

if not exist "%CPY%" (
    echo [ENV] Creating %VENV%
    if defined BASE_PY (
        "%BASE_PY%" -m venv "%VENV%"
    ) else (
        %BASE_CMD% -m venv "%VENV%"
    )
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        if not defined MK_MOLE_NO_PAUSE pause
        exit /b 1
    )
) else (
    echo [ENV] Reusing existing %VENV%
)

rem ------------------------------------------------------------------
rem 2. Detect NVIDIA GPU / driver and select a CUDA PyTorch wheel.
rem ------------------------------------------------------------------
set "TORCH_INDEX=https://download.pytorch.org/whl/cpu"
set "GPU_LABEL=CPU"
where nvidia-smi >nul 2>nul
if not errorlevel 1 (
    rem An NVIDIA GPU with a working driver was detected. CUDA 12.1 wheels are
    rem compatible with current 12.x drivers (including 560.x); use cu118 for
    rem older drivers by editing this line if needed.
    set "TORCH_INDEX=https://download.pytorch.org/whl/cu121"
    set "GPU_LABEL=NVIDIA GPU / CUDA 12.1"
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>nul
) else (
    echo [CPU] No NVIDIA GPU detected; installing the CPU build of PyTorch.
)

echo [TORCH] %GPU_LABEL%
echo [TORCH] index: %TORCH_INDEX%

"%CPY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo [TORCH] Installing PyTorch...
"%CPY%" -m pip install torch --index-url %TORCH_INDEX%
if errorlevel 1 goto :fail

echo [CHGNET] Installing CHGNet and dependencies...
"%CPY%" -m pip install -r "%~dp0requirements-chgnet.txt"
if errorlevel 1 goto :fail

echo.
echo [VERIFY] Checking the installed environment...
"%CPY%" -c "import torch, chgnet, pymatgen, ase; print('torch', torch.__version__, '| cuda', torch.cuda.is_available()); print('chgnet', chgnet.__version__); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu')"
if errorlevel 1 goto :fail

if not exist "%~dp0data" mkdir "%~dp0data"
> "%~dp0data\chgnet_python.txt" echo %CPY%

echo.
echo ============================================================
echo  CHGNet environment ready:
echo    %CPY%
echo  The app will detect %VENV% automatically.
echo ============================================================
if not defined MK_MOLE_NO_PAUSE pause
exit /b 0

:fail
echo.
echo [ERROR] CHGNet environment installation failed.
echo         Check your network and Python installation, then run again.
if not defined MK_MOLE_NO_PAUSE pause
exit /b 1
