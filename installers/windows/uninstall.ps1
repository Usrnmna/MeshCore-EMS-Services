$ErrorActionPreference = 'Stop'
$service = Get-Service MeshCoreEMS -ErrorAction SilentlyContinue
if ($service) {
    Stop-Service MeshCoreEMS
    $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(50))
    & sc.exe delete MeshCoreEMS
    if ($LASTEXITCODE -ne 0) { throw 'Could not unregister MeshCoreEMS.' }
}
Write-Host 'The service was removed. ProgramData\MeshCore-EMS settings and data are retained.'
