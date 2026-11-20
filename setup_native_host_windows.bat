@echo off
rem NovaStream'i KURMADAN, bu klasorden calistirirken tarayici koprusunu kaydeder (gelistirici kullanimi).
rem Normal kullanimda Kurulum-Windows.bat yeterlidir; kurulum sihirbazi kaydi kendisi yapar.
setlocal
set "H=%~dp0"
for %%P in ("%H%NovaStream-App\runtime\python.exe" "%H%NovaStream-App\venv\Scripts\python.exe") do (
    if exist "%%~P" (
        "%%~P" "%H%NovaStream-App\core\native_messaging.py" "%H%NovaStream-v2"
        exit /b
    )
)
python "%H%NovaStream-App\core\native_messaging.py" "%H%NovaStream-v2"
