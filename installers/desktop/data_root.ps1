# Pin and validate data storage before bootstrap writes, without a compiler or CLI fallback.
function Initialize-MeshCoreDataRootNative {
    if ('MeshCoreDataRootNative' -as [type]) { return }
    $assemblyName = New-Object Reflection.AssemblyName('MeshCoreDataRootNative')
    $assembly = [AppDomain]::CurrentDomain.DefineDynamicAssembly($assemblyName, [Reflection.Emit.AssemblyBuilderAccess]::Run)
    $module = $assembly.DefineDynamicModule('MeshCoreDataRootNative')
    $builder = $module.DefineType('MeshCoreDataRootNative', [Reflection.TypeAttributes]::Public)
    $attributes = [Reflection.MethodAttributes]::Public -bor [Reflection.MethodAttributes]::Static -bor [Reflection.MethodAttributes]::PinvokeImpl
    $methods = @(
        @('CreateFileW', [IntPtr], [Type[]]@([string],[uint32],[uint32],[IntPtr],[uint32],[uint32],[IntPtr])),
        @('GetFileInformationByHandleEx', [bool], [Type[]]@([IntPtr],[int],[IntPtr],[uint32])),
        @('CloseHandle', [bool], [Type[]]@([IntPtr]))
    )
    foreach ($spec in $methods) {
        $method = $builder.DefinePInvokeMethod($spec[0], 'kernel32.dll', $attributes, [Reflection.CallingConventions]::Standard, $spec[1], $spec[2], [Runtime.InteropServices.CallingConvention]::Winapi, [Runtime.InteropServices.CharSet]::Unicode)
        $method.SetImplementationFlags([Reflection.MethodImplAttributes]::PreserveSig)
    }
    $builder.CreateType() | Out-Null
}

function Enter-MeshCoreDataRoot([string]$Path) {
    Initialize-MeshCoreDataRootNative
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path -notmatch '^[A-Za-z]:[\\/]') { throw 'Choose an absolute local protected dataset location.' }
    $Path = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $anchor = [IO.Path]::GetPathRoot($Path)
    if ($Path.TrimEnd('\') -ieq $anchor.TrimEnd('\')) { throw 'Choose a dedicated dataset directory, not the volume root.' }
    $nodes = New-Object 'Collections.Generic.List[string]'
    $nodes.Add($anchor)
    $current = $anchor
    foreach ($part in $Path.Substring($anchor.Length).Split('\')) {
        if (-not $part -or $part.Contains(':') -or $part.EndsWith('.') -or $part.EndsWith(' ')) { throw 'Dataset paths cannot contain aliases or alternate streams.' }
        $current = Join-Path $current $part
        $nodes.Add($current)
    }
    $handles = New-Object 'Collections.Generic.List[IntPtr]'
    $trusted = @('S-1-5-18','S-1-5-32-544','S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464')
    try {
        foreach ($node in $nodes) {
            if (-not (Test-Path -LiteralPath $node)) {
                # Parent handles remain pinned; only this new child receives an ACL.
                $security = New-Object Security.AccessControl.DirectorySecurity
                $security.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;AU)(A;OICI;GRGX;;;LS)')
                [IO.Directory]::CreateDirectory($node, $security) | Out-Null
            }
            $handle = [MeshCoreDataRootNative]::CreateFileW($node, 0x20081, 3, [IntPtr]::Zero, 3, 0x02200000, [IntPtr]::Zero)
            if ($handle -eq [IntPtr](-1)) { throw 'Cannot pin dataset storage before privileged writes.' }
            $handles.Add($handle)
            $information = [Runtime.InteropServices.Marshal]::AllocHGlobal(8)
            try {
                if (-not [MeshCoreDataRootNative]::GetFileInformationByHandleEx($handle, 9, $information, 8)) { throw 'Cannot inspect dataset storage.' }
                $flags = [Runtime.InteropServices.Marshal]::ReadInt32($information)
                if (($flags -band 0x400) -or -not ($flags -band 0x10)) { throw 'Dataset storage ancestors cannot be reparse points or files.' }
            } finally { [Runtime.InteropServices.Marshal]::FreeHGlobal($information) }
            $acl = [IO.Directory]::GetAccessControl($node)
            if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted) { throw 'Dataset storage has an untrusted owner. Select a protected location in the graphical installer; existing custom permissions were retained.' }
            $mask = if ($node.TrimEnd('\') -ieq $Path) { [long]0x500D0156 } else { [long]0x500D0150 }
            foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
                if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly)) { continue }
                if ($rule.IdentityReference.Value -notin $trusted -and ([long][int]$rule.FileSystemRights -band $mask)) { throw 'Dataset storage permits untrusted modification. Select a protected location in the graphical installer; existing custom permissions were retained.' }
            }
        }
        return @{Handles=$handles;Root=$Path}
    } catch {
        foreach ($handle in $handles) { [MeshCoreDataRootNative]::CloseHandle($handle) | Out-Null }
        throw
    }
}

function Exit-MeshCoreDataRoot($Lease) {
    for ($index = $Lease.Handles.Count - 1; $index -ge 0; $index--) { [MeshCoreDataRootNative]::CloseHandle($Lease.Handles[$index]) | Out-Null }
}
