#!/usr/bin/env bash
# Construct only regular image files. No physical target device is accepted.
set -Eeuo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INPUTS=""
OUTPUT="$REPO/build/output/yzd-s18"
BUNDLE=""
while (( $# )); do
    case "$1" in
        -b) [[ "$2" == yzd-s18 ]]; shift 2;;
        --yzd-inputs-dir) INPUTS="$(realpath "$2")"; shift 2;;
        --custom-kernel-bundle) BUNDLE="$(realpath "$2")"; shift 2;;
        --output) OUTPUT="$(realpath -m "$2")"; shift 2;;
        *) echo "Unsupported YZD option: $1" >&2; exit 2;;
    esac
done
[[ "$(id -u)" == 0 && -d "$INPUTS" && -f "$BUNDLE" ]]
python3 "$REPO/scripts/yzd-s18/inputs.py" verify "$INPUTS" "$REPO/scripts/yzd-s18/inputs.lock.json"
EXPECTED="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["kernel_bundle"])' "$REPO/scripts/yzd-s18/inputs.lock.json")"
[[ "$BUNDLE" == "$INPUTS/$EXPECTED" ]]
for cmd in losetup mount umount rsync sfdisk mkfs.vfat mkfs.ext4 fdtget mkimage python3; do command -v "$cmd" >/dev/null; done
mkdir -p "$OUTPUT"
YZD_WORK="$(mktemp -d "$OUTPUT/.work.XXXXXXXX")"
chmod 700 "$YZD_WORK"
YZD_MOUNTS=()
YZD_LOOPS=()
source "$REPO/scripts/yzd-s18/safety.sh"
finish() {
    local status=$?
    trap - EXIT
    if ! yzd_cleanup; then exit 1; fi
    echo "Build workspace preserved for inspection: $YZD_WORK"
    exit "$status"
}
trap finish EXIT
mkdir -p "$YZD_WORK/base" "$YZD_WORK/root" "$YZD_WORK/inputs"
python3 "$REPO/scripts/yzd-s18/inputs.py" extract "$BUNDLE" "$YZD_WORK/inputs/kernel"
python3 "$REPO/scripts/yzd-s18/inputs.py" extract "$INPUTS/yzd-s18-vendor-runtime.tar.gz" "$YZD_WORK/inputs/vendor"
python3 "$REPO/scripts/yzd-s18/verify.py" kernel "$YZD_WORK/inputs/kernel"
BASE="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["base_image"])' "$REPO/scripts/yzd-s18/inputs.lock.json")"
gzip -dc "$INPUTS/$BASE" > "$YZD_WORK/base.img"
base_loop="$(losetup --read-only --partscan --find --show "$YZD_WORK/base.img")"
YZD_LOOPS+=("$base_loop")
mount -o ro,noload "${base_loop}p2" "$YZD_WORK/base"
YZD_MOUNTS+=("$YZD_WORK/base")
[[ "$(sed -n 's/^VERSION_CODENAME=//p' "$YZD_WORK/base/etc/os-release")" == bookworm ]]
release=5.15.137-yzd-s18-usbfix
name="Armbian_26.11.0_amlogic_yzd-s18_bookworm_${release}_server_$(date -u +%Y.%m.%d)"
image="$YZD_WORK/$name.img"
truncate -s 6660M "$image"
sfdisk "$image" <<'PARTITIONS'
label: dos
unit: sectors

start=8192, size=1046528, type=c
start=1056768, size=12582912, type=83
PARTITIONS
image_loop="$(losetup --partscan --find --show "$image")"
YZD_LOOPS+=("$image_loop")
root_uuid="$(cat /proc/sys/kernel/random/uuid)"
mkfs.vfat -F32 -n BOOT "${image_loop}p1"
mkfs.ext4 -F -q -b 4096 -m 0 -O ^orphan_file -U "$root_uuid" -L ROOTFS "${image_loop}p2"
boot_uuid="$(blkid -s UUID -o value "${image_loop}p1")"
mount "${image_loop}p2" "$YZD_WORK/root"
YZD_MOUNTS+=("$YZD_WORK/root")
root="$YZD_WORK/root"
rsync -aHAX --numeric-ids --exclude='/boot/***' --exclude='/usr/lib/modules/***' --exclude='/lib/modules/***' --exclude='/usr/src/linux-headers-*' "$YZD_WORK/base/" "$root/"
# The source stays read-only; all changes below refer to the new loop image.
cp -a --no-preserve=ownership "$REPO/build-armbian/armbian-files/common-files/." "$root/"
cp -a --no-preserve=ownership "$REPO/build-armbian/armbian-files/platform-files/amlogic/rootfs/." "$root/"
cp -a --no-preserve=ownership "$REPO/build-armbian/armbian-files/different-files/yzd-s18/rootfs/." "$root/"
mkdir -p "$root/boot" "$root/dev" "$root/proc" "$root/sys" "$root/run" "$root/opt/yzd-build-inputs" "$root/etc/yzd-s18"
mount "${image_loop}p1" "$root/boot"
YZD_MOUNTS+=("$root/boot")
python3 - "$root" "$root_uuid" "$boot_uuid" <<'PY'
import json, pathlib, sys
r=pathlib.Path(sys.argv[1])
identity={"schema_version":1,"board":"yzd-s18","kernel_release":"5.15.137-yzd-s18-usbfix",
          "root_uuid":sys.argv[2],"boot_uuid":sys.argv[3],"input_release":"yzd-s18-inputs-v1"}
