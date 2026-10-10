# YZD-S18 current eMMC installation (2026-10-10)

This machine uses DOS/MBR with one Linux data partition, not the old factory
extended p8 layout. The installer in `scripts/yzd-s18/emmc_install.py` accepts
only the observed 7,755,268,096-byte device: p1 starts at sector 262144 and has
14712832 sectors. It preserves the first 128 MiB, final 84 MiB, MBR, boot0,
boot1 and persistent U-Boot environment; it never reboots. Unknown layouts
and a target containing the running root are rejected.

The current USB is the source. Its installed desktop/player/runtime tools,
settings and accounts are copied; pseudo-filesystems, USB BOOT, backups and
staging files are excluded. The native kernel package from the verified
peripherals CI image replaces the old usbfix package so dpkg, headers and
modules match `5.15.137-yzd-s18-peripherals`. initramfs is built inside the
actual target root using a private /dev with no exposed block devices.

The source-compiled `zh_s905x3_4g_rgmii_emmc.dts` inherits the peripherals
profile and removes only `yzd-s18,peripherals-profile`, replacing it with
`yzd-s18,emmc-profile`. This prevents the USB acceptance udev rule from
forcing the installed root read-only. All eMMC supplies, reset, skip-dtbkey
write guard, raw IR, GPU/VPU, video memory and USB fixes remain unchanged.

The existing factory U-Boot loads `/boot/s905_autoscript` from MMC 1:1.
The new checked script loads matching Image/initramfs/DTB and validates FDT
before booti; loading failures stop without booting stale memory. The old
2024 `u-boot.bin` is retained as an ordinary recovery file, but the default
script boots directly with the original bootloader. The old persistent-env
writing `aml_autoscript` is deliberately not installed.

The repository's older shell `armbian-install` and published CI image still
contain the legacy factory-layout installer. This helper was reviewed and
deployed explicitly on the current machine; publishing a replacement input
and workflow is deferred until the user verifies eMMC boot.

## Boot after installation

After the installation is reported successful, run `poweroff` from the
current USB system, wait for shutdown, remove the system USB, and power on.
If necessary, from the existing factory U-Boot prompt:

```
if ext4load mmc 1:1 0x01020000 /boot/s905_autoscript; then autoscr 0x01020000; fi
```

Do not save environment. For USB recovery, power off, reconnect the original
USB and power on; its UUID/default peripherals profile remain unchanged.
The original raw boot areas and full eMMC image are backed up on the USB at
`/var/backups/yzd-s18-emmc/20261010T122436Z`.

Installation/boot results are recorded below after completion. An offline
filesystem check is not an eMMC hardware boot acceptance result.

## Input and backup checks

The full eMMC backup is 7,755,268,096 bytes. Independent USB and host copies
have the same SHA256:
`8f90066d5deff15be96839285cc51ea63028351662c9c0277f474b7a3bac1a99`.
The host copy is in the porting workspace under
`logs/emmc-install/protected-backup/emmc-full.img`.

The native kernel package was extracted from the pinned CI image, whose
published SHA256 passed before the read-only extraction. Package SHA256:
`36c838ab7a5faa9eeb376e27f4c52be6d57863ec230bd6b4c92349782b15870b`.
Compiled eMMC-root DTB SHA256:
`e4e47f3414b042c385937c932e249996e1cc0f84259490eea5dc868473f2f3c1`.
Decompiled DTB comparison changed only the model and root profile marker.

## Completed installation and offline acceptance

The real install on `root@yzd-s18` completed. Current USB root UUID and boot
configuration remain unchanged; no reboot was performed.

- Target root UUID: `f3577a63-9207-4a23-8a5e-74950ab370a1`.
- Kernel package, modules and headers: `5.15.137-yzd-s18-peripherals`.
- Fresh target initramfs SHA256:
  `ac4dc1d67b29ea41b3ff106f1d09f6fbaebbab83f33dcbf76015b7f3e3742d6e`;
  uInitrd payload matched. GPIO/pinctrl, MMC/pwrseq and fsck.ext4 were present.
- `dpkg --audit`, executable checks and MMC/IR/Mali/VPU module vermagic passed.
  Existing Xorg/VLC and the patched FFmpeg 5.1.9 were preserved.
- e2fsck completed all five passes: 130487 files and 937710/1839104 blocks.
  Incompatible 64bit/metadata_csum/metadata_csum_seed/orphan_file are disabled.
- Prefix, trailing region and both hardware boot area SHA256 values matched
  the original backup after installation. Partition table was unchanged.
- Target is unmounted and block-read-only until the next boot; the eMMC-root
  DTS omits the acceptance RO marker, so that flag is not imposed next boot.

The first automated run stopped at a false version mismatch: its regex
crossed the bare modules-directory newline. A regression test reproduced
`5.15.137-yzd-s18-peripherals\nusr`; line-anchored parsing fixed it. The
written system was retained, the fixed helper was copied into the target,
and all remaining checks were resumed without formatting or recopying.
The first-run log is preserved; `install-result.json` records final success
and the original false alarm is archived separately.

Evidence is in the porting workspace `logs/emmc-install/` (finalize.log,
final-offline-verification.txt, target-fsck.txt, install-result.json and
final-device-state.txt), and on the source USB in the backup directory above.
**Installation and offline checks passed; first eMMC hardware boot remains
pending the user's manual shutdown, USB removal and power-on.** After boot:

```sh
uname -r
findmnt -n -o SOURCE,UUID /
# expected: /dev/mmcblk0p1 f3577a63-9207-4a23-8a5e-74950ab370a1
```
