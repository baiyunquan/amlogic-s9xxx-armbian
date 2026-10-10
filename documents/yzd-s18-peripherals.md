# YZD-S18 eMMC and raw IR USB profile — 2026-10-10

- [Published image and reports](https://github.com/baiyunquan/amlogic-s9xxx-armbian/releases/tag/yzd-s18-bookworm-20261010-b7e67e8f-6)
- [Successful ARM64 workflow](https://github.com/baiyunquan/amlogic-s9xxx-armbian/actions/runs/38039693786)
- Image SHA256: `8d97c096d7d23db87ab765b8cada18011b0c5e229c84218d8e31f1867f46e887`

Published validation/identity/partition/input reports were downloaded and
matched the pinned peripherals release, v2 inputs and expected USB layout.
The new image itself has not been flashed or hardware-booted in this round.
The bundle's selected full profile is
`zh_s905x3_4g_rgmii-yzd-s18-peripherals-peripherals.dtb`; the shorter
`...-yzd-s18-peripherals.dtb` in that bundle is the compute-only variant.
On the existing USB the selected full DTB was deployed under the shorter
`...-yzd-s18-peripherals.dtb` name, as recorded in its uEnv configuration.

The source-compiled `5.15.137-yzd-s18-peripherals` was booted through UART
on the existing USB Bookworm installation. This round did not run
armbian-install, format eMMC, write its partition table, or save U-Boot env.
The bundled installer rejects `install` when this acceptance profile is
active. Its DTB preparation validates the source-compiled companion and
cannot replace it with a status-only copy of the old video DTB.

## Kernel and DTS changes

- The peripherals DTS inherits the accepted video DTS, retaining USB/UAS
  fixes, Ethernet, GPU/VPU/DRM, 564 MiB CMA, KVM and KFENCE 500 ms.
- eMMC uses the vendor SM1 controller, 8-bit bus, high-speed SDR capped at
  52 MHz, default/clk-gate pinctrl, fixed 3.3 V VCC and 1.8 V I/O regulator
  descriptions, and BOOT_12 active-low reset through mmc-pwrseq-emmc.
  DDR, HS200, HS400 and CQE are not enabled in this acceptance profile.
- `amlogic,skip-dtbkey-init` prevents scheduling vendor `add_dtbkey`, whose
  key initialization can repair/write the factory reserved region.
  `save_para=0` prevents stored tuning parameter access. This opt-out applies
  only to the board; legacy vendor users keep their original behavior.
- `CONFIG_MMC_BLOCK_MINORS=32` permits extended factory partition layouts;
  `CONFIG_PWRSEQ_EMMC=m` supplies the hardware reset provider.
- IR uses `amlogic,meson-gxbb-ir`, ff808000/0x24, IRQ 196 and GPIOAO_5.
  NEC/map-specific vendor properties are removed. IR_MESON is enabled as a
  module through a narrow Kconfig dependency on existing AMLOGIC_DRIVER,
  retaining ARCH_MESON disabled. The IR transmitter remains disabled.
- udev prevents eMMC automount/journal replay and sets its block disks
  read-only. `/dev/lirc-yzd-s18` resolves to the meson-ir raw receiver.

## Board acceptance

- SSH recovered with four CPUs online, 3.4 GiB RAM and 1000 Mb/s full duplex.
  A second normal default USB reboot recovered the original MAC
  `18:c8:e7:12:10:c5`; the temporary chainloaded bootloader's random MAC was
  not persisted.
- Root remained USB UUID `2318c106-c35c-490c-82ed-f0407b63a73c`; BOOT UUID
  `A996-1B12`. Display and video services were active; card0, mali0 and
  video26 were present. HDMI was disconnected, so no picture claim is made.
- eMMC `SPeMMC`, CID `ea010e5350654d4d43101f0573c09900`, 7.22 GiB,
  appeared as mmcblk0 with 4 MiB boot0/boot1. The current device has one DOS
  partition: p1 start 262144, size 14712832 sectors. This differs from the
  old factory-backup p8 layout; no partition number is inferred from that
  backup for this machine.
- ios reported 8-bit MMC high-speed, requested 52 MHz / actual 50 MHz.
  Its logical signal-voltage field reports 3.3 V; the DTS fixed 1.8 V rail
  description is inherited from the previous working board DTS and is not
  a measured voltage claim.
- mmcblk0 and both boot areas reported RO=1. Two independent reads of the
  first 4 MiB of each produced identical hashes. Main area:
  `0905462a7b7dae8cff3aad124bc191905dd5bcb97ac27ee2a0b51d4bd96d70e6`;
  boot0/boot1: `0263d24adee049f09d7e2f13acc1da8105372a33f51399906d0b8e896184a9b0`.
- LIRC reported raw reception, 10 us resolution and no transmitter. rc0
  used meson-ir/rc-empty with only lirc enabled. The initial bounded capture
  received no pulses. A subsequent 60-second capture while the user pressed
  keys received 3764 events: 1882 pulses, 1831 spaces and 51 timeouts.
  Offline parsing found 53 complete 32-bit NEC frames, 40 NEC repeat frames
  and 10 distinct commands. All 53 address/command inverse-byte checks passed;
  every observed full NEC leader had 32 decoded bits. The receiver interrupt
  count was 11262. Physical raw IR reception is now accepted; this particular
  sample contains NEC remote packets, so Bosch144 AC decoding remains untested.
- OpenCL passed 100 x 1,048,576 integer additions with full comparisons.
  The captured kernel log contained no panic, SError, workqueue lockup,
  GPU reset or DRM commit/page-flip timeout matching the acceptance patterns.

## Manual IR check and USB fallback

```sh
ir-ctl -d /dev/lirc-yzd-s18 --features
timeout 20 ir-ctl -d /dev/lirc-yzd-s18 --receive=/var/tmp/ir.raw --mode2
# Point an ordinary remote at the receiver and press during the window.
cat /var/tmp/ir.raw
```

Timeout exit 124 is normal for a bounded capture. The follow-up physical
capture passed; raw events and decoded NEC frame counts are recorded in
`logs/peripherals/ir-recapture.raw` and `ir-recapture-result.json` in the
porting workspace. The user confirmed this was an ordinary remote, not a Midea AC remote.
The capture accepts physical raw reception and NEC frames; it does not establish
a specific remote brand or AC protocol. No AC daemon or IR transmission was started.

The existing USB now defaults to the peripherals config and preserves
`/boot/uEnv.usbfix.txt`. To restore the previous kernel on the USB root:

```sh
cp /boot/uEnv.usbfix.txt /boot/uEnv.txt
sync
# reboot only when ready; the runtime manifest service selects the actual release
```

No saveenv is needed. If stopped in U-Boot, the checked UART helper can load
`/uEnv.usbfix.txt` using the same USB marker/UUID validation. It scans USB
device numbers and stops on any failed Image/initramfs/FDT load.

Kernel/source input Release v2 pins the new release and 1514 modules; the
unchanged base image and vendor runtime are fetched from immutable v1 assets.
CI validates new image contents offline. A successful CI build is not proof
that the newly constructed image has itself passed a hardware boot test.
