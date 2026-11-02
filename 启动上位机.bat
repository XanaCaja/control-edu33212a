@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" goto missing
"%~dp0.venv\Scripts\python.exe" "%~dp0generator_app.py"
if errorlevel 1 pause
exit /b
:missing
echo 未找到项目 Python 环境。
pause
exit /b 1

