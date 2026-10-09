# Скрипт быстрого запуска Telegram Audio Downloader для PowerShell
$ErrorActionPreference = "SilentlyContinue"
$rootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $rootDir

python "$rootDir\launch.py"
