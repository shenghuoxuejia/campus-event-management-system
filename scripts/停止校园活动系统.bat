@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."
chcp 936 >nul 2>&1

echo ============================================
echo   校园活动报名与管理系统 - 停止
echo ============================================
echo.

rem ---- 端口：从 .env 读，缺省 5000 ----
set "PORT=5000"
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        if /i "%%a"=="PORT" set "PORT=%%b"
    )
)
set "APP_PORT=%PORT%"

rem ---- 只停止「本项目 backend\app.py」占端口的进程，避免误杀其它程序 ----
powershell -NoProfile -Command "$port=[int]$env:APP_PORT; $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $conn) { Write-Host ('服务未在运行（端口 ' + $port + ' 未被监听）。'); exit 0 }; $procId = $conn.OwningProcess; $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $procId) -ErrorAction SilentlyContinue; $cmdline = if ($proc) { $proc.CommandLine } else { '' }; if ($cmdline -and $cmdline -match 'backend\\app\.py') { Stop-Process -Id $procId -Force; Write-Host ('已停止校园活动系统（PID ' + $procId + '）。') } else { Write-Host ('端口 ' + $port + ' 被其它程序占用（PID ' + $procId + '），未执行停止。'); Write-Host ('占用进程命令行：' + $cmdline) }"

ping -n 3 127.0.0.1 >nul
echo.
echo 顺便清理临时文件吗？
echo   1) 只清缓存：__pycache__ / .pytest_cache / .coverage / htmlcov ... 输入 y
echo   2) 连 .env 和 .venv 一起清（打包交付用，.env 会先备份） ...... 输入 YES
echo   3) 不清理 .................................................... 直接回车
echo.
set "ANSWER="
set /p ANSWER=请选择：
if /i "%ANSWER%"=="YES" goto clean_all
if /i "%ANSWER%"=="y" goto clean_cache
echo 已跳过清理。
goto done

:clean_cache
for /d /r %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)
if exist ".pytest_cache" rmdir /s /q ".pytest_cache"
if exist "htmlcov" rmdir /s /q "htmlcov"
if exist ".coverage" del /f /q ".coverage"
echo [完成] 已删除缓存目录（__pycache__ / .pytest_cache / htmlcov / .coverage）。
goto done

:clean_all
if exist ".env" (
    copy /y ".env" "%USERPROFILE%\campus_events_env_backup.txt" >nul
    echo [备份] .env 已备份到 %USERPROFILE%\campus_events_env_backup.txt
    del /f /q ".env"
    echo [删除] .env
)
if exist ".venv" (
    rmdir /s /q ".venv"
    echo [删除] .venv
)
for /d /r %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)
if exist ".pytest_cache" rmdir /s /q ".pytest_cache"
if exist "htmlcov" rmdir /s /q "htmlcov"
if exist ".coverage" del /f /q ".coverage"
echo [完成] 已清理 .env / .venv / 缓存，可以打包了。
echo        下次使用前重新双击「启动校园活动系统.bat」即可自动装回环境。
echo        交付前再确认：只保留 .env.example，没有 .venv、__pycache__、.pytest_cache。
goto done

:done
echo.
pause
exit /b 0
