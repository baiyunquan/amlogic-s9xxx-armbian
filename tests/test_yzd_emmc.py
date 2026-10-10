import subprocess
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/yzd-s18/armbian-install"


class EmmcInstallerTests(unittest.TestCase):
    def test_installer_is_syntax_checked_and_preserves_factory_regions(self):
        self.assertTrue(SCRIPT.is_file())
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
        text = SCRIPT.read_text()
        self.assertIn("385024", text)
        self.assertIn("start_emmc_autoscript", text)
        self.assertIn("boot0", text)
        self.assertIn("boot1", text)
        self.assertNotIn("mklabel", text)
        self.assertNotIn('of="$TARGET"', text)

    def test_install_requires_explicit_confirmation(self):
        text = SCRIPT.read_text()
        self.assertIn("install requires --yes", text)
        self.assertIn("eMMC not visible", text)
        self.assertIn("factory data partition not found", text)


if __name__ == "__main__":
    unittest.main()
