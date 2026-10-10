import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / 'scripts/yzd-s18/emmc_install.py'


class EmmcLayoutTests(unittest.TestCase):
    def module(self):
        self.assertTrue(PATH.exists(), 'single-data installer is missing')
        spec = importlib.util.spec_from_file_location('emmc_install', PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def table(self):
        return {'partitiontable': {'label': 'dos', 'sectorsize': 512,
                'partitions': [{'node': '/dev/mmcblk0p1', 'start': 262144,
                                'size': 14712832, 'type': '83'}]}}

    def test_known_single_data_layout(self):
        module = self.module()
        self.assertEqual(module.validate_layout(self.table(), '/dev/mmcblk0',
                                               15147008 * 512), '/dev/mmcblk0p1')

    def test_unknown_geometry_and_root_target_rejected(self):
        module = self.module()
        table = self.table()
        table['partitiontable']['partitions'][0]['start'] = 8192
        with self.assertRaises(RuntimeError):
            module.validate_layout(table, '/dev/mmcblk0', 15147008 * 512)
        with self.assertRaises(RuntimeError):
            module.validate_source('/dev/mmcblk0p1', '/dev/mmcblk0', '/dev/mmcblk0')

    def test_initramfs_bare_directory_does_not_cross_line(self):
        module = self.module()
        release = module.RELEASE
        listing = f"usr/lib/modules/{release}\nusr/lib/modules/{release}/kernel/example.ko\n"
        self.assertEqual(module.initramfs_releases(listing), {release})
        self.assertEqual(module.initramfs_releases(listing + "lib/modules/6.12.0/kernel/test.ko\n"),
                         {release, "6.12.0"})

    def test_checked_loader_never_saves_environment(self):
        module = self.module()
        text = module.boot_script(1)
        self.assertNotIn('saveenv', text)
        self.assertNotIn('fw_setenv', text)
        self.assertIn('ext4load mmc 1:1', text)
        self.assertIn('if fdt addr', text)
        self.assertIn('if fdt resize', text)


if __name__ == '__main__':
    unittest.main()
