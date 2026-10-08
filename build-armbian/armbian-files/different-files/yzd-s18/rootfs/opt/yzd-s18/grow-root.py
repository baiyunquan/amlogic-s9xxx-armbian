#!/usr/bin/env python3
"""Expand only this image's USB root partition; never choose another disk."""
import json
import os
from pathlib import Path
import subprocess

def run(argv):
    return subprocess.check_output(argv, text=True).strip()

def validate(table, root_device):
    p = table["partitiontable"]
    rows = p["partitions"]
    if p["label"] != "dos" or len(rows) != 2:
        raise RuntimeError("expected two-partition MBR image")
    if rows[0]["start"] != 8192 or rows[0]["size"] != 1046528 or rows[0]["type"] != "c":
        raise RuntimeError("BOOT geometry changed")
    if rows[1]["node"] != root_device or rows[1]["start"] != 1056768 or rows[1]["type"] != "83":
        raise RuntimeError("ROOTFS geometry changed")
    return p["device"]

def main():
    config = json.loads(Path("/etc/yzd-s18/image.json").read_text())
    marker = Path("/var/lib/yzd-s18/root-expanded")
    if marker.exists():
        return
    if run(["findmnt", "-n", "-o", "UUID", "/"]) != config["root_uuid"]:
        raise RuntimeError("root UUID differs from image manifest")
    root_device = os.path.realpath(run(["findmnt", "-n", "-o", "SOURCE", "/"]))
    parent = run(["lsblk", "-n", "-o", "PKNAME", root_device]).splitlines()[0]
    disk = "/dev/" + parent
    if run(["lsblk", "-d", "-n", "-o", "TRAN", disk]) != "usb":
        raise RuntimeError("only a USB root disk can be expanded")
    table = json.loads(run(["sfdisk", "--json", disk]))
    if validate(table, root_device) != disk:
        raise RuntimeError("partition table device mismatch")
    result = subprocess.run(["growpart", disk, "2"], capture_output=True, text=True)
    if result.returncode and "NOCHANGE" not in result.stdout + result.stderr:
        raise RuntimeError(result.stdout + result.stderr)
    subprocess.run(["resize2fs", root_device], check=True)
    after = json.loads(run(["sfdisk", "--json", disk]))
    validate(after, root_device)
    if run(["findmnt", "-n", "-o", "UUID", "/"]) != config["root_uuid"]:
        raise RuntimeError("root UUID changed")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(config["root_uuid"] + "\n")

if __name__ == "__main__":
    main()
