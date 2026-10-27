param([Parameter(Mandatory=$true)][string]$InstallRoot, [switch]$Purge, [switch]$RemoveData)
$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$settingsPath = Join-Path $InstallRoot 'runtime.json'
# Bootstrap failures can leave tools without any installed dataset selection.
if (-not (Test-Path -LiteralPath $settingsPath)) { exit 0 }
$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
$arguments = @('uninstall','--dataset',$settings.dataset,'--root',$settings.root,'--payload',(Join-Path $InstallRoot 'payload'))
if ($Purge) { $arguments += '--purge' }
elseif (-not $RemoveData) { $arguments += '--retain-data' }
& $settings.python (Join-Path $InstallRoot 'payload\installers\datasets\manage.py') @arguments
exit $LASTEXITCODE
