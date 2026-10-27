<#
.SYNOPSIS
Inspect and maintain the dataset installed beside Dataset.exe.
.DESCRIPTION
Run without arguments for the menu, or supply an action for terminal automation.
Updates and removal require an administrator terminal. Failed updates retain the
selected local dataset. The uninstall action removes data; Installed Apps also
removes the package tools. Source invocation remains available for diagnostics.
#>
param(
    [string]$Action = 'menu',
    [string]$Resume,
    [string]$ReviewedLock,
    [switch]$Purge
)
$ErrorActionPreference = 'Stop'
try {
    # Validate inside the protected body: PS2EXE can report a parameter attribute
    # binding error without setting a failing process exit code.
    if ($args.Count) { throw ('Unexpected arguments: ' + ($args -join ' ')) }
    if ($Action -notin @('menu','install','update','verify','status','rollback','uninstall','recover-lock')) { throw 'Unknown dataset action.' }
    if ($Resume -and $Resume -cnotmatch '^[a-f0-9]{32}$') { throw '-Resume requires a 32-character lowercase hexadecimal candidate identifier.' }
    # PS2EXE supplies ScriptRoot for the executable location. The maintained
    # source lives four directories below the installation root instead.
    if ($PSScriptRoot) {
        $installRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\..'))
    } else {
        $installRoot = [IO.Path]::GetFullPath($ScriptRoot)
    }
    if ($Purge -and $Action -ne 'uninstall') { throw '-Purge is valid only with uninstall.' }
    if ($Resume -and $Action -notin @('install','update')) { throw '-Resume requires install or update.' }
    if (($Action -eq 'recover-lock') -ne [bool]$ReviewedLock -or ($ReviewedLock -and $ReviewedLock -cnotmatch '^[a-f0-9]{64}$')) { throw 'Lock recovery requires an exact reviewed fingerprint.' }
    $settings = Get-Content -LiteralPath (Join-Path $installRoot 'runtime.json') -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $settings.python -PathType Leaf)) { throw 'Maintenance runtime missing; rerun the dataset installer.' }
    $manager = Join-Path $installRoot 'payload\installers\datasets\manage.py'
    if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) { throw 'Dataset manager missing; rerun the dataset installer.' }
    $menu = $Action -eq 'menu'
    do {
        if ($menu) {
            Write-Host ('MeshCore EMS Dataset - ' + $settings.dataset)
            Write-Host '1 Status   2 Verify   3 Update   4 Roll back   5 Remove package   0 Exit'
            Write-Host 'Updates and removal require Run as administrator. Failed updates preserve local data.'
            # Console.ReadLine also supports redirected input in unattended smoke
            # tests; PS2EXE's Read-Host adapter requires an interactive console.
            [Console]::Write('Select: ')
            $choice = [Console]::ReadLine()
            if ($choice -eq '0' -or $null -eq $choice) { exit 0 }
            if ($choice -eq '5') {
                # Use the OS uninstaller so package removal also removes tools.
                $uninstaller = Join-Path $installRoot 'unins000.exe'
                if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) { throw 'Package uninstaller missing; use Installed Apps or repair setup.' }
                Start-Process -FilePath $uninstaller
                exit 0
            }
            $Action = @{'1'='status';'2'='verify';'3'='update';'4'='rollback'}[$choice]
            if (-not $Action) { Write-Host 'Select a listed number.'; continue }
        }
        $arguments = @($Action, '--dataset', $settings.dataset, '--root', $settings.root, '--payload', (Join-Path $installRoot 'payload'))
        if ($Resume) { $arguments += @('--resume', $Resume) }
        if ($ReviewedLock) { $arguments += @('--reviewed-lock', $ReviewedLock) }
        if ($Purge) { $arguments += '--purge' }
        # Native stderr is diagnostic output, not a terminating PowerShell error.
        # Preserve the actual child exit code even when it writes to stderr.
        $lease = $null
        if ($Action -in @('install','update','rollback','uninstall','recover-lock')) {
            . (Join-Path $installRoot 'payload\installers\desktop\maintenance_lock.ps1')
            $lease = Enter-MeshCoreMaintenance
        }
        try {
            $ErrorActionPreference = 'Continue'
            & $settings.python $manager @arguments
            $code = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = 'Stop'
            if ($lease) { Exit-MeshCoreMaintenance $lease }
        }
        if (-not $menu) { exit $code }
        Write-Host ('Operation exit code: ' + $code)
    } while ($menu)
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
