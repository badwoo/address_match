@echo off
chcp 65001 >nul
title 地址匹配系统

:: ====== 自动定位项目目录 ======
:: %~dp0 = 本 BAT 文件所在目录
:: 如果本 BAT 放在项目根目录，%~dp0 就是项目路径
:: 如果本 BAT 放在别处（比如桌面），下面会修正路径
set "PROJECT_DIR=%~dp0"

:: 去掉末尾反斜杠
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: 检查是否在项目目录（存在 launcher.py）
if exist "%PROJECT_DIR%\launcher.py" goto :project_found

:: 如果 BAT 不在项目目录，回退到硬编码路径
set "PROJECT_DIR=D:\pythonProject\address_match"
if exist "%PROJECT_DIR%\launcher.py" goto :project_found

echo [错误] 找不到项目目录！
echo 请把本 BAT 文件放到项目根目录 D:\pythonProject\address_match 下
echo 或在桌面创建指向该 BAT 的快捷方式
pause
exit /b 1

:project_found
echo 项目路径: %PROJECT_DIR%
cd /d "%PROJECT_DIR%"

:: ====== 先兜底杀掉可能残留的进程 ======
if exist ".streamlit_pid" (
    for /f %%i in (.streamlit_pid) do (
        taskkill /F /T /PID %%i >nul 2>&1
    )
    del .streamlit_pid >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    taskkill /F /T /PID %%a >nul 2>&1
    echo [清理] 已结束占用端口 8501 的残留进程
)

:: ====== 启动系统 ======
call "%PROJECT_DIR%\venv\Scripts\activate.bat"
python "%PROJECT_DIR%\launcher.py"

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
    echo [兜底] 已清理占用端口 8501 的进程
)
echo 系统已停止。
pause
