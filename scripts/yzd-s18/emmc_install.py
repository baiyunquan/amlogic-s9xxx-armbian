#!/usr/bin/env python3
"""YZD-S18 single-data eMMC installer; preserves boot areas and raw prefix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

RELEASE = "5.15.137-yzd-s18-peripherals"
START = 262144
SECTORS = 14712832
DISK_BYTES = 15147008 * 512  # Actual device includes an untouched 84 MiB tail.
PREFIX_BYTES = START * 512
IMAGE_SHA = "9466f0d0ad2f0a3ce4c00321f7c4f0ebfe69ccd06d88f271130b45f51713dc58"

def run(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run([str(x) for x in args], check=True, **kwargs)

def output(args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()

def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def initramfs_releases(listing):
    return set(re.findall(r"^(?:usr/)?lib/modules/([^/\s]+)(?:/|$)", listing, re.M))

def validate_layout(table, target, size):
    t = table["partitiontable"]
    p = t.get("partitions", [])
    if (t.get("label") != "dos" or int(t.get("sectorsize", 512)) != 512 or
            size != DISK_BYTES or len(p) != 1):
        raise RuntimeError("unverified eMMC size or partition table")
    q = p[0]
    if (q.get("node") != target + "p1" or q.get("start") != START or
            q.get("size") != SECTORS or q.get("type") != "83"):
        raise RuntimeError("unverified eMMC data partition geometry")
    return q["node"]

def validate_source(source, parent, target):
    if not source.startswith("/dev/") or not parent.startswith("/dev/"):
        raise RuntimeError("root must be a directly attached USB/SD partition")
    if source == target or parent == target or source.startswith(target + "p"):
        raise RuntimeError("refusing to overwrite the running root disk")

def boot_script(partition):
    # Both legacy autoscript and mainline boot.scr consume this checked body.
    return f"""# YZD-S18 installed eMMC: no partition or persistent env changes.
setenv loadaddr 0x10400000
setenv initrd_high 0x7f800000
setenv fdt_high 0x20000000
setenv YZD_BOARD
setenv LINUX
setenv INITRD
setenv FDT
setenv APPEND
setenv filesize
if ext4load mmc 1:{partition} 0x10400000 /boot/uEnv.txt; then
    if env import -t 0x10400000 ${{filesize}}; then
        if test "${{YZD_BOARD}}" = "yzd-s18-emmc"; then
            setenv bootargs "${{APPEND}}"
            if ext4load mmc 1:{partition} 0x11000000 ${{LINUX}}; then
                if ext4load mmc 1:{partition} 0x15000000 ${{INITRD}}; then
                    if ext4load mmc 1:{partition} 0x08000000 ${{FDT}}; then
                        if fdt addr 0x08000000; then
                            if fdt resize 65536; then
                                booti 0x11000000 0x15000000 0x08000000
                            fi
                        fi
                    fi
                fi
            fi
        fi
    fi
