@echo off
setlocal
title Emiliano Desktop
rem Double-click to open the Emiliano desktop app (floating dock + HUD overlay) on this
rem repository's code, so engine and UI changes can be tested without building a release.
rem Drag a folder onto this file to use that folder as the workspace.
rem Needs Python 3.10+, Node with yarn, and Rust (https://rustup.rs) with the VS C++ build tools.

set "ROOT=%~dp0"
set "ENGINE=%ROOT%packages\engine"
set "VENV=%ENGINE%\.venv"
set "EMILIANO=%VENV%\Scripts\emiliano.exe"
set "SIDECAR=%ROOT%apps\desktop\src-tauri\binaries\emiliano-engine-x86_64-pc-windows-msvc.exe"

chcp 65001 >nul
set "PYTHONUTF8=1"

rem Workspace: the dropped folder, or this repository
if "%~1"=="" (set "WORKSPACE=%ROOT%") else (set "WORKSPACE=%~f1")
if not exist "%WORKSPACE%\" goto :bad_folder
rem No trailing backslash: before a closing quote it would escape the quote
if "%WORKSPACE:~-1%"=="\" set "WORKSPACE=%WORKSPACE:~0,-1%"

rem 1. Engine (same first-run setup as Emiliano.bat)
if exist "%EMILIANO%" goto :check_tools
echo [Emiliano] First run: installing the engine into packages\engine\.venv ...
where uv >nul 2>nul
if errorlevel 1 goto :setup_pip
uv venv "%VENV%" || goto :setup_failed
uv pip install --python "%VENV%\Scripts\python.exe" -e "%ENGINE%" || goto :setup_failed
goto :check_tools
:setup_pip
python -m venv "%VENV%" || goto :setup_failed
"%VENV%\Scripts\python.exe" -m pip install -e "%ENGINE%" || goto :setup_failed

:check_tools
where yarn >nul 2>nul || goto :no_yarn
where cargo >nul 2>nul || goto :no_rust

rem 2. Desktop dependencies
cd /d "%ROOT%"
if exist "%ROOT%node_modules" goto :check_sidecar
echo [Emiliano] First run: installing desktop dependencies (yarn install) ...
call yarn install || goto :setup_failed

:check_sidecar
rem Tauri refuses to compile without the bundled engine binary, even though this
rem launcher runs the engine from packages\engine instead. Build it once.
if exist "%SIDECAR%" goto :start
echo [Emiliano] First run: building the bundled engine binary (a few minutes) ...
"%VENV%\Scripts\python.exe" -c "import PyInstaller" >nul 2>nul && goto :build_sidecar
rem uv-made venvs have no pip; --native-tls uses the Windows certificate store
where uv >nul 2>nul
if errorlevel 1 ("%VENV%\Scripts\python.exe" -m pip install pyinstaller || goto :setup_failed) else (uv pip install --native-tls --python "%VENV%\Scripts\python.exe" pyinstaller || goto :setup_failed)
:build_sidecar
"%VENV%\Scripts\python.exe" "%ROOT%scripts\build_engine_sidecar.py" || goto :setup_failed

:start
rem The installed Emiliano app (or another engine) already uses the port: this engine could not start
netstat -ano | findstr /r /c:":8765 .*LISTENING" >nul && goto :port_busy
echo [Emiliano] Workspace: %WORKSPACE%
echo [Emiliano] Starting the engine in its own window (close it to stop the engine) ...
start "Emiliano Engine" /d "%WORKSPACE%" "%EMILIANO%" server
rem The app uses that engine instead of starting its bundled copy
set "EMILIANO_EXTERNAL_ENGINE=1"
echo [Emiliano] Opening the desktop app. The first build compiles Rust and takes a few minutes.
call yarn workspace @emiliano/desktop tauri dev
set "RC=%errorlevel%"
if not "%RC%"=="0" pause
exit /b %RC%

:port_busy
echo [Emiliano] Port 8765 is already in use: close the installed Emiliano app or any running
echo [Emiliano] "emiliano server" window, then run this file again.
pause
exit /b 1

:no_yarn
echo [Emiliano] yarn not found. Install Node.js, then run: npm install -g yarn
pause
exit /b 1

:no_rust
echo [Emiliano] Rust not found. The desktop app and HUD need it: install from https://rustup.rs
echo [Emiliano] (with the Visual Studio C++ build tools), then run this file again.
pause
exit /b 1

:bad_folder
echo [Emiliano] Could not open folder: %~1
pause
exit /b 1

:setup_failed
echo.
echo [Emiliano] Setup failed. See the messages above, fix the problem, then run this file again.
pause
exit /b 1
