@echo off
rem NovaStream baslaticisi: once gomulu Python (runtime), sonra venv, en son sistem Python ile venv kurar
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
    start "" "runtime\pythonw.exe" main.py %*
    exit /b 0
)
if exist "venv\Scripts\pythonw.exe" (
    start "" "venv\Scripts\pythonw.exe" main.py %*
    exit /b 0
)
where python >nul 2>&1
if errorlevel 1 (
    echo [!] Python bulunamadi. Lutfen NovaStream'i Kurulum-Windows.bat ile kurun.
    pause
    exit /b 1
)
echo [*] Python calisma ortami hazirlaniyor...
python -m venv venv || goto :fail
venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt || goto :fail
start "" "venv\Scripts\pythonw.exe" main.py %*
exit /b 0
:fail
echo [!] Kurulum basarisiz oldu.
pause
exit /b 1
