; NovaStream Windows Inno Setup betigi
; Once gomulu Python paketini olusturun:  powershell -ExecutionPolicy Bypass -File ..\tools\build_windows_bundle.ps1
; Sonra bu dosyayi Inno Setup Compiler ile derleyin. Kullanicinin bilgisayarinda Python gerekmez.

#define MyAppName "NovaStream"
#define MyAppVersion "2.4.3"
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
Name: "browserintegration"; Description: "Chrome, Edge, Brave ve Firefox tarayici koprulerini kaydet"; GroupDescription: "Entegrasyonlar:"

[Files]
Source: "main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "run_windows.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "core\*.py"; DestDir: "{app}\core"; Flags: ignoreversion
Source: "ui\*.py"; DestDir: "{app}\ui"; Flags: ignoreversion
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "runtime\*"; DestDir: "{app}\runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__"
Source: "..\NovaStream-v2\native_host.py"; DestDir: "{app}\browser"; Flags: ignoreversion
Source: "..\NovaStream-v2\native_host.bat"; DestDir: "{app}\browser"; Flags: ignoreversion
Source: "..\NovaStream-v2\OpenVideoDownloader-Extension\*"; DestDir: "{app}\browser\chrome"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\NovaStream-Firefox\OpenVideoDownloader-Extension\*"; DestDir: "{app}\browser\firefox"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
; Tarayici koprusu kaydi (kayit defteri + manifest dosyalari)
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\core\native_messaging.py"" ""{app}\browser"""; Flags: runhidden; Tasks: browserintegration
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\main.py"""; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: "-c ""import sys; sys.path.insert(0, r'{app}'); from core.native_messaging import unregister; unregister()"""; Flags: runhidden; RunOnceId: "NovaStreamUnregister"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\browser"
