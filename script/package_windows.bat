@echo off
setlocal
cd /d "%~dp0.."

if defined APP_VERSION goto validate_app_version
if /i "%CI%"=="true" (
    echo APP_VERSION is required in CI.
    exit /b 1
)
echo.
echo Version format: MAJOR.MINOR.PATCH, without a leading v.
echo   Test release:  1.2.0-beta.1 to 1.2.0-beta.2
echo   Bug fix:       1.2.3 to 1.2.4  - increment PATCH
echo   Minor release: 1.2.4 to 1.3.0  - new compatible features, reset PATCH
echo   Major release: 1.3.2 to 2.0.0  - breaking changes, reset MINOR and PATCH
echo   Use 0.x.x during development; use 1.0.0 for the first stable release.
echo.
set /p "APP_VERSION=Enter APP_VERSION (e.g. 0.1.0): "
if not defined APP_VERSION (
    echo APP_VERSION cannot be empty.
    exit /b 1
)
:validate_app_version
powershell -NoProfile -NonInteractive -Command "if ($env:APP_VERSION -notmatch '^[0-9]+(\.[0-9]+){1,3}([-+][0-9A-Za-z.-]+)?$') { exit 1 }"
if errorlevel 1 (
    echo Invalid APP_VERSION. Use a version such as 0.1.0 or 0.1.0-beta.1.
    exit /b 1
)
echo Packaging Xalling version %APP_VERSION%...

echo [1/7] Building claude-proxy-rust...
call script\build_claude_proxy.bat || exit /b 1

echo [2/7] Fetching Claude Code CLI...
call script\fetch_claude_cli.bat || exit /b 1

echo [3/7] Building frontend...
pushd frontend
call npm run build || (popd & exit /b 1)
popd

echo [4/7] Stopping old Xalling process...
taskkill /IM Xalling.exe /T /F >nul 2>&1
taskkill /IM Xalling-Server.exe /T /F >nul 2>&1

echo [5/7] Building Xalling with PyInstaller...
uv run pyinstaller --noconfirm Xalling.spec || exit /b 1

echo [6/7] Building installer with Inno Setup...
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
"%ISCC%" "/DMyAppVersion=%APP_VERSION%" script\installer_windows.iss || exit /b 1
echo [7/7] Done. Output in dist\:
dir /b dist 2>nul
if /i not "%CI%"=="true" pause
