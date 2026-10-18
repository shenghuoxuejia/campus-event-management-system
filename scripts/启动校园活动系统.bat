@echo off
setlocal
set "URL=http://127.0.0.1:5000/"
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [提示] 还没安装运行环境，先执行首次安装...
    call "%~dp0首次安装并启动.bat"
    exit /b 0
)
set "PY=%~dp0.venv\Scripts\python.exe"

rem ---- 服务已在运行则直接打开浏览器 ----
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',5000);$c.Close();exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    echo 服务已经在运行，正在打开浏览器...
    start "" "%URL%"
    exit /b 0
)

echo 正在启动校园活动系统服务...
start "校园活动系统服务端" /min "%PY%" "%~dp0app.py"
ping -n 4 127.0.0.1 >nul
start "" "%URL%"
echo 已启动。服务端在最小化窗口里运行，关掉那个窗口即停止服务。
exit /b 0
