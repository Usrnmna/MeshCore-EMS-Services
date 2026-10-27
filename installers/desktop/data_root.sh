#!/usr/bin/env bash
# Validate before provisioning a privileged dataset root. No ownership is changed.
meshcore_protected_data_root() {
    local requested=$1 current=/ part metadata mode
    [[ $requested == /* && $requested != *$'\n'* && $requested != *$'\r'* ]] || { echo 'Select an absolute protected dataset location in the graphical installer.' >&2; return 1; }
    requested=$(realpath -m -s -- "$requested") || return 1
    [[ $requested != / ]] || { echo 'Choose a dedicated dataset directory, not the filesystem root.' >&2; return 1; }
    IFS=/ read -ra meshcore_data_parts <<< "${requested#/}"
    for part in '' "${meshcore_data_parts[@]}"; do
        [[ -z $part ]] || current="${current%/}/$part"
        if [[ -e $current || -L $current ]]; then
            [[ -d $current && ! -L $current ]] || { echo 'Dataset storage ancestors cannot be symbolic links or non-directories.' >&2; return 1; }
            metadata=$(stat -c '%u %a' -- "$current") || return 1
            read -r meshcore_data_uid mode <<< "$metadata"
            [[ $meshcore_data_uid == 0 ]] && (( (8#$mode & 022) == 0 )) || {
                echo 'Dataset storage and its ancestors must be root-owned and not group/other writable. Choose a protected location in the graphical installer; existing custom permissions were retained.' >&2
                return 1
            }
        else
            # Every existing parent was checked first. No untrusted account can
            # replace it while the shared native maintenance lease is held.
            mkdir -m 0755 -- "$current" || return 1
        fi
    done
    MESHCORE_PROTECTED_DATA_ROOT=$requested
}
