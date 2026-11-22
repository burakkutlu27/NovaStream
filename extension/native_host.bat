@echo off
setlocal
rem NovaStream native host baslaticisi: once gomulu Python, sonra venv, en son sistem Python
set "H=%~dp0"
for %%P in ("%H%..\runtime\python.exe" "%H%..\NovaStream-App\runtime\python.exe" "%H%..\venv\Scripts\python.exe" "%H%..\NovaStream-App\venv\Scripts\python.exe") do (
  if exist "%%~P" (
    "%%~P" -u "%H%native_host.py" %*
    exit /b
  )
)
python -u "%H%native_host.py" %*
