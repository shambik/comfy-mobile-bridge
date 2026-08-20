@echo off
setlocal EnableExtensions

rem One-click launcher for the H3 Mobile Bridge project.
rem It starts ComfyUI first, then the bridge, without duplicating either
rem process when its configured port is already listening.

set "REPO=%~dp0"
set "COMFY_ROOT=D:\Repos\ComfyUI_venv\ComfyUI"
set "COMFY_PYTHON=%COMFY_ROOT%\venv_h3_torch211_cu130\Scripts\python.exe"
set "BRIDGE_PYTHON=%COMFY_ROOT%\venv\Scripts\python.exe"
set "COMFY_PORT=8190"
set "BRIDGE_PORT=8787"

if not exist "%COMFY_PYTHON%" (
    echo ComfyUI Python was not found:
    echo %COMFY_PYTHON%
    pause
    exit /b 2
)

if not exist "%COMFY_ROOT%\main.py" (
    echo ComfyUI main.py was not found:
    echo %COMFY_ROOT%\main.py
    pause
    exit /b 2
)

if not exist "%BRIDGE_PYTHON%" (
    echo Bridge Python was not found:
    echo %BRIDGE_PYTHON%
    pause
    exit /b 2
)

call :port_in_use %COMFY_PORT%
if errorlevel 1 (
    echo Starting ComfyUI on port %COMFY_PORT%...
    start "ComfyUI - H3" /D "%COMFY_ROOT%" "%COMFY_PYTHON%" -u "%COMFY_ROOT%\main.py" ^
        --listen 127.0.0.1 --port %COMFY_PORT% ^
        --base-directory "%COMFY_ROOT%" ^
        --models-directory "%COMFY_ROOT%\models" ^
        --input-directory "%REPO%state\input" ^
        --output-directory "%REPO%state\output" ^
        --temp-directory "%REPO%state\temp" ^
        --user-directory "%REPO%state\user" ^
        --database-url "sqlite:///D:/repository/state/user/comfyui.db" ^
        --disable-auto-launch --disable-api-nodes ^
        --reserve-vram 0.9 --enable-dynamic-vram --async-offload 2 ^
        --preview-method none --log-stdout
) else (
    echo ComfyUI is already listening on port %COMFY_PORT%. Skipping it.
)

timeout /t 3 /nobreak >nul

call :port_in_use %BRIDGE_PORT%
if errorlevel 1 (
    echo Starting bridge on port %BRIDGE_PORT%...
    start "H3 Mobile Bridge" /D "%REPO%" "%BRIDGE_PYTHON%" -u "%REPO%run.py"
) else (
    echo Bridge is already listening on port %BRIDGE_PORT%. Skipping it.
)

echo.
echo Project launch requested.
echo Local app: http://127.0.0.1:%BRIDGE_PORT%/
echo Tailscale: https://desktop-ovb0bfj.tail050c4b.ts.net/
echo.
timeout /t 5 /nobreak >nul
exit /b 0

:port_in_use
powershell.exe -NoProfile -NonInteractive -Command "if (Get-NetTCPConnection -State Listen -LocalPort %1 -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%
