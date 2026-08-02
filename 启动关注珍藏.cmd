@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 首次运行，正在创建环境并安装依赖……
  py -3.12 -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -e ".[browser]"
  ".venv\Scripts\python.exe" -m playwright install chromium
)
".venv\Scripts\python.exe" following_app.py
