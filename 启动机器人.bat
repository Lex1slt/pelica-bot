@echo off
chcp 65001 >nul
title 佩丽卡监督
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo [错误] 尚未安装：请先双击 安装.bat
  pause
  exit /b 1
)
if not exist .env (
  echo [错误] 缺少 .env 配置：请双击 安装.bat，或复制 .env.example 为 .env 并填入 DEEPSEEK_API_KEY
  pause
  exit /b 1
)
if not exist data\pelica.db (
  echo [错误] 缺少语料数据库 data\pelica.db：见 快速开始-Windows.txt 的「数据库」一节
  pause
  exit /b 1
)

echo == 启动微信 4.1.10.27（已登录会直接进入）==
set "WEIXIN="
if exist "D:\WeChat\Weixin\Weixin.exe" set "WEIXIN=D:\WeChat\Weixin\Weixin.exe"
if exist "C:\Program Files\Tencent\Weixin\Weixin.exe" set "WEIXIN=C:\Program Files\Tencent\Weixin\Weixin.exe"
if exist "C:\Program Files (x86)\Tencent\Weixin\Weixin.exe" set "WEIXIN=C:\Program Files (x86)\Tencent\Weixin\Weixin.exe"
if exist "D:\WeChat\download\Weixin\Weixin.exe" set "WEIXIN=D:\WeChat\download\Weixin\Weixin.exe"
if defined WEIXIN (
  start "" "%WEIXIN%"
  timeout /t 6 /nobreak >nul
) else (
  echo [提示] 没有自动找到微信，请手动启动微信 4.1.10.27 并登录机器人小号
  timeout /t 6 >nul
)

echo == 启动机器人（等待微信登录后自动上线，日志见 data\bot_live.err.log）==
.venv\Scripts\python.exe main.py --bridge wxhook
pause
