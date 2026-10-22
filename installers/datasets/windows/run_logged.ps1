param(
    [Parameter(Mandatory=$true)][ValidateSet('install','uninstall')][string]$Action,
    [Parameter(Mandatory=$true)][string]$InstallRoot,
    [string]$Root = '',
    [switch]$Purge
)
$ErrorActionPreference = 'Stop'
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$logs = Join-Path $InstallRoot 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$run = $Action + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N')
$stdout = Join-Path $logs ($run + '.stdout.log')
$stderr = Join-Path $logs ($run + '.stderr.log')
$resultPath = Join-Path $logs ($run + '.result.json')
$started = [DateTime]::UtcNow.ToString('o')
$code = 1
try {
    $script = Join-Path $InstallRoot ('payload\installers\datasets\windows\' + $Action + '.ps1')
    if (-not (Test-Path -LiteralPath $script -PathType Leaf)) { throw 'Dataset maintenance script is missing.' }
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $script + '" -InstallRoot "' + $InstallRoot + '"'
    if ($Root) {
        if ($Action -ne 'install') { throw 'A data-root override is only valid during installation.' }
        $arguments += ' -Root "' + [IO.Path]::GetFullPath($Root) + '"'
    }
    if ($Purge) {
        if ($Action -ne 'uninstall') { throw 'Purge is only valid during removal.' }
        $arguments += ' -Purge'
    }
    # File redirection drains output independently of the setup launcher's console
    # and preserves diagnostics for unattended, elevated, and failed operations.
    $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $code = $process.ExitCode
}
catch {
    [IO.File]::AppendAllText($stderr, $_.Exception.ToString() + [Environment]::NewLine)
}
finally {
    $result = @{action=$Action;started_at=$started;completed_at=[DateTime]::UtcNow.ToString('o');exit_code=$code;stdout=$stdout;stderr=$stderr} | ConvertTo-Json
    [IO.File]::WriteAllText($resultPath, $result, (New-Object Text.UTF8Encoding($false)))
}
exit $code
