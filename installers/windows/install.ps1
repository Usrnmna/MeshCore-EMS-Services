param(
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [Parameter(Mandatory=$true)][ValidatePattern('^COM[1-9][0-9]*$')][string]$SerialPort,
    [string]$Channel = '',
    [string]$StateRoot = (Join-Path $env:ProgramData 'MeshCore-EMS'),
    [switch]$PrepareOnly,
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$StateRoot = [IO.Path]::GetFullPath($StateRoot)
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
if (-not $PrepareOnly) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run setup as administrator.' }
    if ($StateRoot -ne (Join-Path $env:ProgramData 'MeshCore-EMS')) { throw 'The Windows service uses ProgramData\MeshCore-EMS.' }
    $existing = Get-Service MeshCoreEMS -ErrorAction SilentlyContinue
    if ($existing) { Stop-Service MeshCoreEMS; $existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(50)) }
}
New-Item -ItemType Directory -Force $StateRoot | Out-Null
Start-Transcript -Path (Join-Path $StateRoot 'install.log') -Append | Out-Null
try {
    $python = Join-Path $InstallRoot 'python\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host 'Downloading private Python 3.13.15 x64 from the CPython NuGet package...'
        $download = Join-Path $InstallRoot 'python-runtime.zip'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://www.nuget.org/api/v2/package/python/3.13.15' -OutFile $download
        $expected = '05357887df50d3153efc681bdf432c321d3e2f9ce5788f99f4515b27e8fda0ac'
        if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash -ne $expected) { throw 'Python download checksum mismatch.' }
        $expanded = Join-Path $InstallRoot 'python-download'
        Expand-Archive -LiteralPath $download -DestinationPath $expanded -Force
        Move-Item -LiteralPath (Join-Path $expanded 'tools') -Destination (Join-Path $InstallRoot 'python')
        # Only remove the two exact bootstrap paths inside the selected installation.
        $resolvedExpanded = [IO.Path]::GetFullPath($expanded)
        if ($resolvedExpanded -ne (Join-Path $InstallRoot 'python-download')) { throw 'Invalid cleanup path.' }
        Remove-Item -LiteralPath $resolvedExpanded -Recurse -Force
        Remove-Item -LiteralPath $download -Force
    }
    & $python -I -c "import sys,struct; assert sys.version_info[:2] == (3,13) and struct.calcsize('P') == 8"
    if ($LASTEXITCODE -ne 0) { throw 'The private Python runtime is invalid.' }
    & $python -I -m pip install --disable-pip-version-check --no-warn-script-location -r (Join-Path $InstallRoot 'meshcore_mqtt_service_windows\requirements.txt') -r (Join-Path $InstallRoot 'satellite_database\requirements-tracking.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet access and rerun setup.' }
    & $python -I -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
    $configArgs = @('--root',$InstallRoot,'--state',$StateRoot,'--config-dir',$StateRoot,'--platform','windows','--port',$SerialPort)
    if ($Channel) { $configArgs += @('--channel',$Channel) }
    & $python (Join-Path $InstallRoot 'installers\configure.py') @configArgs
    if ($LASTEXITCODE -ne 0) { throw 'Configuration failed.' }
    $env:PYTHONNOUSERSITE = '1'
    & $python (Join-Path $InstallRoot 'meshcore_mqtt_service_windows\service_runner.py') --config (Join-Path $StateRoot 'config.json') --state-dir (Join-Path $StateRoot 'runtime') --environment (Join-Path $StateRoot 'environment.json') --check
    if ($LASTEXITCODE -ne 0) { throw 'Service readiness check failed.' }
    if (-not $PrepareOnly) {
        # Config/credentials: administrators can modify; LocalService can read.
        & icacls.exe $StateRoot /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-19:(OI)(CI)RX'
        if ($LASTEXITCODE -ne 0) { throw 'Could not secure service settings.' }
        foreach ($folder in @('runtime','data')) {
            & icacls.exe (Join-Path $StateRoot $folder) /grant '*S-1-5-19:(OI)(CI)M' /T /Q
            if ($LASTEXITCODE -ne 0) { throw 'Could not grant runtime permissions.' }
        }
        # Explicit Windows argv quoting keeps spaces inside SCM's quoted executable path,
        # including when this script is invoked by Windows PowerShell 5.1.
        $verb = if (Get-Service MeshCoreEMS -ErrorAction SilentlyContinue) { 'config' } else { 'create' }
        $binaryPath = Join-Path $InstallRoot 'MeshCoreEMS.Service.exe'
        $scStart = New-Object System.Diagnostics.ProcessStartInfo
        $scStart.FileName = Join-Path $env:SystemRoot 'System32\sc.exe'
        $scStart.Arguments = $verb + ' MeshCoreEMS binPath= "\"' + $binaryPath + '\"" start= delayed-auto obj= "NT AUTHORITY\LocalService" DisplayName= "MeshCore EMS Services"'
        $scStart.UseShellExecute = $false
        $scStart.CreateNoWindow = $true
        $scProcess = [System.Diagnostics.Process]::Start($scStart)
        $scProcess.WaitForExit()
        if ($scProcess.ExitCode -ne 0) { throw 'Windows service registration failed.' }
        & sc.exe description MeshCoreEMS 'MeshCore EMS v0.2.0-alpha USB/MQTT responder'
        & sc.exe failure MeshCoreEMS reset= 86400 actions= restart/15000/restart/30000/restart/60000
        if ($LASTEXITCODE -ne 0) { throw 'Service recovery setup failed.' }
        if (-not $NoStart) {
            Start-Service MeshCoreEMS
            Start-Sleep -Seconds 3
            if ((Get-Service MeshCoreEMS).Status -ne 'Running') { throw 'Service stopped; inspect runtime\service.log and wrapper.log.' }
        }
    }
    Write-Host 'MeshCore EMS v0.2.0-alpha installation prepared successfully.'
    Write-Host "Configuration and data: $StateRoot"
} finally {
    Stop-Transcript | Out-Null
}
