@echo off
title NovaStream Kurulum Sihirbazi
cd /d "%~dp0"

rem 1) Gomulu Python varsa (dagitim paketi): sistemde Python gerekmez
if exist "runtime\pythonw.exe" (
    echo [*] Kurulum sihirbazi aciliyor...
    start "" "runtime\pythonw.exe" installer.py
    exit /b 0
)

rem 2) Gelistirici kopyasi: sistem Python'u ile venv
where python >nul 2>&1
if errorlevel 1 goto :no_python
if not exist "venv\Scripts\python.exe" (
    echo [*] Python calisma ortami hazirlaniyor...
    python -m venv venv || goto :fail
)
venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -U -r requirements.txt || goto :fail
start "" "venv\Scripts\pythonw.exe" installer.py
exit /b 0

:no_python
echo.
echo [!] Bu klasorde gomulu Python (runtime) yok ve sistemde Python bulunamadi.
echo     Dagitim paketini olusturmak icin (internet gerekir):
echo     powershell -ExecutionPolicy Bypass -File ..\tools\build_windows_bundle.ps1
echo.
pause
exit /b 1

:fail
echo [!] Kurulum hazirligi basarisiz oldu.
pause
exit /b 1
