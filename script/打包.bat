@echo off
setlocal
cd /d "%~dp0.."

rem 用法：双击打包（目录模式）；命令行传 onefile 参数则打单文件
rem 注意：claude-agent-sdk 自带 210MB 的 claude.exe，单文件模式每次启动都要解压，首启很慢
set MODE=--onedir
if /i "%~1"=="onefile" set MODE=--onefile

echo [1/5] 构建前端...
pushd frontend
call npm run build || goto fail
popd

echo [2/5] 结束正在运行的旧实例...
rem 否则 dist 里的 exe 被占用，下面删不掉旧产物，PyInstaller 会打包出一份残缺的产物
taskkill /IM Xalling.exe /T /F >nul 2>&1

echo [3/5] 清理旧产物...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist dist (
    echo.
    echo 打包失败：dist 目录删不掉，多半是有 Xalling.exe 还在占用，请手动结束后再试
    goto fail
)

echo [4/5] PyInstaller 打包...
rem --add-data "源目录;包内目录" 里，包内目录要和代码中读文件的相对路径一致
rem --collect-data claude_agent_sdk 收下它自带的 claude.exe
rem --collect-all clr_loader --hidden-import clr 是 pywebview 的 windows 后端依赖
uv run pyinstaller --noconfirm %MODE% --windowed --name Xalling ^
    --add-data "frontend/dist;frontend/dist" ^
    --add-data "tutorials;tutorials" ^
    --collect-data claude_agent_sdk ^
    --collect-all clr_loader ^
    --hidden-import clr ^
    main.py || goto fail

echo [5/5] 清理中间文件...
rem 只保留 dist 产物；build/ 是 PyInstaller 的中间目录，Xalling.spec 是它自动生成的
if exist build rmdir /s /q build
if exist Xalling.spec del /q Xalling.spec

echo.
echo 打包完成，产物在 dist 目录
pause
exit /b 0

:fail
echo.
echo 打包失败，请看上面的报错
pause
exit /b 1
