@echo off
REM ============================================================================
REM  Net Blocker Build Script
REM  Creates a standalone .exe using PyInstaller + conda env
REM ============================================================================

set ENV_NAME=netblocker_build

echo [1/5] Creating conda environment...
call conda create -n %ENV_NAME% python=3.11 -y
if errorlevel 1 (
    echo ERROR: Failed to create conda environment.
    pause
    exit /b 1
)

echo [2/5] Activating environment...
call conda activate %ENV_NAME%

echo [3/5] Installing dependencies...
pip install psutil pynput customtkinter pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo [4/5] Building exe...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "NetBlocker" ^
    --icon=icon.ico ^
    --uac-admin ^
    --collect-all customtkinter ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import pynput.mouse._win32 ^
    --hidden-import pynput._util ^
    --hidden-import pynput._util.win32 ^
    --add-data "icon.ico;." ^
    net_blocker.pyw

if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo [5/5] Cleaning up...
rmdir /s /q build 2>nul
del /q NetBlocker.spec 2>nul

echo.
echo ============================================
echo   Build complete!
echo   Output: dist\NetBlocker.exe
echo ============================================
echo.
pause
