#!/usr/bin/env python3
"""Validate immutable build inputs and extract data-only archives."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

RELEASE = "5.15.137-yzd-s18-usbfix"
BASE = "Armbian_26.11.0_amlogic_s905x3_bookworm_6.12.109_server_2026.09.14.img.gz"
KERNEL = "yzd-s18-kernel-" + RELEASE + ".tar.gz"

def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def verify(directory, lock):
    directory = Path(directory)
    data = json.loads(Path(lock).read_text())
    for name, expected in data["assets"].items():
        if Path(name).name != name:
            raise ValueError("invalid asset name: " + name)
        if sha(directory / name) != expected:
            raise ValueError("input checksum mismatch: " + name)
    return data

def extract(archive, destination):
    destination = Path(destination)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe archive member: " + member.name)
        destination.mkdir(parents=True, exist_ok=True)
        tar.extractall(destination, members=members, filter="data")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("verify", "extract"))
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    if args.mode == "verify":
        verify(args.source, args.target)
    else:
        extract(args.source, args.target)

if __name__ == "__main__":
    main()
