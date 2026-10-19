@echo off
title Smart Attendance System
cd /d "%~dp0"
echo =========================================================
echo  Starting Smart Attendance Management System...
echo =========================================================
echo.

py -3.13 app.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Trying fallback 'python app.py'...
    python app.py
)

pause
