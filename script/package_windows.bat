@echo off
setlocal
cd /d "%~dp0.."

set MODE=--onedir
if /i "%~1"=="onefile" set MODE=--onefile

echo [1/6] Building claude-proxy-rust...
call script\build_claude_proxy.bat || exit /b 1

echo [2/6] Building frontend...
pushd frontend
call npm run build || (popd & exit /b 1)
popd

echo [3/6] Stopping old Xalling process...
taskkill /IM Xalling.exe /T /F >nul 2>&1

echo [4/6] Building Xalling with PyInstaller...
uv run pyinstaller --noconfirm %MODE% --windowed --name Xalling ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "tutorials;tutorials" ^
    --add-binary "plugins/bin/claude-proxy-rust.exe;plugins/bin" ^
    --collect-data claude_agent_sdk ^
    --collect-all clr_loader ^
    --hidden-import clr ^
    main.py || exit /b 1

echo [5/6] Building installer with Inno Setup...
if /i "%MODE%"=="--onefile" goto :skip_installer

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
"%ISCC%" script\xalling.iss || exit /b 1
goto :installer_done

:skip_installer
echo        Skipped: installer packages the --onedir layout. Use the default build.

:installer_done
echo [6/6] Done. Output in dist\:
dir /b dist 2>nul
pause
