@echo off
setlocal
cd /d "%~dp0.."

echo [1/6] Building claude-proxy-rust...
call script\build_claude_proxy.bat || exit /b 1

echo [2/6] Building frontend...
pushd frontend
call npm run build || (popd & exit /b 1)
popd

echo [3/6] Stopping old Xalling process...
taskkill /IM Xalling.exe /T /F >nul 2>&1
taskkill /IM Xalling-Server.exe /T /F >nul 2>&1

echo [4/6] Building Xalling with PyInstaller...
call script\fetch_claude_cli.bat || exit /b 1
uv run pyinstaller --noconfirm Xalling.spec || exit /b 1

echo [5/6] Building installer with Inno Setup...
set "ISCC="
for %%P in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
) do if exist "%%~P" if not defined ISCC set "ISCC=%%~P"
if not defined ISCC (
    where ISCC.exe >nul 2>&1
    if not errorlevel 1 set "ISCC=ISCC.exe"
)
if not defined ISCC (
    echo        Inno Setup 6 not found. Install from https://jrsoftware.org/isinfo.php
    echo        then re-run, or set ISCC to the full path of ISCC.exe.
    exit /b 1
)
set "ISCC_VERSION_ARG="
if defined APP_VERSION set "ISCC_VERSION_ARG=/DMyAppVersion=%APP_VERSION%"
"%ISCC%" %ISCC_VERSION_ARG% script\installer_windows.iss || exit /b 1
echo [6/6] Done. Output in dist\:
dir /b dist 2>nul
if /i not "%CI%"=="true" pause