(r/"etc/yzd-s18/image.json").write_text(json.dumps(identity,indent=2)+"\n")
(r/"etc/fstab").write_text(f"UUID={sys.argv[2]} / ext4 defaults,noatime,errors=remount-ro 0 1\nUUID={sys.argv[3]} /boot vfat defaults 0 2\ntmpfs /tmp tmpfs defaults,nosuid,mode=1777 0 0\n")
PY
mount --bind "$YZD_WORK/inputs" "$root/opt/yzd-build-inputs"
YZD_MOUNTS+=("$root/opt/yzd-build-inputs")
mount -o remount,bind,ro "$root/opt/yzd-build-inputs"
# A private minimal /dev prevents package scripts seeing host disks.
mount -t tmpfs -o mode=755 tmpfs "$root/dev"
YZD_MOUNTS+=("$root/dev")
for spec in 'null 1 3' 'zero 1 5' 'random 1 8' 'urandom 1 9' 'tty 5 0'; do
    read -r node major minor <<< "$spec"
    mknod -m 666 "$root/dev/$node" c "$major" "$minor"
done
mkdir -p "$root/dev/pts"
mount -t devpts -o mode=620 devpts "$root/dev/pts"
YZD_MOUNTS+=("$root/dev/pts")
ln -s pts/ptmx "$root/dev/ptmx"
ln -s /proc/self/fd "$root/dev/fd"
mount -t proc proc "$root/proc"; YZD_MOUNTS+=("$root/proc")
mount -t sysfs -o ro,nosuid,noexec sysfs "$root/sys"; YZD_MOUNTS+=("$root/sys")
mount -t tmpfs tmpfs "$root/run"; YZD_MOUNTS+=("$root/run")
# resolv.conf may be an absolute symlink: replace the image entry, never follow it.
rm -f "$root/etc/resolv.conf"
cp /etc/resolv.conf "$root/etc/resolv.conf"
install -m 0755 "$REPO/scripts/yzd-s18/setup-rootfs.sh" "$root/tmp/yzd-setup-rootfs.sh"
install -m 0644 "$REPO/scripts/yzd-s18/early-modules.txt" "$root/etc/initramfs-tools/modules"
chroot "$root" /bin/bash /tmp/yzd-setup-rootfs.sh 2>&1 | tee "$OUTPUT/setup-rootfs.log"
ln -sfn /run/NetworkManager/resolv.conf "$root/etc/resolv.conf"
python3 "$REPO/scripts/yzd-s18/write-boot.py" "$root/boot" "$root/etc/yzd-s18/image.json"
for script in s905_autoscript boot.scr aml_autoscript; do
    mkimage -A arm64 -O linux -T script -C none -n 'YZD-S18 USB boot' -d "$REPO/scripts/yzd-s18/boot.cmd" "$root/boot/$script"
done
cp "$REPO/scripts/yzd-s18/boot.cmd" "$root/boot/yzd-s18-boot.cmd"
chroot "$root" /bin/bash -ec '/sbin/init --version; /sbin/fsck.ext4 -V; dpkg --audit; /opt/yzd-s18/video/ffmpeg-5.1.9/bin/ffmpeg -version; python3 /opt/yzd-s18/graphics_runtime.py status' > "$OUTPUT/chroot-checks.txt" 2>&1
python3 "$REPO/scripts/yzd-s18/verify.py" root "$root" --report "$OUTPUT/validation.json"
cp "$root/etc/yzd-s18/image.json" "$OUTPUT/image.json"
cp "$root/opt/yzd-build-inputs/kernel/build-manifest.txt" "$OUTPUT/kernel-build-manifest.txt"
# Unmount binds and filesystems before filesystem checks or compression.
yzd_cleanup
YZD_MOUNTS=(); YZD_LOOPS=()
check_loop="$(losetup --partscan --find --show "$image")"; YZD_LOOPS=("$check_loop")
fsck.vfat -n "${check_loop}p1" > "$OUTPUT/fsck-boot.txt"
e2fsck -fn "${check_loop}p2" > "$OUTPUT/fsck-root.txt" 2>&1
tune2fs -l "${check_loop}p2" > "$OUTPUT/ext4-features.txt"
if grep '^Filesystem features:' "$OUTPUT/ext4-features.txt" | grep -qw orphan_file; then
    echo 'Unsupported ext4 orphan_file feature' >&2; exit 1
fi
sfdisk --json "$image" > "$OUTPUT/partitions.json"
python3 "$REPO/scripts/yzd-s18/verify.py" partitions "$OUTPUT/partitions.json"
yzd_cleanup; YZD_LOOPS=()
gzip -c -6 "$image" > "$OUTPUT/$name.img.gz"
cp "$REPO/scripts/yzd-s18/inputs.lock.json" "$OUTPUT/inputs.lock.json"
(cd "$OUTPUT"; sha256sum "$name.img.gz" > "$name.img.gz.sha256")
# Explicit files only: all mountpoints were removed with rmdir, no recursive rm.
rm -f "$YZD_WORK/base.img" "$image"
echo "IMAGE_BUILD_VERIFIED=$OUTPUT/$name.img.gz"
