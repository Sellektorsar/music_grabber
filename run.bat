@echo off
cd /d "%~dp0"
echo Starting Telegram Audio Downloader...
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Application exited with error code %ERRORLEVEL%.
    pause
)
