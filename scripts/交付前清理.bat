@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0.."

echo ============================================
echo   打包 / 提交前清理
echo ============================================
echo.
echo 以下内容会被删除（它们都不应该出现在交付包里）：
echo   1) .env            真实数据库密码 + 应用签名密钥
echo   2) .venv           本地虚拟环境（几十 MB，换机必坏）
echo   3) __pycache__     Python 字节码缓存
echo   4) .pytest_cache   测试缓存
echo   5) .coverage / htmlcov  覆盖率产物
echo.
echo 注意：删除后本机将无法直接启动，需要重新运行「首次安装并启动.bat」。
echo.

set /p ANSWER=确认清理请输入 YES：
if /i not "%ANSWER%"=="YES" (
    echo 已取消，未删除任何文件。
    pause
    exit /b 1
)

rem 先把 .env 备份到用户目录，避免密码丢失
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
echo [删除] __pycache__

if exist ".pytest_cache" rmdir /s /q ".pytest_cache"
if exist ".coverage" del /f /q ".coverage"
if exist "htmlcov" rmdir /s /q "htmlcov"
del /f /q "_db_audit.py" 2>nul
echo [删除] .pytest_cache / .coverage / htmlcov / _db_audit.py

echo.
echo 清理完成。交付前请再确认：
echo   - 目录里没有 .env / .venv / __pycache__ / .pytest_cache
echo   - 只保留 .env.example
echo   - 已 git add 并 commit 最新改动
echo.
pause
