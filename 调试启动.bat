@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动华华（调试窗口）...
python "%~dp0main.py"
if errorlevel 1 pause
