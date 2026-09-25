#ifndef PayloadDir
  #error Define PayloadDir when compiling
#endif
#ifndef ReleaseDir
  #error Define ReleaseDir when compiling
#endif
[Setup]
AppId={{E76251FC-52CF-44EE-93E7-0278400F236C}
AppName=MeshCore EMS Services
AppVersion=0.2.0-alpha
AppPublisher=Usrnmna
AppPublisherURL=https://github.com/Usrnmna/MeshCore-EMS-Services
DefaultDirName={autopf}\MeshCore-EMS
DefaultGroupName=MeshCore EMS
OutputDir={#ReleaseDir}
OutputBaseFilename=MeshCore-EMS-v0.2.0-alpha-windows-x64-setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile={#PayloadDir}\LICENSE
UninstallDisplayIcon={app}\MeshCoreEMS.Service.exe
CloseApplications=no
SetupLogging=yes

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Installation guide"; Filename: "{app}\INSTALL.md"
Name: "{group}\Service settings"; Filename: "notepad.exe"; Parameters: """{commonappdata}\MeshCore-EMS\config.json"""
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"

[Code]
var PortPage: TInputQueryWizardPage;

function InitializeUninstall(): Boolean;
var Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installers\windows\uninstall.ps1') + '"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then MsgBox('Could not stop/remove the Windows service. Uninstall was cancelled; program files were retained.', mbError, MB_OK);
end;

function ValidPort(Value: String): Boolean;
var I: Integer;
begin
  Result := False;
  if (Length(Value) < 4) or (UpperCase(Copy(Value, 1, 3)) <> 'COM') then exit;
  if Value[4] = '0' then exit;
  for I := 4 to Length(Value) do
    if (Value[I] < '0') or (Value[I] > '9') then exit;
  Result := True;
end;

procedure InitializeWizard;
begin
  PortPage := CreateInputQueryPage(wpSelectDir, 'Companion radio',
    'Select the serial device and existing MeshCore channel.',
    'Setup downloads Python and dependencies automatically. Enter the COM port shown in Device Manager. The channel must already exist on your radio.');
  PortPage.Add('Serial port (for example COM11):', False);
  PortPage.Add('Channel name (blank preserves the current/default channel):', False);
  PortPage.Values[0] := ExpandConstant('{param:SERIALPORT|}');
  PortPage.Values[1] := ExpandConstant('{param:CHANNEL|}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = PortPage.ID then begin
    Result := ValidPort(PortPage.Values[0]) and (Pos('"', PortPage.Values[1]) = 0);
    if not Result then MsgBox('Enter a COM port such as COM11 and a channel without double quotes.', mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  Result := '';
  if not ValidPort(PortPage.Values[0]) then begin
    Result := 'A serial port is required. For silent setup use /SERIALPORT=COM11.'; exit;
  end;
  if Pos('"', PortPage.Values[1]) <> 0 then begin Result := 'Invalid channel name.'; exit; end;
  // Stop only this product before replacing its executable or Python source.
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -Command "if (Get-Service MeshCoreEMS -ErrorAction SilentlyContinue) { Stop-Service MeshCoreEMS -ErrorAction Stop; (Get-Service MeshCoreEMS).WaitForStatus(''Stopped'', [TimeSpan]::FromSeconds(50)) }"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      Result := 'Could not stop the existing MeshCore EMS service.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Params: String;
begin
  if CurStep = ssPostInstall then begin
    Params := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installers\windows\install.ps1') +
      '" -InstallRoot "' + ExpandConstant('{app}') + '" -SerialPort "' + PortPage.Values[0] + '"';
    if PortPage.Values[1] <> '' then Params := Params + ' -Channel "' + PortPage.Values[1] + '"';
    if ExpandConstant('{param:NOSTART|0}') = '1' then Params := Params + ' -NoStart';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
      ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, Code) or (Code <> 0) then
      RaiseException('Dependency or service setup failed. See ProgramData\MeshCore-EMS\install.log. Correct the reported issue and rerun this installer.');
  end;
end;
