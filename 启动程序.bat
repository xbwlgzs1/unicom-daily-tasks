@echo off
chcp 65001 >nul 2>nul
title 中国联通 · 日常任务合集
cd /d "%~dp0"

rem 优先启动打包好的 exe (无需安装 Python)
if exist "中国联通日常任务.exe" (
    start "" "%~dp0中国联通日常任务.exe"
    exit /b 0
)
if exist "dist\UnicomDaily.exe" (
    start "" "%~dp0dist\UnicomDaily.exe"
    exit /b 0
)

rem 回退: 源码模式, 需要本机已装 Python
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw main.py
    exit /b 0
)

echo.
echo [错误] 既没有找到打包好的程序, 也没有找到 Python。
echo.
echo 解决办法二选一:
echo   1. 把 中国联通日常任务.exe 放到本文件夹
echo   2. 安装 Python 3.10+ 并执行:  pip install requests pycryptodome openpyxl
echo      然后运行  python main.py
echo.
pause
