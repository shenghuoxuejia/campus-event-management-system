@echo off
setlocal
cd /d "%~dp0.."

rem ---- 从 .env 读取端口（缺省 5000）----
set "PORT=5000"
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        if /i "%%a"=="PORT" set "PORT=%%b"
    )
)
set "APP_PORT=%PORT%"
set "URL=http://127.0.0.1:%PORT%/"

if not exist "%~dp0..\.venv\Scripts\python.exe" (
    echo [提示] 还没有安装运行环境，先执行首次安装...
    call "%~dp0..\scripts\首次安装并启动.bat"
    exit /b 0
)
set "PY=%~dp0..\.venv\Scripts\python.exe"

rem ---- 如果后端已经在运行，直接打开浏览器 ----
powershell -NoProfile -Command "$port=[int]$env:APP_PORT; try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',$port);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    echo 服务已经在运行中，正在打开浏览器...
    start "" "%URL%"
    exit /b 0
)

echo 正在启动校园活动系统...
start "校园活动系统服务端" /min "%PY%" "%~dp0..\backend\app.py"
ping -n 4 127.0.0.1 >nul
start "" "%URL%"
echo 服务已启动。如浏览器未自动打开，请手动访问 %URL%
echo 关闭服务：双击 scripts 目录下的「停止校园活动系统.bat」。
exit /b 0
