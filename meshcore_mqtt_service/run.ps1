$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & '.\setup.ps1'
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($args.Count -eq 0) {
    & '.\.venv\Scripts\python.exe' service.py bridge
} else {
    & '.\.venv\Scripts\python.exe' service.py @args
}
exit $LASTEXITCODE
