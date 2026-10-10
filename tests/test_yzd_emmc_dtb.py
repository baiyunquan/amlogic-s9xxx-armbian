from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class EmmcDtbTests(unittest.TestCase):
    def test_installer_preserves_compiled_emmc_properties(self):
        text = (REPO / 'scripts/yzd-s18/armbian-install').read_text()
        function = 'make_dtb(){' + text.split('make_dtb(){', 1)[1].split('\ncopy_system(){', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            boot = Path(tmp) / 'boot/dtb/amlogic'
            boot.mkdir(parents=True)
            dts = '/dts-v1/; / { emmc@ffe07000 { status="okay"; bus-width=<8>; max-frequency=<52000000>; pinctrl-names="default", "clk-gate"; }; };'
            compiled = boot / 'zh_s905x3_4g_rgmii-yzd-s18-emmc.dtb'
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(compiled)],
                           input=dts, text=True, check=True, capture_output=True)
            before = compiled.read_bytes()
            # A tempting status-only video DTB must never replace the companion.
            subprocess.run(['dtc', '-I', 'dts', '-O', 'dtb', '-o', str(boot/'old-video.dtb')],
                           input='/dts-v1/; / { emmc@ffe07000 { status="disabled"; }; sdio@ffe03000 { status="disabled"; }; };',
                           text=True, check=True, capture_output=True)
            code = 'need(){ :; }; die(){ echo "$*" >&2; exit 1; };\n' + function + '\nmake_dtb "$1"\n'
            result = subprocess.run(['bash', '-e', '-c', code, '_', tmp],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(compiled.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
