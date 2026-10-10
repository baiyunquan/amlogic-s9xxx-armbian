# YZD-S18 eMMC installer and release workflow

## Goal

Ship a formal YZD-S18 Bookworm image with an `armbian-install` command that
installs the running USB system to the factory eMMC data partition without
writing boot0, boot1, the factory MBR, or a replacement U-Boot image.

## Design

1. Detect a real eMMC from `/sys/block/mmcblk*/device` and refuse to operate
   when the eMMC controller is absent or the selected device is the current
   root disk.
2. Require the factory DOS/extended layout and the known data-partition
   geometry before any write. Back up the first 4 MiB, boot0/boot1, all small
   factory partitions, `sfdisk` output, and the U-Boot environment first.
3. Format only the verified data partition with old-U-Boot-compatible ext4,
   copy the USB root filesystem, create an eMMC DTB with the eMMC controller
   enabled, and write a single ext4 `/boot/uEnv.txt`.
4. Update only `start_emmc_autoscript` through `fw_setenv`; preserve the
   original `bootcmd` and USB autoscript fallback. Provide a variable restore
   command using the saved value and raw backups.
5. Add static/offline checks to the existing YZD build and publish the image,
   installer documentation, checksums, and layout report in a non-prerelease
   GitHub Release.

## Verification

- `status` and `--dry-run` on the current USB boot must report that eMMC is
  disabled and must not modify a block device.
- Shell syntax, repository tests, and workflow YAML checks must pass.
- The image build must contain the installer, eMMC DTB, compatibility ext4
  features, and the release manifest.
- A real install is performed only after the board is booted with an
  eMMC-enabled DTB; the user performs the subsequent reboot and physical
  fallback check.
