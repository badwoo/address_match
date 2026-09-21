@echo off
chcp 65001 >nul
title 地址匹配系统

:: ====== 自动定位项目目录 ======
:: 方案 A：BAT 放在项目根目录时，%~dp0 就是项目路径
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: 方案 B：BAT 放在别处（如桌面）时，回退到硬编码路径
if not exist "%PROJECT_DIR%\launcher.py" (
    set "PROJECT_DIR=D:\pythonProject\address_match"
)

:: 最终校验
if not exist "%PROJECT_DIR%\launcher.py" (
    echo [错误] 找不到项目目录！
    echo 请把本 BAT 放到项目根目录，或修改本文件中的硬编码路径。
    pause
    exit /b 1
)

cd /d "%PROJECT_DIR%"

echo 项目路径: %PROJECT_DIR%
echo 正在启动...

:: 检查 Python 环境
if not exist "%PROJECT_DIR%\venv\Scripts\python.exe" (
    echo [错误] 找不到虚拟环境 Python：%PROJECT_DIR%\venv\Scripts\python.exe
    pause
    exit /b 1
)

:: ====== 清理可能残留的进程 ======
if exist ".streamlit_pid" (
    for /f %%i in (.streamlit_pid) do (
        taskkill /F /T /PID %%i >nul 2>&1
    )
    del .streamlit_pid >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
    echo [清理] 已结束占用端口 8501 的残留进程 (PID %%a)
)

:: ====== 启动系统 ======
:: 直接调用 venv 的 python 运行 launcher.py，继承当前控制台窗口
"%PROJECT_DIR%\venv\Scripts\python.exe" "%PROJECT_DIR%\launcher.py"

:: ====== 退出后兜底清理 ======
echo.
echo [兜底] 清理残留进程...
if exist "%PROJECT_DIR%\.streamlit_pid" (
    for /f %%i in (%PROJECT_DIR%\.streamlit_pid) do (
        taskkill /F /T /PID %%i >nul 2>&1
    )
    del "%PROJECT_DIR%\.streamlit_pid" >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
    echo [兜底] 已清理占用端口 8501 的进程 (PID %%a)
)

echo 系统已停止。
pause
