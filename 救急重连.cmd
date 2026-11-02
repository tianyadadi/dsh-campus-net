@echo off
chcp 65001 >nul
title 校园网救急重连
echo.
echo   ============================================
echo     校园网救急重连（不依赖 DSH）
echo   ============================================
echo.
set PY=C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe
set CORE=E:\appsoftware\Deepseek\chajian\dsh-campus-net\core\campus_net.py

echo   [1/2] 检查当前状态...
"%PY%" "%CORE%" status
echo.
echo   [2/2] 尝试登录...
"%PY%" "%CORE%" login
echo.
echo   稍等 3 秒再查一次...
timeout /t 3 /nobreak >nul
"%PY%" "%CORE%" status
echo.
echo   如果显示 "online": true 就说明连上了。
echo   本窗口可以直接关掉。
pause