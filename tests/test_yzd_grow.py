import importlib.util
from pathlib import Path
import unittest


class GrowthTests(unittest.TestCase):
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
