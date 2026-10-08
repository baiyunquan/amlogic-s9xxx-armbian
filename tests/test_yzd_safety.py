import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
LIB = REPO / 'scripts/yzd-s18/safety.sh'


class CleanupTests(unittest.TestCase):
    def test_busy_mount_preserves_workspace(self):
        self.assertTrue(LIB.is_file(), 'safe cleanup library is missing')
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'valuable.txt'
            marker.write_text('keep me')
            code = f'''source "{LIB}"
YZD_WORK="$1"
YZD_MOUNTS=("$1/root")
YZD_LOOPS=()
mountpoint() {{ return 0; }}
umount() {{ return 1; }}
yzd_cleanup
'''
            result = subprocess.run(['bash', '-c', code, '_', tmp], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(), 'keep me')

    @unittest.skipUnless(os.geteuid() == 0, 'run as root for real loop/mount test')
    def test_real_busy_loop_mount_is_preserved(self):
        self.assertTrue(LIB.is_file(), 'safe cleanup library is missing')
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'test.img'
            image.write_bytes(b'')
            with image.open('r+b') as f:
                f.truncate(16 * 1024 * 1024)
            subprocess.run(['mkfs.ext4', '-q', '-F', str(image)], check=True)
            loop = subprocess.check_output(['losetup', '-f', '--show', str(image)], text=True).strip()
            target = Path(tmp) / 'root'
            target.mkdir()
            child = None
            try:
                subprocess.run(['mount', loop, str(target)], check=True)
                (target / 'valuable.txt').write_text('keep me')
                child = subprocess.Popen(['sleep', '120'], cwd=target)
                code = f'''source "{LIB}"
YZD_WORK="$1"
YZD_MOUNTS=("$1/root")
YZD_LOOPS=("$2")
yzd_cleanup
'''
                result = subprocess.run(['bash', '-c', code, '_', tmp, loop], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((target / 'valuable.txt').read_text(), 'keep me')
                subprocess.run(['mountpoint', '-q', str(target)], check=True)
                child.terminate()
                child.wait()
                child = None
                subprocess.run(['bash', '-c', code, '_', tmp, loop], check=True)
                self.assertNotEqual(subprocess.run(['losetup', loop], capture_output=True).returncode, 0)
            finally:
                if child is not None:
                    child.terminate()
                    child.wait()
                subprocess.run(['umount', str(target)], capture_output=True)
                subprocess.run(['losetup', '-d', loop], capture_output=True)


if __name__ == '__main__':
    unittest.main()
