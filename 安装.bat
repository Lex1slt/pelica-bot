@echo off
chcp 65001 >nul
title 佩丽卡监督 - 一键安装
cd /d "%~dp0"

echo == 1/4 检查 Python ==
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python，请安装 3.10 或更高版本，安装时勾选 Add to PATH
  echo 下载地址：https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
for /f "tokens=2 delims= " %%i in ('%PY% --version 2^>^&1') do echo   使用 Python %%i

echo == 2/4 创建虚拟环境 ==
if not exist .venv\Scripts\python.exe (
  %PY% -m venv .venv
  if errorlevel 1 (echo [错误] venv 创建失败 & pause & exit /b 1)
) else (
  echo   .venv 已存在，跳过
)

echo == 3/4 安装依赖（首次约 1-3 分钟，取决于网速）==
.venv\Scripts\python.exe -m pip install -U pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo [错误] 依赖安装失败，请检查网络后重试
  pause
  exit /b 1
)

echo == 4/4 生成配置 ==
if not exist .env (
  copy .env.example .env >nul
  echo   已生成 .env —— 请用记事本打开，填入你的 DEEPSEEK_API_KEY（必填）
) else (
  echo   .env 已存在，跳过
)

echo.
if exist data\pelica.db (
  echo 数据库就绪：data\pelica.db
) else (
  echo [提示] 未找到语料数据库 data\pelica.db，二选一：
  echo   方式A（推荐）：到本项目 Release 下载「pelica.db 预构建包」，解压出
  echo           pelica.db 放进 data\ 文件夹
  echo   方式B：自行获取 PRTS-Terrachive 语料 release，放进 corpus\releases\ 后运行
  echo           .venv\Scripts\python.exe scripts\build_db.py
)

echo.
echo ============================================
echo   安装完成！接下来：
echo   1. 记事本打开 .env 填 DEEPSEEK_API_KEY
echo   2. 按 快速开始-Windows.txt 装好微信 4.1.10.27 和 version.dll
echo   3. 双击 启动机器人.bat 上线（没装微信可先双击 mock体验.bat）
echo ============================================
pause
