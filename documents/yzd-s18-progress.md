# YZD-S18 build implementation ledger

Plan: user-approved Bookworm USB system / GitHub Actions, 2026-10-08.
Base commit: 7d81e344. Work on main was explicitly requested.

- Inputs: existing USB-fix kernel, fixed clean Bookworm base, validated Mali,
  vendor video firmware and patched FFmpeg; no damaged rootfs copying.
- Interfaces: published input lock feeds builder; builder generates image.json;
  runtime tools consume that manifest; workflow publishes only verified output.
- Ruling: use a dedicated YZD dispatch in rebuild, sharing the repository's
  platform/common overlay, instead of applying vendor assumptions to all boards.
  This avoids altering existing board builds and permits read-only base input.
- Safety RED: missing cleanup helper detected by busy-mount regression.
- Task 1 complete: f6be0b9b, busy mount/data-preservation test passed on a real loop filesystem.
- Inputs packaged: 61 MiB kernel, 218 MiB exact source snapshot, 29 MiB vendor
  runtime; all 1512 module architectures/vermagic and video DTS/CMA checked.
- Input/boot RED to GREEN: rejects tampered assets and unsafe tar paths;
  failed loads or invalid FDT never boot; device index 2 works.
- Ruling: package precompiled payload as yzd-s18-kernel with no generic kernel
  hooks, remove the base kernel through apt, and generate initramfs explicitly
  inside final Bookworm rootfs. This keeps dpkg consistent and one kernel ABI.
- Ruling: disable the generic armbian-fix first-boot cleanup/resize entrypoint
  in this profile. Dedicated SSH identity and guarded USB resize services replace it.
- Independent review found the common startup script also launches armbian-tf
  when .no_rootfs_resize is yes. Its actual startup block was reproduced in a
  regression (RED), then disabled with no and a diverted armbian-tf (GREEN).
- Independent review found missing native header helpers in the cross-built
  headers. Build those in Bookworm external-module mode to preserve the pinned
  kernel configuration; require a compiled external module with matching ABI.
- Local integration found inherited host PATH and chroot fsck detection issues.
  Set Debian PATH explicitly and FSTYPE=ext4; preserve a private /dev and require
  executable checks to stop on the first failure.
- Completed 2026-10-08: main pushed; immutable inputs published at
  https://github.com/baiyunquan/amlogic-s9xxx-armbian/releases/tag/yzd-s18-inputs-v1.
- Final build commit: 40621b9e3d25fc655525ce710fd516440cec1d69.
  ARM64 workflow https://github.com/baiyunquan/amlogic-s9xxx-armbian/actions/runs/37745223274
  completed successfully. All seven regressions, native headers/module smoke,
  chroot/runtime, initramfs, DTB, filesystem and installed-file hash gates passed.
- Final image and reports:
  https://github.com/baiyunquan/amlogic-s9xxx-armbian/releases/tag/yzd-s18-bookworm-20261008-40621b9e-2.
  SHA256 a418023dd27f06d750b5afb27ae9ccb57280dfec7c230633aef9e1145b74e509.
- Downloaded final image locally. sha256sum and gzip integrity passed; direct
  reads of MBR, FAT UUID and ext4 superblock match the final manifest. Checked
  orphan_file is absent. See yzd-s18-download-verification.json.
- Status: image construction and offline checks complete. New-image boot,
  four cores, SSH, native JMicron UAS, GPU/VPU and HDMI playback acceptance pending.
