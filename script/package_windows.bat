@echo off
setlocal
cd /d "%~dp0.."

set MODE=--onedir
if /i "%~1"=="onefile" set MODE=--onefile

echo [1/5] Building claude-proxy-rust...
call script\build_claude_proxy.bat || exit /b 1

echo [2/5] Building frontend...
pushd frontend
call npm run build || (popd & exit /b 1)
popd

echo [3/5] Stopping old Xalling process...
taskkill /IM Xalling.exe /T /F >nul 2>&1

echo [4/5] Building Xalling with PyInstaller...
uv run pyinstaller --noconfirm %MODE% --windowed --name Xalling ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "tutorials;tutorials" ^
    --add-binary "plugins/bin/claude-proxy-rust.exe;plugins/bin" ^
    --collect-data claude_agent_sdk ^
    --collect-all clr_loader ^
    --hidden-import clr ^
    main.py || exit /b 1

echo [5/5] Done. The package is in dist\Xalling
exit /b 0
