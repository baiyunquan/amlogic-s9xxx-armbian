import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[1]


class InputTests(unittest.TestCase):
    def module(self):
        path = REPO / 'scripts/yzd-s18/inputs.py'
        self.assertTrue(path.is_file(), 'input validation is missing')
        spec = importlib.util.spec_from_file_location('inputs', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_archive_cannot_escape_destination(self):
        mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'bad.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                info = tarfile.TarInfo('../escape')
                info.size = 1
                tar.addfile(info, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                mod.extract(archive, Path(tmp) / 'out')
            self.assertFalse((Path(tmp) / 'escape').exists())

    def test_changed_published_asset_is_rejected(self):
        mod = self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'base.img.gz').write_bytes(b'changed')
            lock = root / 'lock.json'
            lock.write_text(json.dumps({'assets': {'base.img.gz': '0' * 64}}))
            with self.assertRaises(ValueError):
                mod.verify(root, lock)

    def test_failed_load_never_boots_and_device_number_is_not_fixed(self):
        path = REPO / 'scripts/yzd-s18/boot.cmd'
        self.assertTrue(path.is_file(), 'checked boot script is missing')
        for failed, count in [('kernel', 0), ('initrd', 0), ('dtb', 0), ('fdt', 0), ('none', 1)]:
            with self.subTest(failed=failed):
                with tempfile.TemporaryDirectory() as tmp:
                    log = Path(tmp) / 'boots'
                    code = '''setenv() { local key="$1"; shift; if (( $# )); then printf -v "$key" '%s' "$*"; else unset "$key"; fi; }
usb() { return 0; }
fatload() {
    [[ "$2" == 2:1 ]] || return 1
    case "$4:$FAILED" in /Image*:kernel|/uInitrd*:initrd|/dtb*:dtb) return 1;; esac
    filesize=100
}
env() { YZD_BOARD=yzd-s18; LINUX=/Image; INITRD=/uInitrd; FDT=/dtb/video.dtb; APPEND='root=UUID=test'; }
fdt() { [[ "$FAILED" != fdt ]]; }
booti() { echo "$dev" >> "$BOOTLOG"; }
source "$SCRIPT"
'''
                    result = subprocess.run(['bash', '-c', code], env={
                        'PATH': '/usr/bin:/bin', 'FAILED': failed, 'BOOTLOG': str(log), 'SCRIPT': str(path)},
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(len(log.read_text().splitlines()) if log.exists() else 0, count)


if __name__ == '__main__':
    unittest.main()
