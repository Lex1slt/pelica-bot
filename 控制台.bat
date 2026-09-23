@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Pelica Console 开发入口

if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到 .venv，请先运行 安装.bat
    pause
    exit /b 1
)
if not exist "console\node_modules" (
    echo [提示] 首次运行：正在安装前端依赖……
    pushd console && call npm install --no-audit --no-fund && popd
)

for /f %%i in ('.venv\Scripts\python -c "import secrets;print(secrets.token_urlsafe(24))"') do set "GW_TOKEN=%%i"
set "PELICA_GATEWAY_PORT=8765"
set "PELICA_GATEWAY_TOKEN=%GW_TOKEN%"

echo [1/2] 启动本地网关（127.0.0.1:8765，token 已注入，日志见 data\logs\gateway.log）……
start "pelica-gateway" /min cmd /c ".venv\Scripts\python -m gateway"

echo [2/2] 启动前端开发服务器并打开浏览器（关闭本窗口即退出开发模式）……
pushd console
call npm run dev:open
popd
