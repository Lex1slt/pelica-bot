@echo off
chcp 65001 >nul
title 佩丽卡监督 - 停止
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_bot.ps1"
pause
