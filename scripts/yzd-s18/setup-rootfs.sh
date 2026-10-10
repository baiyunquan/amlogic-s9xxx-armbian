#!/usr/bin/env bash
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
export LC_ALL=C.UTF-8
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
release=5.15.137-yzd-s18-peripherals
kernel=/opt/yzd-build-inputs/kernel
vendor=/opt/yzd-build-inputs/vendor
install -d /var/tmp/yzd-build /var/lib/yzd-s18 /root /var/tmp /etc/initramfs-tools/conf.d
chmod 1777 /var/tmp
cat > /usr/sbin/policy-rc.d <<'POLICY'
#!/bin/sh
exit 101
POLICY
chmod 755 /usr/sbin/policy-rc.d
# Purge the old kernel through dpkg, rather than deleting its package records.
mapfile -t old < <(dpkg-query -W -f='${binary:Package} ${db:Status-Status}\n' 2>/dev/null | awk '$2=="installed" && $1 ~ /^linux-(image|headers|dtb)/ {print $1}')
if (( ${#old[@]} )); then
    apt-get -s purge "${old[@]}" > /var/lib/yzd-s18/kernel-purge-simulation.txt
    apt-mark unhold "${old[@]}"
    apt-get -y purge "${old[@]}"
fi
packages=(initramfs-tools e2fsprogs u-boot-tools kmod hdparm python3 openssh-server network-manager
    rsync cloud-guest-utils parted util-linux kbd ffmpeg libsdl2-2.0-0 v4l-utils
    device-tree-compiler
    mesa-utils mesa-utils-bin glmark2-es2-drm libdrm-tests libvulkan1 vulkan-tools
    clinfo ocl-icd-libopencl1 ocl-icd-opencl-dev opencl-headers
    build-essential flex bison libssl-dev libelf-dev pkg-config libegl-dev libgles-dev libgbm-dev libvulkan-dev
    libwayland-client0 libwayland-server0 libwayland-egl1 libdrm2)
apt-get update
apt-get -s --no-install-recommends install "${packages[@]}" > /var/lib/yzd-s18/packages-simulation.txt
apt-get -y --no-install-recommends install "${packages[@]}"
stage=/var/tmp/yzd-build/kernel-package
mkdir -p "$stage/DEBIAN" "$stage/boot/dtb/amlogic" "$stage/usr/lib/modules" "$stage/usr/src" "$stage/usr/share/doc/yzd-s18-kernel"
cp -a "$kernel/modules" "$stage/usr/lib/modules/$release"
dpkg-deb -x "$kernel/headers.deb" /var/tmp/yzd-build/header-extract
cp -a /var/tmp/yzd-build/header-extract/usr/src/. "$stage/usr/src/"
headers="$stage/usr/src/linux-headers-$release"
# The cross-built header package intentionally omitted host executables. Generate
# them with the native Bookworm compiler before packing the installed headers.
cat > /var/tmp/yzd-build/header-helpers.mk <<'HELPERS'
.PHONY: yzd_headers_prepare
yzd_headers_prepare: scripts_basic
	$(MAKE) $(build)=scripts
	$(MAKE) $(build)=scripts/mod
HELPERS
# External-module mode preserves the exact generated kernel configuration; the
# headers omit vendor Kconfig sources and must never run syncconfig here.
make -C "$headers" -f Makefile -f /var/tmp/yzd-build/header-helpers.mk ARCH=arm64 CROSS_COMPILE= M=/var/tmp/yzd-build/header-smoke yzd_headers_prepare
test -x "$headers/scripts/basic/fixdep"
test -x "$headers/scripts/mod/modpost"
mkdir -p /var/tmp/yzd-build/header-smoke
printf 'obj-m += yzd_header_smoke.o\n' > /var/tmp/yzd-build/header-smoke/Makefile
cat > /var/tmp/yzd-build/header-smoke/yzd_header_smoke.c <<'MODULE'
#include <linux/module.h>
static int __init yzd_init(void) { return 0; }
static void __exit yzd_exit(void) { }
module_init(yzd_init);
module_exit(yzd_exit);
MODULE_LICENSE("GPL");
MODULE
make -C "$headers" ARCH=arm64 CROSS_COMPILE= M=/var/tmp/yzd-build/header-smoke modules
modinfo -F vermagic /var/tmp/yzd-build/header-smoke/yzd_header_smoke.ko | grep -q "^$release "
cp /var/tmp/yzd-build/header-smoke/yzd_header_smoke.ko "$stage/usr/share/doc/yzd-s18-kernel/"
ln -s "/usr/src/linux-headers-$release" "$stage/usr/lib/modules/$release/build"
cp "$kernel/boot/Image-$release" "$stage/boot/"
cp "$kernel/boot/dtb/amlogic/"*.dtb "$stage/boot/dtb/amlogic/"
cp "$kernel/config-$release" "$stage/boot/"
cp "$kernel/System.map" "$stage/boot/System.map-$release"
cp "$kernel/build-manifest.txt" "$stage/usr/share/doc/yzd-s18-kernel/"
cat > "$stage/DEBIAN/control" <<'CONTROL'
Package: yzd-s18-kernel
Version: 5.15.137-peripherals-1
Architecture: arm64
Section: kernel
Priority: optional
Maintainer: baiyunquan <liaic@outlook.com>
Description: YZD-S18 Khadas kernel, DTBs, headers and vendor modules
 Fixed release 5.15.137-yzd-s18-peripherals. Rebuild image to update.
CONTROL
dpkg-deb --build --root-owner-group "$stage" /var/tmp/yzd-build/yzd-s18-kernel.deb
dpkg -i /var/tmp/yzd-build/yzd-s18-kernel.deb
apt-mark hold yzd-s18-kernel
depmod -a "$release"
# Ship the source-compiled profile, with bus/pinctrl/supplies/reset and raw IR.
# The previous status-only DTB did not contain the required eMMC properties.
emmc_dtb=/boot/dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb
cp -f /boot/dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-peripherals-peripherals.dtb "$emmc_dtb"
[[ "$(fdtget -t s "$emmc_dtb" /emmc@ffe07000 status)" == okay ]]
# Install only the pinned Mali library; do not run the vendor .deb replacement hooks.
dpkg-deb -x "$vendor/mali.deb" /var/tmp/yzd-build/mali-extract
install -d /opt/yzd-s18/mali-r44p0/lib /opt/yzd-s18/mali-r44p0/vendors /lib/firmware/video
install -m 0644 /var/tmp/yzd-build/mali-extract/usr/lib/aarch64-linux-gnu/libMali.so /opt/yzd-s18/mali-r44p0/lib/libMali.so
printf '/opt/yzd-s18/mali-r44p0/lib/libMali.so\n' > /opt/yzd-s18/mali-r44p0/vendors/mali.icd
echo 'c2524056ef47ed5b503615a2aa7bf133bffadcd0fd3dba236ee9778f725bf64d  /opt/yzd-s18/mali-r44p0/lib/libMali.so' | sha256sum -c -
install -m 0644 "$vendor/video_ucode.bin" /lib/firmware/video/video_ucode.bin
echo '80522fd7376bde74be185e822c314f9beddee0264279bb4538d104588f46b094  /lib/firmware/video/video_ucode.bin' | sha256sum -c -
python3 /opt/yzd-s18/graphics_runtime.py install
mkdir -p /opt/yzd-s18/video/ffmpeg-5.1.9
tar -xzf "$vendor/video-media-runtime.tar.gz" -C /opt/yzd-s18/video/ffmpeg-5.1.9
cp -a "$vendor/samples" "$vendor/reference" /opt/yzd-s18/video/
cp -a "$vendor/ffmpeg-source" /usr/share/doc/yzd-s18-video-source
gcc -std=c11 -O2 -Wall -Wextra -Werror /opt/yzd-s18/opencl_smoke.c -lOpenCL -o /opt/yzd-s18/opencl_smoke
gcc -std=c11 -O2 -Wall -Wextra -Werror /opt/yzd-s18/graphics_smoke.c -lEGL -lGLESv2 -lgbm -lvulkan -o /opt/yzd-s18/graphics_smoke
gcc -std=c11 -O2 -Wall -Wextra -Werror /opt/yzd-s18/eglinfo_gbm.c -lEGL -lgbm -o /opt/yzd-s18/eglinfo-gbm
chmod 755 /opt/yzd-s18/*.sh /opt/yzd-s18/graphics_runtime.py /opt/yzd-s18/video/yzd_s18_video.py /usr/local/bin/eglinfo
chmod 755 /usr/local/sbin/yzd-s18-disk-power
ln -s /opt/yzd-s18/video/yzd_s18_video.py /usr/local/bin/yzd-s18-video
ln -s /opt/yzd-s18/graphics_runtime.py /usr/local/bin/yzd-s18-graphics
# Prevent vendor-incompatible update entrypoints, including future dpkg upgrades.
mkdir -p /usr/lib/yzd-s18/disabled-tools
for tool in armbian-update armbian-kernel armbian-tf; do
    dpkg-divert --local --rename --add --divert "/usr/lib/yzd-s18/disabled-tools/$tool" "/usr/sbin/$tool"
    cat > "/usr/sbin/$tool" <<'BLOCKED'
#!/bin/sh
echo 'YZD-S18 USB vendor image: use the pinned build-yzd-s18 workflow to update. Generic kernel/eMMC installation is unsupported.' >&2
exit 1
BLOCKED
    chmod 755 "/usr/sbin/$tool"
done
# Install the YZD-specific eMMC installer. It never repartitions the factory
# disk or writes boot0/boot1; the generic installer is retained as a backup.
dpkg-divert --local --rename --add --divert /usr/lib/yzd-s18/disabled-tools/armbian-install /usr/sbin/armbian-install
install -m 0755 /tmp/yzd-armbian-install /usr/sbin/armbian-install
# The generic first-run fixer purges package records and performs an unchecked
# resize. This image was finalized and checked during CI; use its own services.
dpkg-divert --local --rename --add --divert /usr/lib/yzd-s18/disabled-tools/armbian-fix /usr/sbin/armbian-fix
printf '#!/bin/sh\necho "YZD-S18 image was finalized during build; first-boot services handle identity and USB growth."\n' > /usr/sbin/armbian-fix
chmod 755 /usr/sbin/armbian-fix
cat > /etc/initramfs-tools/conf.d/yzd-s18 <<'INITRAMFS'
MODULES=most
COMPRESS=gzip
FSTYPE=ext4
INITRAMFS
# Disable automatic generic hooks: this dedicated build invokes mkinitramfs explicitly.
printf 'update_initramfs=no\n' > /etc/initramfs-tools/update-initramfs.conf
mkinitramfs -c gzip -o "/boot/initrd.img-$release" "$release"
mkimage -A arm64 -O linux -T ramdisk -C gzip -n "uInitrd-$release" -d "/boot/initrd.img-$release" "/boot/uInitrd-$release"
lsinitramfs "/boot/initrd.img-$release" > /var/lib/yzd-s18/initramfs.list
while read -r name; do
    [[ "$name" == usb-storage ]] && { grep -q '^CONFIG_USB_STORAGE=y' "/boot/config-$release"; continue; }
    grep -Fq "/$name.ko" /var/lib/yzd-s18/initramfs.list
done < /etc/initramfs-tools/modules
grep -q 'fsck.ext4' /var/lib/yzd-s18/initramfs.list
# Preserve the base's first-login policy, but regenerate host identity on first boot.
rm -f /etc/ssh/ssh_host_* /var/lib/dbus/machine-id
: > /etc/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id
rm -f /initrd.img /initrd.img.old /vmlinuz /vmlinuz.old
ln -s "/boot/initrd.img-$release" /initrd.img
ln -s "/boot/Image-$release" /vmlinuz
ln -sfn usr/bin /bin
ln -sfn usr/lib /lib
ln -sfn usr/sbin /sbin
printf 'no\n' > /root/.no_rootfs_resize
# ttyAML0 belongs to the mainline baseline, not this vendor UART.
rm -f /etc/systemd/system/getty.target.wants/serial-getty@ttyAML0.service
systemctl --root=/ enable ssh NetworkManager yzd-s18-display yzd-s18-video yzd-s18-grow-root yzd-s18-identity yzd-s18-disk-power yzd-s18-disk-park
systemctl --root=/ mask armbian-resize-filesystem.service
systemd-analyze verify /etc/systemd/system/yzd-s18-{display,video,grow-root,disk-power,disk-park}.service
printf 'yzd-s18\n' > /etc/hostname
install -d /etc/profile.d
printf 'export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n' > /etc/profile.d/yzd-s18-path.sh
sed -i 's/\barmbian\b/yzd-s18/g' /etc/hosts
ln -sfn /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
printf 'Asia/Shanghai\n' > /etc/timezone
if [[ -f /etc/udev/rules.d/hdmi.rules ]]; then mv /etc/udev/rules.d/hdmi.rules /etc/udev/rules.d/hdmi.rules.disabled; fi
sed -i -e 's/^BOARD=.*/BOARD=yzd-s18/' -e 's/^BOARD_NAME=.*/BOARD_NAME="YZD-S18"/' /etc/armbian-release
cat > /etc/ophub-release <<'OPHUB'
PLATFORM='amlogic'
VERSION_CODEID='debian'
VERSION_CODENAME='bookworm'
MODEL_ID='528'
MODEL_NAME='YZD-S18'
SOC='s905x3'
FDTFILE='zh_s905x3_4g_rgmii-yzd-s18-peripherals-peripherals.dtb'
FAMILY='meson-sm1'
BOARD='yzd-s18'
KERNEL_REPO='baiyunquan/amlogic-s9xxx-armbian'
KERNEL_TAGS='yzd-s18'
KERNEL_VERSION='5.15.137'
KERNEL_SIGNATURE='yzd-s18-peripherals'
BOOT_CONF='uEnv.txt'
ROOTFS_TYPE='ext4'
DISK_TYPE='usb'
OPHUB
dpkg --audit > /var/lib/yzd-s18/dpkg-audit.txt
test ! -s /var/lib/yzd-s18/dpkg-audit.txt
dpkg-query -W -f='${binary:Package}\t${Version}\n' > /var/lib/yzd-s18/packages.tsv
# Regular build inputs live on a separate read-only bind and are never deleted here.
apt-get clean
rm -f /usr/sbin/policy-rc.d /tmp/yzd-setup-rootfs.sh
