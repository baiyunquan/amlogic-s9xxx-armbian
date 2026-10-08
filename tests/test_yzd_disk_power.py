import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "build-armbian/armbian-files/different-files/yzd-s18/rootfs/usr/local/sbin/yzd-s18-disk-power"
BOOT_SERVICE = REPO / "build-armbian/armbian-files/different-files/yzd-s18/rootfs/etc/systemd/system/yzd-s18-disk-power.service"
PARK_SERVICE = REPO / "build-armbian/armbian-files/different-files/yzd-s18/rootfs/etc/systemd/system/yzd-s18-disk-park.service"


class DiskPowerTests(unittest.TestCase):
    def test_image_contains_guarded_policy_and_shutdown_park(self):
        self.assertTrue(SCRIPT.is_file())
        self.assertIn("hdparm -S", SCRIPT.read_text())
        self.assertIn("hdparm -y", SCRIPT.read_text())
        self.assertIn("lsblk -sno KNAME", SCRIPT.read_text())
        self.assertIn("After=umount.target", PARK_SERVICE.read_text())
        self.assertIn("WantedBy=poweroff.target reboot.target halt.target", PARK_SERVICE.read_text())
        self.assertIn("WantedBy=multi-user.target", BOOT_SERVICE.read_text())

    def test_apply_and_park_exclude_root_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "bin"
            fake.mkdir()
            log = Path(tmp) / "hdparm.log"
            (fake / "findmnt").write_text(
                "#!/bin/sh\ncase \"$5\" in /boot) echo /dev/sdb1 ;; *) echo /dev/sdb2 ;; esac\n"
            )
            (fake / "lsblk").write_text(
                """#!/bin/sh
if [ "$1" = "-sno" ]; then
    case "$3" in
        /dev/sdb2) printf '%s\\n' sdb2 sdb ;;
        /dev/sdb1) printf '%s\\n' sdb1 sdb ;;
    esac
else
    printf '%s\\n' 'sda disk 1 0 usb' 'sdb disk 1 0 usb' 'sdc disk 0 0 usb'
fi
"""
            )
            (fake / "hdparm").write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HDLOG\"\n"
            )
            for name in ("logger", "sync"):
                (fake / name).write_text("#!/bin/sh\nexit 0\n")
            for path in fake.iterdir():
                path.chmod(0o755)
            env = {
                "PATH": str(fake),
                "HDLOG": str(log),
            }
            applied = subprocess.run(["/bin/bash", str(SCRIPT), "apply"], env=env, capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual(log.read_text().splitlines(), ["-S 120 /dev/sda"])
            self.assertIn("skip root/boot disk /dev/sdb", applied.stderr)
            log.unlink()
            parked = subprocess.run(["/bin/bash", str(SCRIPT), "park"], env=env, capture_output=True, text=True)
            self.assertEqual(parked.returncode, 0, parked.stderr)
            self.assertEqual(log.read_text().splitlines(), ["-y /dev/sda"])
            self.assertIn("skip root/boot disk /dev/sdb", parked.stderr)


if __name__ == "__main__":
    unittest.main()
