@echo off
chcp 65001 >nul
title 佩丽卡监督 - mock 体验（不需要微信）
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  echo [错误] 尚未安装：请先双击 安装.bat
  pause
  exit /b 1
)
if not exist data\pelica.db (
  echo [错误] 缺少语料数据库 data\pelica.db：见 快速开始-Windows.txt
  pause
  exit /b 1
)

.venv\Scripts\python.exe scripts\run_mock_chat.py
pause
