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

rem ---- 只停止「本项目 backend\app.py」占用端口的进程，避免误杀其它程序 ----
powershell -NoProfile -Command "$port=[int]$env:APP_PORT; $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $conn) { Write-Host ('服务未在运行（端口 ' + $port + ' 未被监听）。'); exit 0 }; $procId = $conn.OwningProcess; $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $procId) -ErrorAction SilentlyContinue; $cmdline = if ($proc) { $proc.CommandLine } else { '' }; if ($cmdline -and $cmdline -match 'backend\\app\.py') { Stop-Process -Id $procId -Force; Write-Host ('已停止校园活动系统（PID ' + $procId + '）。') } else { Write-Host ('端口 ' + $port + ' 被其它程序占用（PID ' + $procId + '），未执行停止。'); Write-Host ('占用进程命令行：' + $cmdline) }"

ping -n 3 127.0.0.1 >nul
