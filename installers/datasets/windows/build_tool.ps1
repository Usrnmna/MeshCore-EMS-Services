param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Version = '0.9.8.0'
)
$ErrorActionPreference = 'Stop'
try {
    # Pin the host/compiler semantics, particularly ScriptRoot support. PS2EXE
    # is a build dependency only; generated programs use Windows PowerShell 5.1.
    Import-Module ps2exe -RequiredVersion 1.0.18 -ErrorAction Stop
    Invoke-ps2exe -InputFile $Source -OutputFile $Output -x64 -version $Version `
        -title 'MeshCore EMS Dataset' -product 'MeshCore EMS' `
        -description 'Dataset status, verification, updates and recovery' -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $Output -PathType Leaf)) { throw 'PS2EXE did not produce Dataset.exe.' }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
