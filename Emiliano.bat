@echo off
setlocal
title Emiliano Chat
rem Double-click to chat with Emiliano in this repository.
rem Drag a folder onto this file to chat with that folder as the workspace.

set "ROOT=%~dp0"
set "ENGINE=%ROOT%packages\engine"
set "VENV=%ENGINE%\.venv"
set "EMILIANO=%VENV%\Scripts\emiliano.exe"

rem UTF-8 console so colored output and symbols render correctly
chcp 65001 >nul
set "PYTHONUTF8=1"

if exist "%EMILIANO%" goto :run

echo [Emiliano] First run: installing the engine into packages\engine\.venv ...
where uv >nul 2>nul
if errorlevel 1 goto :setup_pip

uv venv "%VENV%" || goto :setup_failed
uv pip install --python "%VENV%\Scripts\python.exe" -e "%ENGINE%" || goto :setup_failed
goto :run

:setup_pip
python -m venv "%VENV%" || goto :setup_failed
"%VENV%\Scripts\python.exe" -m pip install -e "%ENGINE%" || goto :setup_failed

:run
if "%~1"=="" (
    cd /d "%ROOT%"
) else (
    cd /d "%~1" || goto :bad_folder
)
echo [Emiliano] Workspace: %CD%
"%EMILIANO%"
set "RC=%errorlevel%"
rem Keep the window open on errors so the message can be read
if not "%RC%"=="0" pause
exit /b %RC%

:bad_folder
echo [Emiliano] Could not open folder: %~1
pause
exit /b 1

:setup_failed
echo.
echo [Emiliano] Setup failed. Install Python 3.10+ (and optionally uv), then run this file again.
pause
exit /b 1
