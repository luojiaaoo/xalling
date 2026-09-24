@echo off
setlocal
cd /d "%~dp0.."

rem Pinned Claude Code CLI, hosted at https://github.com/luojiaaoo/cc-versions
rem Linux asset naming: claude-%CLAUDE_VERSION%-linux-x64 -> plugins\bin\claude
set CLAUDE_VERSION=2.1.281
set DOWNLOAD_URL=https://github.com/luojiaaoo/cc-versions/releases/download/v%CLAUDE_VERSION%/claude-%CLAUDE_VERSION%-win32-x64.exe
set TARGET=plugins\bin\claude.exe

if not exist "plugins\bin" mkdir "plugins\bin"

rem Already pinned locally: skip the 200MB+ download.
if exist "%TARGET%" (
    "%TARGET%" --version 2>nul | find "%CLAUDE_VERSION%" >nul
    if not errorlevel 1 (
        echo %TARGET% already at pinned version %CLAUDE_VERSION%.
        exit /b 0
    )
)

echo Downloading Claude Code %CLAUDE_VERSION% (win32-x64) to %TARGET%...
curl.exe -L --fail --retry 3 -o "%TARGET%.tmp" "%DOWNLOAD_URL%"
if errorlevel 1 (
    del "%TARGET%.tmp" 2>nul
    echo        Download failed: %DOWNLOAD_URL%
    exit /b 1
)
move /y "%TARGET%.tmp" "%TARGET%" >nul

"%TARGET%" --version 2>nul | find "%CLAUDE_VERSION%" >nul
if errorlevel 1 (
    echo        Downloaded binary does not report version %CLAUDE_VERSION%.
    exit /b 1
)
echo Done: %TARGET%
exit /b 0
