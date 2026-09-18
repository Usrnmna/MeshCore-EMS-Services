param([string]$PythonExe = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$probe = "import sys,struct; assert sys.platform == 'win32' and sys.version_info >= (3,11) and struct.calcsize('P') == 8; print(sys.executable)"
if (-not $PythonExe) {
    foreach ($candidate in @('py', 'python')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $launcherArgs = @()
            if ($candidate -eq 'py') { $launcherArgs = @('-3') }
            $found = & $candidate @launcherArgs -c $probe 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) {
                $PythonExe = [string]($found | Select-Object -Last 1)
                break
            }
        }
    }
}
if (-not $PythonExe) { throw 'Install 64-bit Python 3.11 or newer, or pass -PythonExe with its full path.' }
& $PythonExe -c $probe
if ($LASTEXITCODE -ne 0) { throw 'This package requires 64-bit Windows Python 3.11 or newer.' }
$localPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $localPython)) {
    & $PythonExe -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $localPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $localPython -m pip check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Windows service folder is ready. Run run.cmd to select a COM device and start.'
exit 0
