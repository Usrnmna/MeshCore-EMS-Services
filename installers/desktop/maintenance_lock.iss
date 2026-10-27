// Included by independent Inno packages after their global declarations.
var MaintenanceAcquired: Boolean;
    MaintenanceHelper, MaintenancePrevious: String;

function MaintenanceProcessId(): LongWord;
  external 'GetCurrentProcessId@kernel32.dll stdcall';
function MaintenanceSetEnvironment(Name, Value: String): Boolean;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function AcquireMaintenance(InstalledHelper: String): Boolean;
var Code, I: Integer; OutputPath, Parameters: String; Token: AnsiString;
begin
  Result := False;
  MaintenancePrevious := GetEnv('MESHCORE_MAINTENANCE_LEASE');
  MaintenanceHelper := ExpandConstant('{tmp}\_maintenance_lock.ps1');
  if IsUninstaller then begin
    if not FileCopy(InstalledHelper, MaintenanceHelper, False) then exit;
  end else ExtractTemporaryFile('_maintenance_lock.ps1');
  OutputPath := ExpandConstant('{autopf}\MeshCore-EMS-Maintenance\inno-') + IntToStr(MaintenanceProcessId()) + '.token';
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + MaintenanceHelper +
    '" -AcquireForProcess ' + IntToStr(MaintenanceProcessId()) + ' -TokenOutput "' + OutputPath + '"';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters, '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then begin
    SuppressibleMsgBox('Another maintenance operation or an interrupted lease prevents this operation. Review maintenance diagnostics before retrying.', mbError, MB_OK, IDOK);
    exit;
  end;
  if not LoadStringFromFile(OutputPath, Token) or (Length(Token) <> 32) then exit;
  for I := 1 to Length(Token) do if Pos(Token[I], '0123456789abcdef') = 0 then exit;
  DeleteFile(OutputPath);
  if not MaintenanceSetEnvironment('MESHCORE_MAINTENANCE_LEASE', String(Token)) then exit;
  MaintenanceAcquired := True;
  Result := True;
end;

procedure ReleaseMaintenance;
var Code: Integer; Parameters: String;
begin
  if not MaintenanceAcquired then exit;
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + MaintenanceHelper +
    '" -ReleaseForProcess ' + IntToStr(MaintenanceProcessId());
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters, '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    Log('Maintenance lease release failed; protected recovery inspection is required.');
  MaintenanceSetEnvironment('MESHCORE_MAINTENANCE_LEASE', MaintenancePrevious);
  MaintenanceAcquired := False;
end;

function InitializeSetup(): Boolean;
begin
  Result := AcquireMaintenance('');
end;

procedure DeinitializeSetup;
begin
  ReleaseMaintenance;
end;

procedure DeinitializeUninstall;
begin
  ReleaseMaintenance;
end;
