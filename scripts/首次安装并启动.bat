@echo off
setlocal
cd /d "%~dp0.."
echo ============================================
echo   校园活动报名与管理系统 - 首次安装
echo ============================================
echo.

rem ---- 1) 找一个可用的 Python ----
set "BOOT="
py -3 --version >nul 2>&1
if not errorlevel 1 set "BOOT=py -3"
if not defined BOOT (
    python --version >nul 2>&1
    if not errorlevel 1 set "BOOT=python"
)
if not defined BOOT (
    echo [错误] 没有检测到 Python。
    echo        请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/
    echo        安装时务必勾选 Add python.exe to PATH。
    pause
    exit /b 1
)

rem ---- 2) 创建虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 创建虚拟环境...
    %BOOT% -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
) else (
    echo [1/4] 虚拟环境已存在，跳过。
)

rem ---- 3) 安装依赖 ----
echo [2/4] 安装依赖，首次会比较慢，请耐心等待...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

rem ---- 4) 生成 .env ----
if exist ".env" (
    echo [3/4] .env 已存在，跳过数据库配置。
) else (
    echo [3/4] 配置数据库连接...
    ".venv\Scripts\python.exe" backend\setup_env.py
)

rem ---- 5) 初始化数据库 ----
echo [4/4] 检查并初始化数据库...
".venv\Scripts\python.exe" backend\init_db.py
if errorlevel 1 (
    echo [错误] 数据库初始化失败，请按上面的提示处理后重试。
    pause
    exit /b 1
)

echo.
echo 安装完成，正在启动...
call "%~dp0..\scripts\启动校园活动系统.bat"
exit /b 0
