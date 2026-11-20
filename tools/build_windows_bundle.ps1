<#
NovaStream - Gömülü Python dağıtım paketi oluşturucu (Windows)

NovaStream-App\runtime klasörüne python.org'un "embeddable" Python paketini kurar ve
requirements.txt'deki kütüphaneleri (PyQt6, requests, yt-dlp, deno) içine yükler.
-IncludeFFmpeg parametresi verilirse FFmpeg Essentials sürümünü runtime\bin\ffmpeg.exe
olarak indirip paketler (kullanıcıda ek FFmpeg kurulumu gerekmez).

Kullanım (proje kök klasöründen):
    powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1 [-IncludeFFmpeg]
#>
param(
    [string[]]$PythonVersions = @("3.13.11", "3.13.10", "3.13.9", "3.13.8", "3.13.7", "3.13.5", "3.13.0"),
    [switch]$IncludeFFmpeg
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
$App = Join-Path $Root "NovaStream-App"
$Runtime = Join-Path $App "runtime"
$Tmp = Join-Path $env:TEMP "novastream_bundle"
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

Write-Host "[*] Gomulu Python indiriliyor..."
$zip = Join-Path $Tmp "python-embed.zip"
$got = $null
foreach ($v in $PythonVersions) {
    $url = "https://www.python.org/ftp/python/$v/python-$v-embed-amd64.zip"
    try {
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        $got = $v
        break
    } catch {
        Write-Host "    $v bulunamadi, siradaki deneniyor..."
    }
}
if (-not $got) { throw "Gomulu Python indirilemedi." }
Write-Host "    Python $got"

if (Test-Path $Runtime) { Remove-Item -Recurse -Force $Runtime }
Expand-Archive -Path $zip -DestinationPath $Runtime -Force

# site-packages ve 'import site' etkinlestir (pip ve kutuphaneler icin gerekli)
$pth = Get-ChildItem -Path $Runtime -Filter "python*._pth" | Select-Object -First 1
$lines = Get-Content $pth.FullName | ForEach-Object { if ($_ -match '^#\s*import site') { 'import site' } else { $_ } }
if (-not ($lines -contains 'Lib\site-packages')) { $lines += 'Lib\site-packages' }
Set-Content -Path $pth.FullName -Value $lines -Encoding ASCII

Write-Host "[*] pip kuruluyor..."
$getpip = Join-Path $Tmp "get-pip.py"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip -UseBasicParsing
& (Join-Path $Runtime "python.exe") $getpip --no-warn-script-location --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip kurulamadi" }

Write-Host "[*] Kutuphaneler kuruluyor (PyQt6, yt-dlp, deno)..."
& (Join-Path $Runtime "python.exe") -m pip install --no-warn-script-location --disable-pip-version-check -r (Join-Path $App "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Kutuphaneler kurulamadi" }

if ($IncludeFFmpeg) {
    Write-Host "[*] FFmpeg Essentials indiriliyor (runtime\bin\ffmpeg.exe)..."
    $ffZip = Join-Path $Tmp "ffmpeg-essentials.zip"
    $ffTmp = Join-Path $Tmp "ffmpeg_extract"
    if (Test-Path $ffTmp) { Remove-Item -Recurse -Force $ffTmp }
    Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $ffZip -UseBasicParsing
    Expand-Archive -Path $ffZip -DestinationPath $ffTmp -Force
    $ffExe = Get-ChildItem -Path $ffTmp -Filter "ffmpeg.exe" -Recurse | Select-Object -First 1
    if (-not $ffExe) { throw "ffmpeg.exe arsivde bulunamadi" }
    $binDir = Join-Path $Runtime "bin"
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    Copy-Item $ffExe.FullName -Destination (Join-Path $binDir "ffmpeg.exe") -Force
    Write-Host "[OK] FFmpeg gomulu pakete eklendi: $(Join-Path $binDir 'ffmpeg.exe')"
}

& (Join-Path $Runtime "python.exe") -c "import PyQt6.QtWidgets, yt_dlp, requests; print('[OK] Gomulu Python hazir:', __import__('sys').version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw "Dogrulama basarisiz" }
Write-Host "[OK] Paket hazir: $Runtime"
