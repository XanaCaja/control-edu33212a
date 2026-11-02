@echo off
setlocal
chcp 65001 >nul
title EDU33212A 波形发生器控制
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\python.exe" goto missing_python
if not exist "%~dp0edu33212a.py" goto missing_script
if /i "%~1"=="--check" goto check
echo 启动成功。选择 1 可连接发生器并读取设置。
goto menu

:menu
echo.
echo ========= EDU33212A 控制菜单 =========
echo [1] 刷新两路状态
echo [2] 关闭 CH2 输出
echo [3] 查看扫频命令参数
echo [0] 退出
echo 退出窗口不会改变仪器输出状态。
choice /c 1230 /n /m "请选择 [1/2/3/0]："
if errorlevel 4 exit /b 0
if errorlevel 3 goto sweep_help
if errorlevel 2 goto output_off
call :status
goto menu

:output_off
"%~dp0.venv\Scripts\python.exe" "%~dp0edu33212a.py" output --channel 2 --state off
if errorlevel 1 echo 操作失败，请检查仪器电源、USB 连接及错误信息。
goto menu

:sweep_help
"%~dp0.venv\Scripts\python.exe" "%~dp0edu33212a.py" sweep --help
echo.
echo 扫频配置方法请查看同目录的“发生器使用说明.md”。
goto menu

:status
"%~dp0.venv\Scripts\python.exe" "%~dp0edu33212a.py" status
if errorlevel 1 echo 读取失败，请检查仪器电源、USB 连接及错误信息。
exit /b

:check
"%~dp0.venv\Scripts\python.exe" "%~dp0edu33212a.py" status
exit /b %errorlevel%

:missing_python
echo 未找到项目 Python 环境：%~dp0.venv\Scripts\python.exe
pause
exit /b 1

:missing_script
echo 未找到控制程序：%~dp0edu33212a.py
pause
exit /b 1

