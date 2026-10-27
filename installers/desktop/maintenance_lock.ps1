param([int]$AcquireForProcess = 0, [int]$ReleaseForProcess = 0, [string]$TokenOutput = '')
# Fixed native backends share an administrator/System-only maintenance lease.
function New-MeshCorePrivateFile([string]$Path) {
    $security = New-Object Security.AccessControl.FileSecurity
    $security.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)')
    return New-Object IO.FileStream($Path, [IO.FileMode]::CreateNew, [Security.AccessControl.FileSystemRights]::FullControl, [IO.FileShare]::Read, 4096, [IO.FileOptions]::None, $security)
}

function Assert-MeshCoreRecordOwner([string]$Path) {
    $owner = [IO.File]::GetAccessControl($Path).GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($owner -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Maintenance record has an untrusted owner; it was not changed.' }
}

function Write-MeshCorePrivateRecord([string]$Path, [string]$Content) {
    $stream = New-MeshCorePrivateFile $Path
    try {
        $bytes = [Text.Encoding]::ASCII.GetBytes($Content)
        $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true)
    } finally { $stream.Dispose() }
}

function Enter-MeshCoreMaintenance {
    $directory = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'MeshCore-EMS-Maintenance'
    $cursor = [IO.DirectoryInfo]$directory
    while ($cursor) {
        if ($cursor.Exists -and ($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Maintenance directory ancestors cannot be reparse points.' }
        $cursor = $cursor.Parent
    }
    $security = New-Object Security.AccessControl.DirectorySecurity
    $security.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
    if (Test-Path -LiteralPath $directory -PathType Container) {
        $existingOwner = [IO.Directory]::GetAccessControl($directory).GetOwner([Security.Principal.SecurityIdentifier]).Value
        if ($existingOwner -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Existing maintenance directory has an untrusted owner; protected native repair is required.' }
    }
    [IO.Directory]::CreateDirectory($directory, $security) | Out-Null
    [IO.Directory]::SetAccessControl($directory, $security)
    if (Test-Path -LiteralPath (Join-Path $directory 'recovery-guard')) { throw 'Maintenance recovery is pending; inspect recovery first.' }
    $path = Join-Path $directory 'lease'
    $previous = $env:MESHCORE_MAINTENANCE_LEASE
    $token = [guid]::NewGuid().ToString('N')
    $identity = [Diagnostics.Process]::GetCurrentProcess().StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
    $owned = $false
    try {
        $stream = New-MeshCorePrivateFile $path
        try {
            $content = [Text.Encoding]::ASCII.GetBytes("$PID`n$identity`n$token`n")
            $stream.Write($content, 0, $content.Length)
            $stream.Flush($true)
            $owned = $true
        } finally { $stream.Dispose() }
    } catch [IO.IOException] {
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Maintenance lease cannot be a reparse point.' }
        Assert-MeshCoreRecordOwner $path
        $record = [IO.File]::ReadAllLines($path)
        if ($record.Length -ne 3 -or $record[0] -notmatch '^\d+$' -or $record[1] -notmatch '^\d+$' -or $record[2] -cnotmatch '^[0-9a-f]{32}$') { throw 'Invalid maintenance lease.' }
        $owner = [Diagnostics.Process]::GetProcessById([int]$record[0])
        if ($previous -cne $record[2] -or $owner.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -cne $record[1]) { throw 'Another maintenance operation or interrupted lease exists. Inspect it before recovery.' }
        $token = $record[2]
    }
    $env:MESHCORE_MAINTENANCE_LEASE = $token
    $participants = Join-Path $directory ('participants-' + $token)
    if ($owned) {
        [IO.Directory]::CreateDirectory($participants, $security) | Out-Null
        Write-MeshCorePrivateRecord (Join-Path $participants 'PROTOCOL') "2`n"
    }
    if (-not (Test-Path -LiteralPath $participants -PathType Container) -or (Get-Item -LiteralPath $participants).Attributes -band [IO.FileAttributes]::ReparsePoint -or [IO.File]::ReadAllText((Join-Path $participants 'PROTOCOL')) -cne "2`n") { throw 'Unknown maintenance participant protocol.' }
    $participantOwner = [IO.Directory]::GetAccessControl($participants).GetOwner([Security.Principal.SecurityIdentifier]).Value
    if ($participantOwner -notin @('S-1-5-18','S-1-5-32-544')) { throw 'Maintenance participant directory has an untrusted owner.' }
    Assert-MeshCoreRecordOwner (Join-Path $participants 'PROTOCOL')
    $participant = Join-Path $participants ($PID.ToString() + '-' + $identity + '.participant')
    $participantOwned = $false
    try {
        $stream = New-MeshCorePrivateFile $participant
        try {
            $content = [Text.Encoding]::ASCII.GetBytes("$PID`n$identity`n$token`n")
            $stream.Write($content, 0, $content.Length); $stream.Flush($true); $participantOwned = $true
        } finally { $stream.Dispose() }
    } catch [IO.IOException] {
        Assert-MeshCoreRecordOwner $participant
        if ([IO.File]::ReadAllText($participant) -cne "$PID`n$identity`n$token`n") { throw 'Maintenance participant identity changed.' }
    }
    if (Test-Path -LiteralPath (Join-Path $directory 'recovery-guard')) {
        if ($participantOwned) { [IO.File]::Delete($participant) }
        throw 'Maintenance recovery started; no operation will run.'
    }
    return @{Path=$path;Token=$token;Owned=$owned;Previous=$previous;Participant=$participant;ParticipantOwned=$participantOwned;Participants=$participants}
}

function Exit-MeshCoreMaintenance($Lease) {
    if ($Lease.ParticipantOwned) { [IO.File]::Delete($Lease.Participant) }
    if ($Lease.Owned -and -not (Get-ChildItem -LiteralPath $Lease.Participants -Filter '*.participant') -and ([IO.File]::ReadAllLines($Lease.Path))[2] -ceq $Lease.Token) { [IO.File]::Delete($Lease.Path) }
    $env:MESHCORE_MAINTENANCE_LEASE = $Lease.Previous
}

# Inno owns a lease before it stops services or replaces package files. The
# short-lived helper transfers a newly acquired lease to that still-live process.
# The only output file accepted is inside the protected maintenance directory.
if ($AcquireForProcess) {
    $ErrorActionPreference = 'Stop'
    $owner = [Diagnostics.Process]::GetProcessById($AcquireForProcess)
    $directory = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'MeshCore-EMS-Maintenance'
    $expected = Join-Path $directory ('inno-' + $AcquireForProcess + '.token')
    if ([IO.Path]::GetFullPath($TokenOutput) -cne $expected) { throw 'Invalid native lease output path.' }
    $lease = Enter-MeshCoreMaintenance
    $parentIdentity = $owner.StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
    $parentParticipant = Join-Path $lease.Participants ($AcquireForProcess.ToString() + '-' + $parentIdentity + '.participant')
    Write-MeshCorePrivateRecord $parentParticipant "$AcquireForProcess`n$parentIdentity`n$($lease.Token)`n"
    if ($lease.Owned) {
        [IO.File]::WriteAllText($lease.Path, "$AcquireForProcess`n$parentIdentity`n$($lease.Token)`n", [Text.Encoding]::ASCII)
    }
    if ($lease.ParticipantOwned) { [IO.File]::Delete($lease.Participant) }
    if (Test-Path -LiteralPath $expected -PathType Leaf) { Assert-MeshCoreRecordOwner $expected; [IO.File]::Delete($expected) }
    Write-MeshCorePrivateRecord $expected $lease.Token
} elseif ($ReleaseForProcess) {
    $ErrorActionPreference = 'Stop'
    $directory = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'MeshCore-EMS-Maintenance'
    $path = Join-Path $directory 'lease'
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Assert-MeshCoreRecordOwner $path
        $record = [IO.File]::ReadAllLines($path)
        if ($record.Length -eq 3 -and $record[0] -ceq $ReleaseForProcess.ToString() -and $record[2] -ceq $env:MESHCORE_MAINTENANCE_LEASE) {
            $owner = [Diagnostics.Process]::GetProcessById($ReleaseForProcess)
            $identity = $owner.StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
            $participants = Join-Path $directory ('participants-' + $record[2])
            [IO.File]::Delete((Join-Path $participants ($ReleaseForProcess.ToString() + '-' + $identity + '.participant')))
            if ($identity -ceq $record[1] -and -not (Get-ChildItem -LiteralPath $participants -Filter '*.participant')) { [IO.File]::Delete($path) }
        } elseif ($record.Length -eq 3 -and $record[2] -ceq $env:MESHCORE_MAINTENANCE_LEASE) {
            # A native package delegated by a unified owner removes only its own marker.
            $identity = [Diagnostics.Process]::GetProcessById($ReleaseForProcess).StartTime.ToUniversalTime().ToFileTimeUtc().ToString()
            $participants = Join-Path $directory ('participants-' + $record[2])
            [IO.File]::Delete((Join-Path $participants ($ReleaseForProcess.ToString() + '-' + $identity + '.participant')))
        }
    }
}
