#!/usr/bin/env bash
# Shared privileged maintenance lease; this file is sourced by fixed native tools.
meshcore_lock_identity() {
    local value
    value=$(cat "/proc/$1/stat") || return 1
    value=${value##*) }
    read -ra meshcore_identity_fields <<< "$value"
    printf '%s' "${meshcore_identity_fields[19]}"
}

meshcore_lock_acquire() {
    [[ $EUID -eq 0 ]] || { echo 'Maintenance authorization is required.' >&2; return 1; }
    meshcore_lock_directory=/run/meshcore-ems-maintenance
    [[ ! -L /run && ! -L $meshcore_lock_directory ]] || { echo 'Unsafe maintenance directory.' >&2; return 1; }
    if [[ ! -e $meshcore_lock_directory ]]; then
        mkdir -m 0700 -- "$meshcore_lock_directory" || return 1
    fi
    [[ $(stat -c '%u:%a' "$meshcore_lock_directory") == 0:700 ]] || { echo 'Maintenance directory must be root-owned and private.' >&2; return 1; }
    meshcore_lock_file=$meshcore_lock_directory/lease
    [[ ! -e $meshcore_lock_directory/recovery-guard ]] || { echo 'Maintenance recovery is pending; inspect recovery first.' >&2; return 1; }
    meshcore_lock_owned=0
    meshcore_lock_previous=${MESHCORE_MAINTENANCE_LEASE-}
    local identity token
    identity=$(meshcore_lock_identity "$$") || return 1
    token=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
    if (set -o noclobber; umask 0077; printf '%s\n%s\n%s\n' "$$" "$identity" "$token" > "$meshcore_lock_file") 2>/dev/null; then
        meshcore_lock_owned=1
    else
        [[ -f $meshcore_lock_file && ! -L $meshcore_lock_file && $(stat -c '%u:%a' "$meshcore_lock_file") == 0:600 ]] || { echo 'Unsafe maintenance lease.' >&2; return 1; }
        local record
        mapfile -t record < "$meshcore_lock_file"
        [[ ${#record[@]} -eq 3 && ${record[0]} =~ ^[0-9]+$ && ${record[1]} =~ ^[0-9]+$ && ${record[2]} =~ ^[0-9a-f]{32}$ ]] || { echo 'Invalid maintenance lease.' >&2; return 1; }
        [[ ${MESHCORE_MAINTENANCE_LEASE-} == "${record[2]}" && $(meshcore_lock_identity "${record[0]}") == "${record[1]}" ]] || { echo 'Another maintenance operation or interrupted lease exists. Inspect it before recovery.' >&2; return 1; }
        token=${record[2]}
    fi
    export MESHCORE_MAINTENANCE_LEASE=$token
    meshcore_lock_participants="$meshcore_lock_directory/participants-$token"
    if [[ $meshcore_lock_owned == 1 ]]; then
        mkdir -m 0700 -- "$meshcore_lock_participants" || return 1
        printf '2\n' > "$meshcore_lock_participants/PROTOCOL"
    fi
    [[ -d $meshcore_lock_participants && ! -L $meshcore_lock_participants && $(cat "$meshcore_lock_participants/PROTOCOL") == 2 ]] || { echo 'Unknown maintenance participant protocol.' >&2; return 1; }
    meshcore_lock_participant="$meshcore_lock_participants/$$-$identity.participant"
    meshcore_participant_owned=0
    if (set -o noclobber; umask 0077; printf '%s\n%s\n%s\n' "$$" "$identity" "$token" > "$meshcore_lock_participant") 2>/dev/null; then
        meshcore_participant_owned=1
    else
        local participant
        [[ -f $meshcore_lock_participant && ! -L $meshcore_lock_participant ]] || return 1
        mapfile -t participant < "$meshcore_lock_participant"
        [[ ${#participant[@]} -eq 3 && ${participant[0]} == "$$" && ${participant[1]} == "$identity" && ${participant[2]} == "$token" ]] || return 1
    fi
    if [[ -e $meshcore_lock_directory/recovery-guard ]]; then
        [[ $meshcore_participant_owned != 1 ]] || rm -- "$meshcore_lock_participant"
        echo 'Maintenance recovery started; no operation will run.' >&2
        return 1
    fi
}

meshcore_lock_release() {
    if [[ ${meshcore_participant_owned:-0} == 1 ]]; then rm -- "$meshcore_lock_participant"; fi
    if [[ ${meshcore_lock_owned:-0} == 1 ]]; then
        local record
        mapfile -t record < "$meshcore_lock_file"
        if [[ ${record[2]-} == "${MESHCORE_MAINTENANCE_LEASE-}" ]] && ! compgen -G "$meshcore_lock_participants/*.participant" >/dev/null; then rm -- "$meshcore_lock_file"; fi
    fi
    if [[ -n ${meshcore_lock_previous-} ]]; then export MESHCORE_MAINTENANCE_LEASE=$meshcore_lock_previous; else unset MESHCORE_MAINTENANCE_LEASE; fi
}
