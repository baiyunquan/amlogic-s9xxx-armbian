# YZD-S18 Bookworm USB vendor image

Build entry: **Build YZD-S18 Bookworm vendor image** in Actions, or:

```sh
gh release download yzd-s18-inputs-v1 -R baiyunquan/amlogic-s9xxx-armbian -D build/yzd-s18-inputs
sudo ./rebuild -b yzd-s18 \
  --custom-kernel-bundle build/yzd-s18-inputs/yzd-s18-kernel-5.15.137-yzd-s18-usbfix.tar.gz \
  --yzd-inputs-dir build/yzd-s18-inputs --output build/output/yzd-s18
```

Use an ARM64 Linux build host. An x86 host additionally needs registered ARM64
QEMU binfmt support. All input hashes are locked in scripts/yzd-s18/inputs.lock.json.
The workflow uses this checkout's code, not the upstream ophub action.
The board is excluded from generic all-board builds because its vendor ABI
requires the explicit locked bundle.

## Layout and boot

MBR, 4 MiB reserved before BOOT. FAT32 starts at sector 8192, length 1046528
sectors (the existing nominal 512 MiB layout, including its gap). ext4 ROOTFS
starts at sector 1056768, initial size 6144 MiB. Each image has fresh UUIDs;
fstab, uEnv and /etc/yzd-s18/image.json agree. Only the image's USB root
partition is expanded by the first-boot service. BOOT is never expanded.

BOOT contains one kernel, 5.15.137-yzd-s18-usbfix, a newly generated matching
initramfs, and compute/display/video DTBs. The default is video with 564 MiB CMA.
No eMMC installer, U-Boot overload or saveenv command is provided.
The scripts scan USB devices 0 through 7, verifying the YZD_BOARD marker and
every load before booti. This accommodates changing JMicron/eVtran numbers.

At an existing U-Boot prompt, identify eVtran using the **current** USB listing
and the successful partition/FAT read, rather than assuming a fixed number:

```text
usb start
usb storage
fatls usb <eVtran-number>:1 /
fatload usb <eVtran-number>:1 0x10400000 s905_autoscript
autoscr 0x10400000
```

Do not execute autoscr after a failed fatload. The script uses kernel 0x11000000,
initrd 0x15000000 and FDT 0x08000000, with initrd_high=0x7f800000 and
fdt_high=0x20000000. Default native UAS uses the park-mode, frame adjustment,
SG/TRB and ERST fixes; it is not a claim of completed disk stress acceptance.
uEnv.bot.txt disables only JMicron UAS and retains BOT disk access.
uEnv.debug.txt adds UART kernel diagnostics. To use an alternate, import it
manually and load its named Image/initramfs/DTB, or replace uEnv.txt deliberately.

## Runtime and checks

Bookworm server, DHCP Ethernet and ttyS0. The clean base image's root/1234
first-login policy is retained; SSH host keys and machine ID are regenerated.
There are no copied SSH keys or personal files from the old USB rootfs.

Mali EGL/GLES/GBM aliases and Vulkan ICD use the recoverable graphics manager.
Original libraries remain outside loader search paths; the vendor .deb's broad
replacement scripts are never executed. The private OpenCL directory is kept.
No software Vulkan driver or desktop compositor is installed by this build.

The firmware is the previous validated video_ucode.bin (0.4.129-g7f05035,
SHA256 80522fd7376bde74be185e822c314f9beddee0264279bb4538d104588f46b094).
Its provenance is the previously working system file, not an invented new
upstream source. The runtime input bundles that exact binary.
Mali comes from numbqq/mali-debs commit 79a60bb30229f742cc57307187b5a2c2929fc5a5,
the VIM3L r44p0 package with SHA256
7ad4a803d02f0e5ac9be7db4b3d7b2e69e14b3ba695d384cfc7e21086bd1a822.

Services load system_heap, mali_kbase, aml_drm, then the vendor V4L2 decoders
amvdec_mh264_v4l/amvdec_h265_v4l/amvdec_ports. Parameters are multiplanar=1,
bypass_vpp=1, enable_drm_mode=0. Hardware decoder identity is aml-vcodec-dec;
a v4lvideo node does not count as a decoder.

```sh
uname -r
cat /etc/yzd-s18/image.json
lsusb -t
yzd-s18-video check
yzd-s18-video decode /opt/yzd-s18/video/samples/test_1080p_h264.mp4
yzd-s18-video decode /opt/yzd-s18/video/samples/test_1080p_h265.mp4
yzd-s18-video play /opt/yzd-s18/video/samples/test_1080p_h264.mp4
yzd-s18-video stop
/opt/yzd-s18/run_gpu_opencl.sh
/opt/yzd-s18/run_display_checks.sh smoke
yzd-s18-graphics status
```

The private FFmpeg 5.1.9 runtime retains NV12M capture validation, GLES2/alpha8,
exclusive fullscreen and signal-safe orderly teardown. Its source, patch and
GPL license are in /usr/share/doc/yzd-s18-video-source. Kernel source snapshots,
patches and build provenance are separate immutable input Release assets.

The first boot runs no video playback, GPU benchmarks or polling monitors.
Generic armbian-update/kernel/eMMC install commands are blocked on this image.
To restore original graphics libraries use yzd-s18-graphics restore; install
returns to the pinned Mali backend. Keep Mali enabled for vendor ffplay playback.

## Build validation and safety

The builder accepts regular files only; it never takes a physical flash target.
The clean source image is mounted read-only without journal replay. Package
scripts receive a private minimal /dev with no host disk nodes.
Cleanup records owned mounts and loop devices, unmounts in reverse order,
and stops on any busy mount. It uses rmdir for mountpoints, never recursive
deletion of the workspace. Failed workspaces remain for inspection.

Every published image passed filesystem/partition checks, package audit,
executable systemd/fsck checks, matching initramfs/provider validation,
uInitrd payload checks, GPU/VPU DTB validation and runtime hashes.
validation.json explicitly marks hardware acceptance pending. GitHub CI cannot
prove HDMI picture, native USB/UAS recovery, GPU acceleration or decoded pixels.
Those require a later boot on YZD-S18 with the new image. Flashing the physical
USB disk is a separate operation and is not performed by these build tools.
