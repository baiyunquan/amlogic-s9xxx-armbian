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
- 实机复核 2026-10-08：SSH 进入 `yzd-s18`，运行
  `5.15.137-yzd-s18-usbfix`；4 核在线、内存 3.4 GiB，根分区为 USB
  `/dev/sdb2`，UUID 与 image.json 一致，千兆以太网 1000Mb/s 全双工。
- JMicron JMS567 位于 USB 3 SuperSpeed，`lsusb -t` 明确显示
  `Driver=uas`，对应 `/dev/sda`；只读 32 MiB 读取成功（106 MB/s），复核后无
  UAS reset、timeout 或 I/O error。
- `/dev/mali0` 和 Meson `/dev/dri/card0` 已注册。EGL GBM vendor=ARM、
  GLES3.2 Mali-G31；GLES smoke 像素校验和 Vulkan logical-device/queue smoke
  均通过。固定 ICD 的 OpenCL smoke 枚举 Mali-G31，100×1048576 整数校验通过。
  裸 `clinfo` 没有 vendor 目录而显示 0 平台，项目入口会显式使用固定 Mali ICD。
- HDMI-A-1 当前 connected，读取到 256-byte EDID 和 11 个模式，preferred
  模式为 1080p60。DRM glmark2 子基准完整结束，Mali-G31 在 2560x1440 输出下
  得分 147；默认完整套件在无独立 VT 的 SSH 会话中被保护超时/恢复 CRTC 报
  `-2`，不作为完整套件成绩交付。
- `/dev/video26` 驱动为 `aml-vcodec-dec`，具备 multiplanar/streaming，输入
  同时列出 H264 与 HEVC。H.264 和 H.265 样例均以厂商 V4L2 解码器完成 300 帧。
  未发现 panic、Oops、lockup、GPU reset、UAS 错误或 DRM timeout；保留启动时
  的 eMMC/温控/`osd_axi_sel` 兼容性警告作为非阻断日志。
