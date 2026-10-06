#ifndef PayloadDir
  #error Define PayloadDir when compiling
#endif
#ifndef ReleaseDir
  #error Define ReleaseDir when compiling
#endif
[Setup]
AppId={{E76251FC-52CF-44EE-93E7-0278400F236C}
AppName=MeshCore EMS Services
AppVersion=v0.3.0-beta
VersionInfoVersion=0.3.0.0
AppPublisher=Usrnmna
AppPublisherURL=https://github.com/Usrnmna/MeshCore-EMS-Services
DefaultDirName={autopf}\MeshCore-EMS
DefaultGroupName=MeshCore EMS
OutputDir={#ReleaseDir}
OutputBaseFilename=MeshCore-EMS-v0.3.0-beta-windows-x64-setup
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
var PortPage, EndpointPage: TInputQueryWizardPage;
    TransportPage: TInputOptionWizardPage;

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
  // Auto defers USB device detection until service start; explicit COM ports remain valid.
  Result := False;
  if LowerCase(Value) = 'auto' then begin Result := True; exit; end;
  if (Length(Value) < 4) or (UpperCase(Copy(Value, 1, 3)) <> 'COM') then exit;
  if Value[4] = '0' then exit;
  for I := 4 to Length(Value) do
    if (Value[I] < '0') or (Value[I] > '9') then exit;
  Result := True;
end;

function SelectedTransport: String;
begin
  case TransportPage.SelectedValueIndex of
    1: Result := 'serial';
    2: Result := 'tcp';
    3: Result := 'ble';
  else Result := ''; end;
end;

procedure InitializeWizard;
var Choice: String;
begin
  TransportPage := CreateInputOptionPage(wpSelectDir, 'Radio connection',
    'Choose how this computer reaches the companion node.',
    'Existing settings are preserved unless you select a connection. New installations default to USB serial auto detection. Pair BLE in the OS before starting the service.', True, False);
  TransportPage.Add('Preserve existing settings (new installation: USB serial auto)');
  TransportPage.Add('USB serial');
  TransportPage.Add('Wi-Fi / TCP');
  TransportPage.Add('Bluetooth LE (previously paired device)');
  Choice := LowerCase(ExpandConstant('{param:TRANSPORT|}'));
  TransportPage.SelectedValueIndex := 0;
  if Choice = 'serial' then TransportPage.SelectedValueIndex := 1;
  if Choice = 'tcp' then TransportPage.SelectedValueIndex := 2;
  if Choice = 'ble' then TransportPage.SelectedValueIndex := 3;
  // Keep legacy /SERIALPORT invocations working; endpoint options can infer type.
  if Choice = '' then begin
    if ExpandConstant('{param:SERIALPORT|}') <> '' then TransportPage.SelectedValueIndex := 1;
    if ExpandConstant('{param:TCPHOST|}') <> '' then TransportPage.SelectedValueIndex := 2;
    if ExpandConstant('{param:BLEADDRESS|}') <> '' then TransportPage.SelectedValueIndex := 3;
  end;
  EndpointPage := CreateInputQueryPage(TransportPage.ID, 'Companion radio settings',
    'Fill only the fields for the selected connection.',
    'TCP uses the node IP and defaults to port 5000. BLE uses an explicit paired address. Radio channels must already exist; setup never overwrites them.');
  EndpointPage.Add('Serial port (auto or COM number):', False);
  EndpointPage.Add('TCP node IP address:', False);
  EndpointPage.Add('TCP port:', False);
  EndpointPage.Add('BLE address (AA:BB:CC:DD:EE:FF):', False);
  PortPage := CreateInputQueryPage(EndpointPage.ID, 'Radio channels',
    'Preserve channels or import settings.',
    'Leave both fields blank to preserve current/default channels. Setup never programs the radio.');
  PortPage.Add('Channel name (blank preserves current/default):', False);
  PortPage.Add('Channels JSON file (optional; instead of channel name):', False);
  EndpointPage.Values[0] := ExpandConstant('{param:SERIALPORT|auto}');
  EndpointPage.Values[1] := ExpandConstant('{param:TCPHOST|}');
  EndpointPage.Values[2] := ExpandConstant('{param:TCPPORT|5000}');
  EndpointPage.Values[3] := ExpandConstant('{param:BLEADDRESS|}');
  PortPage.Values[0] := ExpandConstant('{param:CHANNEL|}');
  PortPage.Values[1] := ExpandConstant('{param:CHANNELSCONFIG|}');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = EndpointPage.ID then begin
    EndpointPage.Edits[0].Enabled := SelectedTransport = 'serial';
    EndpointPage.Edits[1].Enabled := SelectedTransport = 'tcp';
    EndpointPage.Edits[2].Enabled := SelectedTransport = 'tcp';
    EndpointPage.Edits[3].Enabled := SelectedTransport = 'ble';
  end;
end;

function ValidateSettings: String;
var I, Port: Integer; Choice, Mode: String;
begin
  Result := '';
  Mode := SelectedTransport;
  Choice := LowerCase(ExpandConstant('{param:TRANSPORT|}'));
  if (Choice <> '') and (Choice <> 'serial') and (Choice <> 'tcp') and (Choice <> 'ble') then begin
    Result := 'TRANSPORT must be serial, tcp or ble.'; exit;
  end;
  if ((ExpandConstant('{param:SERIALPORT|}') <> '') and (Mode <> 'serial')) or
     ((ExpandConstant('{param:TCPHOST|}') <> '') and (Mode <> 'tcp')) or
     ((ExpandConstant('{param:TCPPORT|}') <> '') and (Mode <> 'tcp')) or
     ((ExpandConstant('{param:BLEADDRESS|}') <> '') and (Mode <> 'ble')) then begin
    Result := 'Connection arguments must select only one transport.'; exit;
  end;
  for I := 0 to 1 do
    if (Pos('"', PortPage.Values[I]) <> 0) or (Pos(#13, PortPage.Values[I]) <> 0) or (Pos(#10, PortPage.Values[I]) <> 0) then begin
      Result := 'Settings cannot contain double quotes or newlines.'; exit;
    end;
  for I := 0 to 3 do
    if (Pos('"', EndpointPage.Values[I]) <> 0) or (Pos(#13, EndpointPage.Values[I]) <> 0) or (Pos(#10, EndpointPage.Values[I]) <> 0) then begin
      Result := 'Settings cannot contain double quotes or newlines.'; exit;
    end;
  if (Mode = 'serial') and not ValidPort(EndpointPage.Values[0]) then begin
    Result := 'Use auto or a specific COM port.'; exit;
  end;
  if Mode = 'tcp' then begin
    Port := StrToIntDef(EndpointPage.Values[2], 0);
    if (EndpointPage.Values[1] = '') or (Port < 1) or (Port > 65535) then begin
      Result := 'Supply a TCP node IP and port from 1 to 65535.'; exit;
    end;
  end;
  if (Mode = 'ble') and (EndpointPage.Values[3] = '') then begin
    Result := 'Supply the paired BLE device address.'; exit;
  end;
  if ((PortPage.Values[0] <> '') and (PortPage.Values[1] <> '')) or
    ((PortPage.Values[1] <> '') and not FileExists(PortPage.Values[1])) then
    Result := 'Use a channel name or an existing channels JSON file.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Error: String;
begin
  Result := True;
  if CurPageID = PortPage.ID then begin
    Error := ValidateSettings;
    Result := Error = '';
    if not Result then MsgBox(Error, mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  // Validate silent-install arguments and stop this service before replacing files.
  Result := ValidateSettings;
  if Result <> '' then exit;
  // Stop only this product before replacing its executable or Python source.
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -Command "if (Get-Service MeshCoreEMS -ErrorAction SilentlyContinue) { Stop-Service MeshCoreEMS -ErrorAction Stop; (Get-Service MeshCoreEMS).WaitForStatus(''Stopped'', [TimeSpan]::FromSeconds(50)) }"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      Result := 'Could not stop the existing MeshCore EMS service.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Params: String;
begin
  // Pass the chosen detection policy and channel import to post-copy configuration.
  if CurStep = ssPostInstall then begin
    Params := '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\installers\windows\install.ps1') +
      '" -InstallRoot "' + ExpandConstant('{app}') + '"';
    if SelectedTransport <> '' then Params := Params + ' -Transport "' + SelectedTransport + '"';
    if SelectedTransport = 'serial' then Params := Params + ' -SerialPort "' + EndpointPage.Values[0] + '"';
    if SelectedTransport = 'tcp' then Params := Params + ' -TcpHost "' + EndpointPage.Values[1] + '" -TcpPort ' + EndpointPage.Values[2];
    if SelectedTransport = 'ble' then Params := Params + ' -BleAddress "' + EndpointPage.Values[3] + '"';
    if PortPage.Values[0] <> '' then Params := Params + ' -Channel "' + PortPage.Values[0] + '"';
    if PortPage.Values[1] <> '' then Params := Params + ' -ChannelsConfig "' + PortPage.Values[1] + '"';
    if ExpandConstant('{param:NOSTART|0}') = '1' then Params := Params + ' -NoStart';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
      ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, Code) or (Code <> 0) then
      RaiseException('Dependency or service setup failed. See ProgramData\MeshCore-EMS\install.log. Correct the reported issue and rerun this installer.');
  end;
end;
