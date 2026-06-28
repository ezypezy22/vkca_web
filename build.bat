@echo off
REM ═══════════════════════════════════════════════════════════════════════════
REM  VK Contest Analyzer — Build Script
REM  Run from the folder containing vkca_web.spec and contest_log.py
REM  i.e. the vkca_web\ folder you extracted
REM ═══════════════════════════════════════════════════════════════════════════
setlocal

echo.
echo  VK Contest Analyzer - PyInstaller Build
echo  ========================================
echo.

REM ── Check we are in the right folder ──────────────────────────────────────
if not exist "vkca_web.spec" (
    echo [ERROR] vkca_web.spec not found.
    echo         Run build.bat from the vkca_web\ folder.
    pause & exit /b 1
)
if not exist "web\server.py" (
    echo [ERROR] web\server.py not found.
    echo         Make sure the web\ folder is in the same directory as build.bat.
    pause & exit /b 1
)

REM ── Python check ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ and add to PATH.
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Python: %%v

REM ── Create hooks folder if missing ────────────────────────────────────────
if not exist "hooks" mkdir hooks

if not exist "hooks\rthook_multiprocessing.py" (
    echo  Creating hooks\rthook_multiprocessing.py...
    (
        echo import multiprocessing
        echo import sys
        echo if sys.platform == 'win32':
        echo     multiprocessing.freeze_support^(^)
    ) > hooks\rthook_multiprocessing.py
)

if not exist "hooks\hook-uvicorn.py" (
    echo  Creating hooks\hook-uvicorn.py...
    (
        echo from PyInstaller.utils.hooks import collect_submodules, collect_data_files
        echo hiddenimports = collect_submodules^('uvicorn'^)
        echo datas = collect_data_files^('uvicorn'^)
    ) > hooks\hook-uvicorn.py
)

REM ── Install dependencies ───────────────────────────────────────────────────
echo.
echo [1/3] Installing dependencies...
pip install --upgrade pyinstaller pyinstaller-hooks-contrib --quiet
pip install -r requirements.txt --quiet
pip install -r web\requirements-web.txt --quiet
echo       Done.

REM ── Clean ──────────────────────────────────────────────────────────────────
echo [2/3] Cleaning previous build...
if exist "dist\VKContestAnalyzer" rmdir /s /q "dist\VKContestAnalyzer"
if exist "build\VKContestAnalyzer" rmdir /s /q "build\VKContestAnalyzer"
echo       Done.

REM ── Build ──────────────────────────────────────────────────────────────────
echo [3/3] Building (this takes 2-5 minutes first time)...
echo.
pyinstaller vkca_web.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check the output above.
    pause & exit /b 1
)

echo.
echo  ========================================
echo   BUILD COMPLETE
echo   dist\VKContestAnalyzer\VKContestAnalyzer.exe
echo  ========================================
echo.

REM ── Optional ZIP ──────────────────────────────────────────────────────────
set /p MAKEZIP="Create distributable ZIP? (y/n): "
if /i "%MAKEZIP%"=="y" (
    powershell -Command "Compress-Archive -Path 'dist\VKContestAnalyzer' -DestinationPath 'dist\VKContestAnalyzer_release.zip' -Force"
    echo  Created: dist\VKContestAnalyzer_release.zip
)

pause
