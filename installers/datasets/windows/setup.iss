#ifndef PayloadDir
  #error Define PayloadDir
#endif
#ifndef ReleaseDir
  #error Define ReleaseDir
#endif
#ifndef Dataset
  #error Define Dataset
#endif
#ifndef ReleaseVersion
  #error Define ReleaseVersion
#endif
#ifndef DatasetName
  #define DatasetName Dataset
#endif
#ifndef MaintenanceExe
  #error Define MaintenanceExe (PS2EXE build of dataset.ps1)
#endif
[Setup]
; Stable and unique per collection, independent of the main service AppId.
AppId=MeshCore-EMS-Data-{#Dataset}
AppName=MeshCore EMS Dataset - {#DatasetName}
UninstallDisplayName=MeshCore EMS Dataset - {#DatasetName}
AppVersion={#ReleaseVersion}
AppPublisher=Usrnmna
DefaultDirName={autopf}\MeshCore-EMS-Data\{#Dataset}
DefaultGroupName=MeshCore EMS\Datasets\{#DatasetName}
UsePreviousGroup=no
UninstallDisplayIcon={app}\Dataset.exe
OutputDir={#ReleaseDir}
OutputBaseFilename=MeshCore-EMS-Data-{#Dataset}-{#ReleaseVersion}-windows-x64-setup
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile={#PayloadDir}\LICENSE
SetupLogging=yes
CloseApplications=no
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}\payload"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#MaintenanceExe}"; DestDir: "{app}"; DestName: "Dataset.exe"; Flags: ignoreversion

[InstallDelete]
; Remove only known obsolete launchers; keep data and stable package identity.
Type: files; Name: "{app}\dataset.cmd"
Type: files; Name: "{commonprograms}\MeshCore EMS Data\{#Dataset}\Dataset guide.lnk"
Type: files; Name: "{commonprograms}\MeshCore EMS Data\{#Dataset}\Uninstall dataset.lnk"
Type: dirifempty; Name: "{commonprograms}\MeshCore EMS Data\{#Dataset}"
Type: dirifempty; Name: "{commonprograms}\MeshCore EMS Data"

[Icons]
Name: "{group}\Manage {#DatasetName}"; Filename: "{app}\Dataset.exe"; WorkingDir: "{app}"
Name: "{group}\Guide"; Filename: "{app}\payload\docs\DATA_PACKAGES.md"
Name: "{group}\Uninstall {#DatasetName}"; Filename: "{uninstallexe}"

[UninstallDelete]
; Dataset storage is outside {app} and is exclusively owned by manage.py.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\environments"
Type: files; Name: "{app}\runtime.json"
Type: files; Name: "{app}\runtime.next.json"

[Code]
var DatasetPreparationFailed: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Parameters: String;
begin
  if CurStep = ssPostInstall then begin
    DatasetPreparationFailed := True;
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\payload\installers\datasets\windows\run_logged.ps1') + '" -Action install -InstallRoot "' + ExpandConstant('{app}') + '"';
    if ExpandConstant('{param:DATAROOT|}') <> '' then Parameters := Parameters + ' -Root "' + ExpandConstant('{param:DATAROOT|}') + '"';
    if Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters, '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0) then
      DatasetPreparationFailed := False
    else
      SuppressibleMsgBox('Dataset preparation did not complete. Existing local data was retained. Review the logs in ' + ExpandConstant('{app}\logs') + ' and retry setup or Dataset.exe install.', mbError, MB_OK, IDOK);
  end;
end;

function GetCustomSetupExitCode(): Integer;
begin
  if DatasetPreparationFailed then Result := 20 else Result := 0;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and DatasetPreparationFailed then begin
    WizardForm.FinishedHeadingLabel.Caption := 'Dataset setup incomplete';
    WizardForm.FinishedLabel.Caption := 'The dataset was not activated. Existing local data was retained. Review the logs in ' + ExpandConstant('{app}\logs') + ' before retrying.';
  end;
end;

function InitializeUninstall(): Boolean;
var Code: Integer; Parameters: String;
begin
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\payload\installers\datasets\windows\run_logged.ps1') + '" -Action uninstall -InstallRoot "' + ExpandConstant('{app}') + '"';
  if ExpandConstant('{param:PURGE|0}') = '1' then Parameters := Parameters + ' -Purge';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parameters, '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then SuppressibleMsgBox('Dataset removal was refused or failed. Data and maintenance tools were retained. Review the logs in ' + ExpandConstant('{app}\logs') + ' and check dependent datasets before retrying.', mbError, MB_OK, IDOK);
end;