fi
echo "YZD-S18 eMMC boot failed; retain USB recovery"
"""

def preflight(args):
    target = args.target
    if not re.fullmatch(r"/dev/mmcblk[0-9]+", target):
        raise RuntimeError("target must be an eMMC whole disk")
    name = Path(target).name
    sysdev = Path("/sys/block") / name / "device"
    if (sysdev / "type").read_text().strip() != "MMC":
        raise RuntimeError("target is not eMMC")
    for suffix in ("boot0", "boot1"):
        if not Path(target + suffix).is_block_device():
            raise RuntimeError("missing eMMC hardware boot area")
    cid = (sysdev / "cid").read_text().strip()
    if args.expected_cid and args.expected_cid.lower() != cid.lower():
        raise RuntimeError("target CID differs from explicitly verified device")
    source = output(["findmnt", "-n", "-o", "SOURCE", "/"]).split("[")[0]
    parent = "/dev/" + output(["lsblk", "-ndo", "PKNAME", source])
    validate_source(source, parent, target)
    identity = json.loads(Path("/etc/yzd-s18/image.json").read_text())
    if identity["board"] != "yzd-s18" or output(["findmnt", "-n", "-o", "UUID", "/"]) != identity["root_uuid"]:
        raise RuntimeError("running source is not the verified YZD USB image")
    if os.uname().release != RELEASE:
        raise RuntimeError("running kernel must be the accepted peripherals release")
    table = json.loads(output(["sfdisk", "--json", target]))
    size = int(output(["blockdev", "--getsize64", target]))
    part = validate_layout(table, target, size)
    if output(["lsblk", "-n", "-o", "MOUNTPOINTS", target]):
        raise RuntimeError("an eMMC filesystem is already mounted")
    return target, part, cid, table, identity

def check_inputs(args, cid):
    backup = args.backup_dir.resolve()
    if not backup.is_relative_to(Path("/var/backups/yzd-s18-emmc")):
        raise RuntimeError("backup must stay in the excluded USB backup directory")
    if (backup / "cid").read_text().strip() != cid:
        raise RuntimeError("backup CID mismatch")
    full = backup / "emmc-full.img"
    if full.stat().st_size != DISK_BYTES:
        raise RuntimeError("full backup incomplete")
    expected = (backup / "emmc-full.img.sha256").read_text().split()[0]
    if not re.fullmatch("[0-9a-f]{64}", expected):
        raise RuntimeError("full backup has no valid checksum receipt")
    # Full backup SHA was generated after fsync by the controlled backup step.
    # Validate the stored backup again before allowing any target write.
    if sha(full) != expected:
        raise RuntimeError("full backup checksum mismatch")
    protected = {}
    for name in ("prefix-128MiB.bin", "boot0.bin", "boot1.bin"):
        protected[name] = sha(backup / name)
    if (backup / "prefix-128MiB.bin").stat().st_size != PREFIX_BYTES:
        raise RuntimeError("prefix backup size mismatch")
    with full.open("rb") as stream:
        stream.seek((START + SECTORS) * 512)
        protected["trailing-84MiB"] = hashlib.file_digest(stream, "sha256").hexdigest()
    boot = backup / "old-boot"
    for name in ("s905_autoscript", "u-boot.bin"):
        if not (boot / name).is_file():
            raise RuntimeError("original boot chain backup missing")
    if sha(Path("/boot") / f"Image-{RELEASE}") != IMAGE_SHA:
        raise RuntimeError("running Image differs from accepted build")
    emmc = args.dtb.resolve()
    if output(["fdtget", "-t", "s", emmc, "/emmc@ffe07000", "status"]) != "okay":
        raise RuntimeError("candidate eMMC controller disabled")
    if output(["fdtget", "-t", "i", emmc, "/emmc@ffe07000", "bus-width"]) != "8":
        raise RuntimeError("candidate lacks 8-bit bus")
    run(["fdtget", emmc, "/", "yzd-s18,emmc-profile"], stdout=subprocess.DEVNULL)
    if subprocess.run(["fdtget", emmc, "/", "yzd-s18,peripherals-profile"],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError("eMMC root DTB still triggers acceptance read-only rule")
    run(["fdtget", emmc, "/emmc@ffe07000", "amlogic,skip-dtbkey-init"], stdout=subprocess.DEVNULL)
    info = output(["dpkg-deb", "-f", args.kernel_package, "Package", "Version", "Architecture"])
    if "yzd-s18-kernel" not in info or "5.15.137-peripherals-1" not in info or "arm64" not in info:
        raise RuntimeError("kernel package is not the matching ARM64 build")
    with tempfile.TemporaryDirectory(prefix="yzd-control-") as temp:
        run(["dpkg-deb", "-e", args.kernel_package, temp])
        if any((Path(temp) / script).exists() for script in ("preinst", "postinst", "prerm", "postrm", "triggers")):
            raise RuntimeError("kernel package has unexpected hooks")
    return protected

def protected_hashes(target):
    result = {}
    for name, device, count in (("prefix-128MiB.bin", target, 128),
                               ("boot0.bin", target + "boot0", 4),
                               ("boot1.bin", target + "boot1", 4)):
        proc = subprocess.Popen(["dd", "if=" + device, "bs=1M", "count=" + str(count),
                                 "status=none"], stdout=subprocess.PIPE)
        result[name] = hashlib.file_digest(proc.stdout, "sha256").hexdigest()
        if proc.wait() != 0:
            raise RuntimeError("protected region read failed")
    proc = subprocess.Popen(["dd", "if=" + target, "bs=1M", "skip=7312", "count=84",
                             "status=none"], stdout=subprocess.PIPE)
    result["trailing-84MiB"] = hashlib.file_digest(proc.stdout, "sha256").hexdigest()
    if proc.wait() != 0:
        raise RuntimeError("protected tail read failed")
    return result

def create_boot(root, args, new_uuid, mac):
    boot = root / "boot"
    boot.mkdir(exist_ok=True)
    shutil.copy2(args.dtb, boot / "dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb")
    # The exact existing chainload binary remains available for recovery.
    shutil.copy2(args.backup_dir / "old-boot/u-boot.bin", boot / "u-boot.bin")
    shutil.copy2(Path("/boot") / f"initrd.img-{RELEASE}", boot / f"initrd.img-{RELEASE}")
    shutil.copy2(Path("/boot") / f"uInitrd-{RELEASE}", boot / f"uInitrd-{RELEASE}")
    # Old U-Boot ext4 readers should load regular files, not filesystem symlinks.
    shutil.copy2(boot / f"Image-{RELEASE}", boot / "Image")
    shutil.copy2(boot / f"uInitrd-{RELEASE}", boot / "uInitrd")
    args_text = (f"root=UUID={new_uuid} rw rootwait rootfstype=ext4 "
                 "console=ttyS0,115200n8 no_console_suspend net.ifnames=0 "
                 "fbcon=map:9 yzd_s18.display=1 yzd_s18.video=1 "
                 "amvdec_ports.multiplanar=1 amvdec_ports.bypass_vpp=1 "
                 f"amvdec_ports.enable_drm_mode=0 mac={mac}")
    (boot / "uEnv.txt").write_text(
        "YZD_BOARD=yzd-s18-emmc\n"
        f"LINUX=/boot/Image-{RELEASE}\nINITRD=/boot/uInitrd-{RELEASE}\n"
        "FDT=/boot/dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb\n"
        "initrd_high=0x7f800000\nfdt_high=0x20000000\n"
        f"APPEND={args_text}\n")
    script = boot_script(1)
    (boot / "emmc-boot.cmd").write_text(script)
    (boot / "boot.ini").write_text("ZY-UBOOT-CONFIG\n" + script)
    for filename in ("s905_autoscript", "emmc_autoscript", "boot.scr"):
        run(["mkimage", "-A", "arm64", "-O", "linux", "-T", "script", "-C", "none",
             "-n", "YZD-S18 eMMC data boot", "-d", boot / "emmc-boot.cmd", boot / filename])
    # Provide mainline extlinux without changing the existing ROM/BL2/U-Boot.
    (boot / "extlinux").mkdir(exist_ok=True)
    (boot / "extlinux/extlinux.conf").write_text(
        "DEFAULT yzd-s18\nTIMEOUT 20\nLABEL yzd-s18\n"
        f"  LINUX /boot/Image-{RELEASE}\n  INITRD /boot/initrd.img-{RELEASE}\n"
        "  FDT /boot/dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb\n"
        f"  APPEND {args_text}\n")
    (boot / "armbianEnv.txt").write_text(
        f"rootdev=UUID={new_uuid}\nrootfstype=ext4\n"
        "fdtfile=amlogic/zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb\n"
        f"extraargs={args_text}\n")
    for alias, filename in (("initrd.img", f"boot/initrd.img-{RELEASE}"),
                            ("vmlinuz", f"boot/Image-{RELEASE}")):
        link = root / alias
        link.unlink(missing_ok=True)
        link.symlink_to(filename)
    metadata = root / "etc/ophub-release"
    text = metadata.read_text()
    for key, value in {"DISK_TYPE": "emmc", "FDTFILE": "zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb",
                       "KERNEL_SIGNATURE": "yzd-s18-peripherals"}.items():
        text = re.sub(r"^" + key + r"=.*$", key + "='" + value + "'", text, flags=re.M)
    metadata.write_text(text)
    return args_text

def install(args, target, part, cid, table, identity, protected):
    if not args.yes or not args.expected_cid:
        raise RuntimeError("install requires --yes and --expected-cid")
    if protected_hashes(target) != protected:
        raise RuntimeError("protected regions changed since backup")
    new_uuid = str(uuid.uuid4())
    root = Path(tempfile.mkdtemp(prefix="yzd-emmc-root-", dir="/run"))
    mounted = []
    rsync = ["rsync", "-aHAXx", "--numeric-ids", "--info=stats2"]
    excludes = ("/dev/***", "/proc/***", "/sys/***", "/run/***", "/tmp/***",
            "/mnt/***", "/media/***", "/boot/***", "/lost+found/***",
            "/var/backups/yzd-s18-emmc/***", "/var/log.hdd/***",
            "/var/tmp/yzd-s18-peripherals-stage/***", "/var/cache/apt/archives/***")
    stats = output(rsync + ["--dry-run", "--exclude=" + excludes[0]] +
                   ["--exclude=" + name for name in excludes[1:]] + ["/", str(root) + "/"])
    match = re.search(r"Total file size: ([0-9,]+) bytes", stats)
    if not match or int(match[1].replace(",", "")) + 768 * 1024**2 > SECTORS * 512 * 0.96:
        root.rmdir()
        raise RuntimeError("copied source plus kernel/initramfs reserve will not fit eMMC")
    (args.backup_dir / "source-rsync-dry-run.txt").write_text(stats + "\n")
    try:
        # These are kernel block flags, not bootloader or persistent env writes.
        run(["blockdev", "--setrw", target])
        run(["blockdev", "--setrw", part])
        run(["mkfs.ext4", "-F", "-q", "-b", "4096", "-m", "0",
             "-O", "^64bit,^metadata_csum,^metadata_csum_seed,^orphan_file",
             "-U", new_uuid, "-L", "ROOTFS_EMMC", part])
        run(["mount", "-t", "ext4", part, root])
        mounted.append(root)
        run(rsync + ["--exclude=" + name for name in excludes] + ["/", str(root) + "/"])
        for name in ("dev", "proc", "sys", "run", "tmp", "boot", "mnt", "media"):
            (root / name).mkdir(exist_ok=True)
        (root / "tmp").chmod(0o1777)
        (root / "etc/fstab").write_text(
            f"UUID={new_uuid} / ext4 defaults,noatime,errors=remount-ro 0 1\n"
            "tmpfs /tmp tmpfs defaults,nosuid,mode=1777 0 0\n")
        identity = dict(identity, kernel_release=RELEASE, root_uuid=new_uuid,
                        boot_uuid=None, input_release="yzd-s18-inputs-v2",
                        disk_type="emmc", emmc_cid=cid)
        (root / "etc/yzd-s18/image.json").write_text(json.dumps(identity, indent=2) + "\n")
        (root / "var/lib/yzd-s18/root-expanded").write_text("eMMC existing partition; resize disabled\n")
        (root / "etc/systemd/system/yzd-s18-grow-root.service").unlink(missing_ok=True)
        link = root / "etc/systemd/system/multi-user.target.wants/yzd-s18-grow-root.service"
        link.unlink(missing_ok=True)
        (root / "etc/systemd/system/yzd-s18-grow-root.service").symlink_to("/dev/null")
        # Kernel .deb has no hooks, so dpkg does not alter any default boot/env.
        run(["dpkg", "--root=" + str(root), "--install", args.kernel_package])
        run(["chroot", root, "depmod", "-a", RELEASE])
        audit = output(["chroot", root, "dpkg", "--audit"])
        if audit:
            raise RuntimeError("target package audit failed: " + audit)
        for executable in ("sbin/init", "usr/lib/systemd/systemd", "usr/sbin/fsck.ext4"):
            # Resolve absolute symlinks inside the target, not the host root.
            candidate = root / executable
            for _ in range(10):
                if not candidate.is_symlink():
                    break
                value = os.readlink(candidate)
                candidate = root / value.lstrip("/") if value.startswith("/") else candidate.parent / value
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                raise RuntimeError("target executable missing: " + executable)
        module_versions = {p.name for p in (root / "lib/modules").iterdir() if p.is_dir()}
        if module_versions != {RELEASE}:
            raise RuntimeError("target contains mismatched kernel modules: " + str(module_versions))
        mac = Path("/sys/class/net/eth0/address").read_text().strip()
        create_boot(root, args, new_uuid, mac)
        # Rebuild in this actual target root, with a private /dev exposing no disks.
        run(["mount", "-t", "tmpfs", "-o", "mode=755", "tmpfs", root / "dev"])
        mounted.append(root / "dev")
        for name, major, minor in (("null", 1, 3), ("zero", 1, 5),
                                   ("random", 1, 8), ("urandom", 1, 9), ("tty", 5, 0)):
            run(["mknod", "-m", "666", root / "dev" / name, "c", str(major), str(minor)])
        for fs in ("proc", "sys", "run"):
            if fs == "sys":
                run(["mount", "-t", "sysfs", "-o", "ro,nosuid,noexec", fs, root / fs])
            else:
                run(["mount", "-t", "proc" if fs == "proc" else "tmpfs", fs, root / fs])
            mounted.append(root / fs)
        run(["chroot", root, "mkinitramfs", "-c", "gzip", "-o",
             f"/boot/initrd.img-{RELEASE}", RELEASE])
        run(["chroot", root, "mkimage", "-A", "arm64", "-O", "linux", "-T", "ramdisk",
             "-C", "gzip", "-n", "YZD-S18 eMMC initramfs", "-d",
             f"/boot/initrd.img-{RELEASE}", f"/boot/uInitrd-{RELEASE}"])
        shutil.copy2(root / f"boot/uInitrd-{RELEASE}", root / "boot/uInitrd")
        listing = output(["lsinitramfs", root / f"boot/initrd.img-{RELEASE}"])
        for module in ("pwrseq_emmc.ko", "amlogic-mmc.ko", "amlogic-gpio.ko",
                       "amlogic-pinctrl-soc-g12a.ko", "fsck.ext4"):
            if module not in listing:
                raise RuntimeError("initramfs missing " + module)
        versions = initramfs_releases(listing)
        if versions != {RELEASE}:
            raise RuntimeError("initramfs release mismatch")
        initrd_sha = sha(root / f"boot/initrd.img-{RELEASE}")
        with (root / f"boot/uInitrd-{RELEASE}").open("rb") as f:
            f.seek(64)
            if hashlib.file_digest(f, "sha256").hexdigest() != initrd_sha:
                raise RuntimeError("uInitrd payload mismatch")
        if sha(root / f"boot/Image-{RELEASE}") != IMAGE_SHA:
            raise RuntimeError("installed Image hash mismatch")
        (args.backup_dir / "target-initramfs.list").write_text(listing + "\n")
        report = dict(status="installed-offline-verified-reboot-pending", target=target,
                      partition=part, root_uuid=new_uuid, kernel_release=RELEASE,
                      cid=cid, initramfs_sha256=initrd_sha,
                      dtb_sha256=sha(args.dtb), protected_hashes=protected,
                      uboot_environment_modified=False, reboot_performed=False)
        run(["sync"])
    except BaseException as error:
        (args.backup_dir / "install-incomplete.json").write_text(json.dumps(
            {"status": "incomplete", "error": str(error), "root_uuid": new_uuid,
             "reboot_performed": False}, indent=2) + "\n")
        raise
    finally:
        # Never remove a directory whose mount could not be unmounted.
        cleanup_errors = []
        for mount in reversed(mounted):
            try:
                run(["umount", mount])
            except subprocess.CalledProcessError as error:
                cleanup_errors.append(str(error))
        if not cleanup_errors:
            try:
                root.rmdir()
            except OSError as error:
                cleanup_errors.append(str(error))
        for device in (part, target):
            try:
                run(["blockdev", "--setro", device])
            except subprocess.CalledProcessError as error:
                cleanup_errors.append(str(error))
        try:
            if protected_hashes(target) != protected:
                cleanup_errors.append("protected prefix/tail/boot areas changed")
            if json.loads(output(["sfdisk", "--json", target])) != table:
                cleanup_errors.append("partition table changed")
        except Exception as error:
            cleanup_errors.append("protected verification failed: " + str(error))
        if cleanup_errors:
            raise RuntimeError("cleanup failed; mount directory retained: " + "; ".join(cleanup_errors))
    if json.loads(output(["sfdisk", "--json", target])) != table:
        raise RuntimeError("partition table changed unexpectedly")
    if protected_hashes(target) != protected:
        raise RuntimeError("protected prefix/boot areas differ after installation")
    run(["e2fsck", "-f", "-n", part], stdout=(args.backup_dir / "target-fsck.txt").open("w"),
        stderr=subprocess.STDOUT)
    features = output(["tune2fs", "-l", part])
    feature_line = next(line for line in features.splitlines() if line.startswith("Filesystem features:"))
    if any(name in feature_line.split() for name in ("64bit", "metadata_csum", "metadata_csum_seed", "orphan_file")):
        raise RuntimeError("old U-Boot incompatible filesystem feature")
    report["filesystem_features"] = feature_line
    (args.backup_dir / "install-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    print("Installation verified offline. No reboot issued. Remove USB only after shutdown.", flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "check", "install"))
    parser.add_argument("--target", default="/dev/mmcblk0")
    parser.add_argument("--expected-cid")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--kernel-package", type=Path)
    parser.add_argument("--dtb", type=Path)
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    os.environ["LC_ALL"] = "C"
    if os.geteuid() != 0:
        parser.error("run as root")
    target, part, cid, table, identity = preflight(args)
    print(json.dumps(dict(target=target, partition=part, cid=cid, layout="single-data-128MiB"), indent=2), flush=True)
    if args.action == "status":
        return
    if not all((args.backup_dir, args.kernel_package, args.dtb)):
        parser.error("check/install need --backup-dir, --kernel-package and --dtb")
    args.backup_dir = args.backup_dir.resolve()
    protected = check_inputs(args, cid)
    if args.action == "check":
        if protected_hashes(target) != protected:
            raise RuntimeError("protected region mismatch")
        print("Preflight passed; no target writes.", flush=True)
    else:
        try:
            install(args, target, part, cid, table, identity, protected)
        except BaseException as error:
            (args.backup_dir / "install-incomplete.json").write_text(json.dumps(
                {"status": "incomplete", "error": str(error),
                 "reboot_performed": False}, indent=2) + "\n")
            raise

if __name__ == "__main__":
    main()

