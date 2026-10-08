#!/usr/bin/env bash
# Only unmount resources recorded by this build. Never recursively remove a
# workspace: a failed unmount must leave its data and loop device intact.
yzd_cleanup() {
    local target loop backing index
    for ((index=${#YZD_MOUNTS[@]}-1; index>=0; index--)); do
        target="${YZD_MOUNTS[index]}"
        if mountpoint -q "$target"; then
            if ! umount "$target"; then
                echo "Cleanup stopped: busy mount $target; preserve $YZD_WORK" >&2
                return 1
            fi
        fi
    done
    for loop in "${YZD_LOOPS[@]}"; do
        backing="$(losetup -n -O BACK-FILE "$loop")" || return 1
        case "$backing" in "$YZD_WORK/"*) ;; *) echo "Unowned loop: $loop" >&2; return 1;; esac
        losetup -d "$loop" || return 1
    done
    for target in "${YZD_MOUNTS[@]}"; do
        rmdir "$target" 2>/dev/null || true
    done
}
