$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & '.\setup.ps1'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& '.\.venv\Scripts\python.exe' -c 'import meshcore_cli, meshcore, paho.mqtt.client, amqtt, serial'
if ($LASTEXITCODE -ne 0) {
    Write-Error 'Dependencies are incomplete. Run setup.cmd before starting.'
    exit 1
}
if ($args.Count -eq 0) {
    & '.\.venv\Scripts\python.exe' service.py bridge
} else {
    & '.\.venv\Scripts\python.exe' service.py @args
}
exit $LASTEXITCODE
