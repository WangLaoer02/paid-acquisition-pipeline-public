@echo off
rem Windows: double-click to install ab-join-name-upload and the workspace. No login, no upload.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 install.py %*
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
    pause
    exit /b 1
  )
  python install.py %*
)
set rc=%errorlevel%
pause
exit /b %rc%
