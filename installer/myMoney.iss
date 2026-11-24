; Inno Setup: installa myMoney (programma + widget) per l'utente corrente, senza bisogno di amministratore.
; Si costruisce da .github/workflows/windows.yml:  iscc /DVersione=2026.11.24 installer\myMoney.iss
#ifndef Versione
  #define Versione "1.0"
#endif

[Setup]
AppId={{6F1C6B1E-3D0A-4E2C-9B7A-5C1D0E7A4F21}
AppName=myMoney
AppVersion={#Versione}
AppPublisher=myMoney
DefaultDirName={autopf}\myMoney
DefaultGroupName=myMoney
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist-installer
OutputBaseFilename=myMoney-Setup
SetupIconFile=..\icons\myMoney.ico
UninstallDisplayIcon={app}\myMoney.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktop"; Description: "Crea un'icona sul Desktop"; GroupDescription: "Collegamenti:"
Name: "widget"; Description: "Avvia il widget con Windows"; GroupDescription: "Widget:"; Flags: unchecked

[Files]
Source: "..\dist\myMoney\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\myMoney"; Filename: "{app}\myMoney.exe"; IconFilename: "{app}\_internal\icons\myMoney.ico"; Comment: "Portafogli ETF nel browser"
Name: "{group}\myMoney widget"; Filename: "{app}\myMoney-widget.exe"; IconFilename: "{app}\_internal\icons\myMoney.ico"; Comment: "Widget sempre in primo piano"
Name: "{group}\Cartella dei portafogli"; Filename: "{userdocs}\myMoney\portafogli"
Name: "{group}\Disinstalla myMoney"; Filename: "{uninstallexe}"
Name: "{autodesktop}\myMoney"; Filename: "{app}\myMoney.exe"; IconFilename: "{app}\_internal\icons\myMoney.ico"; Tasks: desktop

[Run]
Filename: "{app}\myMoney-widget.exe"; Parameters: "--avvio on"; Flags: runhidden; Tasks: widget
Filename: "{app}\myMoney.exe"; Description: "Avvia myMoney"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\myMoney-widget.exe"; Parameters: "--avvio off"; Flags: runhidden; RunOnceId: "ToglieAvvioWidget"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
