@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."
chcp 936 >nul 2>&1

echo ============================================
echo   校园活动报名与管理系统 - 启动
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

rem ---- 2) 虚拟环境：没有就建一个 ----
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 第一次运行，正在创建虚拟环境...
    %BOOT% -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败。
        pause
        exit /b 1
    )
)
set "PY=.venv\Scripts\python.exe"

rem ---- 3) 依赖：缺了才装，装过就跳过 ----
"%PY%" -c "import flask, flask_cors, mysql.connector, bcrypt, itsdangerous, dotenv" >nul 2>&1
if errorlevel 1 (
    echo [2/4] 正在安装依赖，第一次会比较慢，请耐心等待...
    "%PY%" -m pip install --upgrade pip --quiet
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

rem ---- 4) .env：没有就引导填写数据库连接 ----
if not exist ".env" (
    echo [3/4] 还没有数据库配置，按提示填写即可...
    "%PY%" backend\setup_env.py
    if errorlevel 1 (
        echo [错误] 数据库配置未完成。
        pause
        exit /b 1
    )
)

rem ---- 5) 数据库：缺表就初始化（已存在的库不会被改动）----
"%PY%" backend\init_db.py >"%TEMP%\campus_init_db.log" 2>&1
if errorlevel 1 (
    echo [错误] 数据库初始化失败，详情：
    type "%TEMP%\campus_init_db.log"
    pause
    exit /b 1
)

rem ---- 6) 端口：从 .env 读，缺省 5000 ----
set "PORT=5000"
for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if /i "%%a"=="PORT" set "PORT=%%b"
)
set "APP_PORT=%PORT%"
set "URL=http://127.0.0.1:%PORT%/"

rem ---- 7) 已经在运行就直接开浏览器 ----
powershell -NoProfile -Command "$port=[int]$env:APP_PORT; try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',$port);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    echo [4/4] 服务已经在运行，直接打开浏览器...
    start "" "%URL%"
    exit /b 0
)

echo [4/4] 正在启动服务...
start "校园活动系统服务端" /min "%PY%" "backend\app.py"
ping -n 4 127.0.0.1 >nul
start "" "%URL%"
echo.
echo 服务已启动（端口 %PORT%）。若浏览器没有自动打开，手动访问 %URL%
echo 关闭服务：双击 scripts 目录下的「停止校园活动系统.bat」
echo.
pause
exit /b 0
