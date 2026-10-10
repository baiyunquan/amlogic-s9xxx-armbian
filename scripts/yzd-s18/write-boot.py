#!/usr/bin/env python3
import json
from pathlib import Path
import sys
boot, identity = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text())
release = identity["kernel_release"]
lines = [
    "YZD_BOARD=yzd-s18", "initrd_high=0x7f800000", "fdt_high=0x20000000",
    f"LINUX=/Image-{release}", f"INITRD=/uInitrd-{release}",
    f"FDT=/dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-peripherals-peripherals.dtb",
]
args = (f"root=UUID={identity['root_uuid']} rw rootwait rootfstype=ext4 "
        "console=ttyS0,115200n8 no_console_suspend net.ifnames=0 "
        "fbcon=map:9 yzd_s18.display=1 yzd_s18.video=1 "
        "amvdec_ports.multiplanar=1 amvdec_ports.bypass_vpp=1 amvdec_ports.enable_drm_mode=0")
(boot/"uEnv.txt").write_text("\n".join(lines+[f"APPEND={args}"])+"\n")
(boot/"uEnv.bot.txt").write_text("\n".join(lines+[f"APPEND={args} usb-storage.quirks=152d:0562:u"])+"\n")
(boot/"uEnv.debug.txt").write_text("\n".join(lines+[f"APPEND={args} earlycon=meson,0xff803000 initcall_debug ignore_loglevel loglevel=8 log_buf_len=4M sysrq_always_enabled=1"])+"\n")
