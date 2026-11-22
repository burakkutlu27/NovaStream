; NovaStream Windows Inno Setup betigi
; Once gomulu Python paketini olusturun:  powershell -ExecutionPolicy Bypass -File tools\build_windows_bundle.ps1 -IncludeFFmpeg
; Istege bagli paketli eklentiler:        python tools\package_extensions.py --out NovaStream-App\browser_packages --with-id-name
; Sonra bu dosyayi Inno Setup Compiler ile derleyin. Kullanicinin bilgisayarinda Python gerekmez.

#define MyAppName "NovaStream"
#define MyAppVersion "2.6.0"
#define MyAppPublisher "NovaStream"

[Setup]
AppId={{C8E19B91-5B3F-4A92-9C21-6D9E71F401A2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputBaseFilename=NovaStream_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
CloseApplications=yes

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "browserintegration"; Description: "Algilanan tarayicilara kopru ve eklenti paketlerini kur"; GroupDescription: "Entegrasyonlar:"

[Files]
Source: "main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "run_windows.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\BENI-OKU.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\KULLANIM-KILAVUZU.txt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "core\*.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "ui\*.py"; DestDir: "{app}\ui"; Flags: ignoreversion
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__"
Source: "..\extension\native_host.py"; DestDir: "{app}\browser"; Flags: ignoreversion
Source: "..\extension\native_host.bat"; DestDir: "{app}\browser"; Flags: ignoreversion
Source: "..\extension\chrome\*"; DestDir: "{app}\browser\chrome"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\extension\firefox\*"; DestDir: "{app}\browser\firefox"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "browser_packages\*"; DestDir: "{app}\browser\packages"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
; Tarayici koprusu kaydi + otomatik paket/profil yerlestirme
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\core\browser_setup.py"" ""{app}\browser"""; Flags: runhidden; Tasks: browserintegration
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: "-c ""import sys; sys.path.insert(0, r'{app}'); from core.native_messaging import unregister; unregister()"""; Flags: runhidden; RunOnceId: "NovaStreamUnregister"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\browser"
