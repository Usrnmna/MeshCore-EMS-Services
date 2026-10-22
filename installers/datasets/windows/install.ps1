param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$Root = ''
)

function Publish-RuntimeSettings {
    param([string]$TemporarySettings, [string]$SettingsPath)
    # A real backup path avoids Windows PowerShell 5.1 converting a null string
    # argument into an invalid empty path. Replacement remains atomic.
    if (Test-Path -LiteralPath $SettingsPath) {
        $backup = $SettingsPath + '.' + [guid]::NewGuid().ToString('N') + '.previous'
        [IO.File]::Replace($TemporarySettings, $SettingsPath, $backup)
        [IO.File]::Delete($backup)
    }
    else { [IO.File]::Move($TemporarySettings, $SettingsPath) }
}

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$payload = Join-Path $InstallRoot 'payload'
$dataset = (Get-Content -LiteralPath (Join-Path $payload 'dataset-id.txt') -Raw).Trim()
if ($dataset -notin @('ebmud','basin_plans','flood_impacts','usgs_water','wildfire','landslide','california_state_parks','satellites')) { throw 'Invalid dataset identifier.' }
$settingsPath = Join-Path $InstallRoot 'runtime.json'
if (-not $Root) {
    if (Test-Path -LiteralPath $settingsPath) { $Root = (Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json).root }
    else { $Root = Join-Path $env:ProgramData 'MeshCore-EMS\data' }
}
if (-not [IO.Path]::IsPathRooted($Root)) { throw 'Data root must be absolute.' }
$Root = [IO.Path]::GetFullPath($Root)
if (($Root + '\').StartsWith($InstallRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Data root must be outside the maintenance installation.' }
New-Item -ItemType Directory -Force -Path $Root | Out-Null
# Service-first and dataset-first installation both permit LocalService to read data.
& icacls.exe $Root /grant '*S-1-5-19:(OI)(CI)RX' /Q
if ($LASTEXITCODE -ne 0) { throw 'Could not grant service read access to the data directory.' }
# The private interpreter does not depend on the service or a machine Python installation.
$basePython = Join-Path $InstallRoot 'python\python.exe'
if (-not (Test-Path -LiteralPath $basePython)) {
    $bootstrap = Join-Path $InstallRoot ('bootstrap-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $bootstrap | Out-Null
    $archive = Join-Path $bootstrap 'python.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.nuget.org/api/v2/package/python/3.13.15' -OutFile $archive
    $expected = '05357887df50d3153efc681bdf432c321d3e2f9ce5788f99f4515b27e8fda0ac'
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) { throw 'Python download checksum mismatch.' }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $bootstrap 'expanded')
    $source = [IO.Path]::GetFullPath((Join-Path $bootstrap 'expanded\tools'))
    $destination = [IO.Path]::GetFullPath((Join-Path $InstallRoot 'python'))
    if (-not $source.StartsWith($InstallRoot + '\') -or $destination -ne (Join-Path $InstallRoot 'python')) { throw 'Invalid bootstrap paths.' }
    Move-Item -LiteralPath $source -Destination $destination
    if (-not ([IO.Path]::GetFullPath($bootstrap)).StartsWith($InstallRoot + '\bootstrap-')) { throw 'Invalid cleanup path.' }
    Remove-Item -LiteralPath $bootstrap -Recurse -Force
}
& $basePython -I -c "import sys,struct; assert sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8"
if ($LASTEXITCODE -ne 0) { throw 'Private Python validation failed.' }
# Build each environment at its permanent path; never modify the working environment.
$venv = Join-Path $InstallRoot ('environments\' + [guid]::NewGuid().ToString('N'))
& $basePython -I -m venv $venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create maintenance environment.' }
$python = Join-Path $venv 'Scripts\python.exe'
& $python -I -m pip install --disable-pip-version-check --only-binary=:all: -r (Join-Path $payload 'installers\datasets\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; existing local data is unchanged.' }
& $python -I -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed; existing local data is unchanged.' }
$settings = @{python=$python;root=$Root;dataset=$dataset} | ConvertTo-Json
$temporarySettings = Join-Path $InstallRoot 'runtime.next.json'
[IO.File]::WriteAllText($temporarySettings, $settings, (New-Object Text.UTF8Encoding($false)))
Publish-RuntimeSettings -TemporarySettings $temporarySettings -SettingsPath $settingsPath
& $python (Join-Path $payload 'installers\datasets\manage.py') install --dataset $dataset --root $Root --payload $payload
if ($LASTEXITCODE -ne 0) { throw 'Dataset acquisition failed. Valid existing local data was retained. Use Dataset.exe install to retry.' }
