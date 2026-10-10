#!/usr/bin/env python3
"""Artifact gate for the USB/eMMC/raw-IR profile, before any board boot."""
import argparse
from pathlib import Path
import subprocess


def prop(dtb, node, name, kind="s"):
    return subprocess.check_output(
        ["fdtget", "-t", kind, str(dtb), node, name], text=True
    ).strip()


def verify(dtb, config):
    def p(node, name, kind="s"):
        return prop(dtb, node, name, kind)
    def symbol(label):
        return p("/__symbols__", label)
    def present(node, name):
        subprocess.run(["fdtget", str(dtb), node, name], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    emmc = symbol("sd_emmc_c")
    assert p(emmc, "status") == "okay"
    assert p(emmc, "bus-width", "i") == "8"
    assert p(emmc, "max-frequency", "i") == "52000000"
    assert p(emmc, "save_para", "i") == "0"
    assert p(emmc, "pinctrl-names") == "default clk-gate"
    assert p(emmc, "pinctrl-0", "x").split() == [
        p(symbol(label), "phandle", "x") for label in ("emmc_pins", "emmc_ds_pins")]
    assert p(symbol("emmc_pwrseq"), "reset-gpios", "i").split()[1:] == ["38", "1"]
    for label, voltage in (("flash_vcc", "3300000"), ("flash_vqmmc", "1800000")):
        assert p(symbol(label), "regulator-min-microvolt", "i") == voltage
        assert p(symbol(label), "regulator-max-microvolt", "i") == voltage
    for name in ("non-removable", "cap-mmc-highspeed",
                 "amlogic,skip-dtbkey-init"):
        present(emmc, name)
    for name in ("mmc-hs200-1_8v", "mmc-hs400-1_8v", "mmc-ddr-1_8v",
                 "supports-cqe"):
        assert subprocess.run(["fdtget", str(dtb), emmc, name],
                              capture_output=True).returncode != 0
    for supply in ("vmmc-supply", "vqmmc-supply", "mmc-pwrseq"):
        assert int(p(emmc, supply, "x"), 16) > 0
    ir = symbol("ir")
    assert p(ir, "status") == "okay"
    assert p(ir, "compatible") == "amlogic,meson-gxbb-ir"
    assert p(ir, "reg", "x") == "0 ff808000 0 24"
    assert p(ir, "interrupts", "i") == "0 196 1"
    assert p(symbol("remote_pins") + "/mux", "groups") == "remote_ao_input"
    assert p(symbol("irblaster"), "status") == "disabled"
    assert p(symbol("sd_emmc_a"), "status") == "disabled"
    for label in ("gpu", "vpu", "drm_vpu", "amhdmitx", "drm_subsystem"):
        assert p(symbol(label), "status") == "okay", label
    for node in ("/vdec", "/vcodec_dec", "/codec_mm"):
        assert p(node, "status") == "okay", node
    assert sum(int(p(symbol(label), "size", "x").split()[-1], 16)
               for label in ("codec_mm_cma", "ion_cma_reserved",
                             "dmaheap_fb_reserved", "dmaheap_gfx_reserved")) == 564 * 1024**2
    text = Path(config).read_text()
    for line in ("CONFIG_IR_MESON=m", "CONFIG_LIRC=y", "CONFIG_RC_CORE=y",
                 "CONFIG_PWRSEQ_EMMC=m", "CONFIG_MMC_BLOCK_MINORS=32",
                 "CONFIG_KFENCE_SAMPLE_INTERVAL=500", "CONFIG_KVM=y"):
        assert line + "\n" in text, line
    assert "# CONFIG_ARCH_MESON is not set\n" in text
    print("peripherals artifact gate: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dtb", type=Path)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    verify(args.dtb, args.config)
