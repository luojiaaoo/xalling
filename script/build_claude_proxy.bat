@echo off
setlocal
cd /d "%~dp0.."

set SOURCE_DIR=plugins\claude-proxy-rust
set OUTPUT_DIR=plugins\bin
set OUTPUT=%OUTPUT_DIR%\claude-proxy-rust.exe

if not exist "%SOURCE_DIR%\Cargo.toml" (
    echo claude-proxy-rust submodule not found. Run:
    echo git submodule update --init --recursive
    exit /b 1
)

where cargo >nul 2>&1
if errorlevel 1 (
    echo cargo not found. Install the Rust toolchain and retry.
    exit /b 1
)

echo Building claude-proxy-rust...
cargo build --manifest-path "%SOURCE_DIR%\Cargo.toml" --release
if errorlevel 1 exit /b 1

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
copy /Y "%SOURCE_DIR%\target\release\claude-proxy-rust.exe" "%OUTPUT%" >nul
if errorlevel 1 (
    echo Failed to copy the compiled binary to %OUTPUT%
    exit /b 1
)

echo Generated %OUTPUT%
exit /b 0
