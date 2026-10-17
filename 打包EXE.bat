@echo off
chcp 65001 >nul 2>nul
title 打包成 exe
cd /d "%~dp0"

set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python

echo [1/3] 自检...
"%PY%" -X utf8 main.py --selftest
if errorlevel 1 (
    echo 自检未通过, 已中止打包
    pause
    exit /b 1
)

echo [2/3] 生成图标...
"%PY%" -X utf8 make_icon.py

echo [3/3] PyInstaller 打包...
"%PY%" -m PyInstaller --noconfirm --onefile --windowed ^
    --name UnicomDaily ^
    --icon "%~dp0assets\app.ico" ^
    --distpath "%~dp0dist" --workpath "%~dp0build\work" --specpath "%~dp0build" ^
    --paths "%~dp0" --hidden-import notify ^
    "%~dp0main.py"
if errorlevel 1 (
    echo 打包失败
    pause
    exit /b 1
)

if exist "%~dp0dist\UnicomDaily.exe" (
    copy /y "%~dp0dist\UnicomDaily.exe" "%~dp0中国联通日常任务.exe" >nul
    echo.
    echo ✅ 打包完成: %~dp0中国联通日常任务.exe
) else (
    echo ❌ 未生成 exe
)
echo.
pause
