import importlib.util
from pathlib import Path
import unittest
import re
import subprocess
import tempfile


class GrowthTests(unittest.TestCase):
    def test_legacy_startup_cannot_resize(self):
        repo = Path(__file__).resolve().parents[1]
        setup = (repo / 'scripts/yzd-s18/setup-rootfs.sh').read_text()
        value = re.search(r"printf '([^']*)' > /root/\.no_rootfs_resize", setup).group(1)
        startup = (repo / 'build-armbian/armbian-files/common-files/etc/custom_service/start_service.sh').read_text()
        block = startup.split('# Maximize root partition size')[1].split('# Finalization')[0]
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / 'resize-flag'
            unsafe = Path(tmp) / 'unsafe-resize'
            script = "printf '" + value + "' > '" + str(flag) + "'\n"
            script += "armbian-tf() { touch '" + str(unsafe) + "'; }; log_message() { :; };\n"
            script += block.replace('/root/.no_rootfs_resize', str(flag)) + '\nwait\n'
            result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, check=True)
            self.assertFalse(unsafe.exists(), result.stderr)

    def test_wrong_boot_size_is_rejected(self):
        path = Path(__file__).resolve().parents[1] / 'build-armbian/armbian-files/different-files/yzd-s18/rootfs/opt/yzd-s18/grow-root.py'
        spec = importlib.util.spec_from_file_location('grow', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        table = {'partitiontable': {'label': 'dos', 'device': '/dev/sda', 'partitions': [
            {'node': '/dev/sda1', 'start': 8192, 'size': 1, 'type': 'c'},
            {'node': '/dev/sda2', 'start': 1056768, 'size': 123, 'type': '83'}]}}
        with self.assertRaises(RuntimeError):
            mod.validate(table, '/dev/sda2')


if __name__ == '__main__':
    unittest.main()
