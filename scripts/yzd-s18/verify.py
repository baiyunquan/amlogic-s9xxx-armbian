#!/usr/bin/env python3
"""Offline kernel/rootfs/partition gate; never substitutes for hardware tests."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
from inputs import RELEASE, sha

def call(args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()

def kernel(root):
    root = Path(root)
    data = json.loads((root/"manifest.json").read_text())
    assert data["kernel_release"] == RELEASE
    for name, digest in data["files"].items():
        assert sha(root/name) == digest, name
    modules = sorted((root/"modules").rglob("*.ko"))
    assert len(modules) == 1512, len(modules)
    for file in modules:
        with file.open("rb") as f:
            header=f.read(20)
        assert header[:4] == b"\x7fELF" and struct.unpack_from("<H", header, 18)[0] == 183, str(file)
        assert call(["modinfo", "-F", "vermagic", file]).startswith(RELEASE+" "), str(file)
    dtb=root/"boot/dtb/amlogic/zh_s905x3_4g_rgmii-yzd-s18-usbfix-video.dtb"
    def prop(node, name, kind="s"):
        return call(["fdtget","-t",kind,dtb,node,name])
    def sym(label):
        return prop("/__symbols__",label)
    for label in ("vpu","drm_vpu","drm_subsystem","amhdmitx","gpu"):
        assert prop(sym(label),"status") == "okay", label
    for node in ("/vdec","/vcodec_dec","/codec_mm"):
        assert prop(node,"status") == "okay", node
    assert prop(sym("dwc3"),"snps,quirk-frame-length-adjustment","x") == "20"
    call(["fdtget", dtb, sym("dwc3"), "snps,parkmode-disable-ss-quirk"])
    assert sum(int(prop(sym(label),"size","x").split()[-1],16) for label in (
        "codec_mm_cma","ion_cma_reserved","dmaheap_fb_reserved","dmaheap_gfx_reserved")) == 564*1024*1024
    return {"module_count":len(modules),"release":RELEASE,"dtb":"video","cma_mib":564}

def partitions(path):
    parts=json.loads(Path(path).read_text())["partitiontable"]
    assert parts["label"] == "dos"
    p=parts["partitions"]
    assert len(p)==2
    assert (p[0]["start"],p[0]["size"],p[0]["type"]) == (8192,1046528,"c")
    assert (p[1]["start"],p[1]["size"],p[1]["type"]) == (1056768,12582912,"83")
    return {"mbr":True,"boot_start":8192,"root_start":1056768}

def rootfs(root):
    root=Path(root)
    identity=json.loads((root/"etc/yzd-s18/image.json").read_text())
    assert identity["kernel_release"]==RELEASE
    assert len(list((root/"usr/lib/modules").iterdir()))==1
    for name in ("sbin/init","usr/lib/systemd/systemd","sbin/fsck.ext4","usr/bin/python3","usr/sbin/sshd","var/lib/dpkg/status"):
        assert (root/name).exists(), name
    fstab=(root/"etc/fstab").read_text()
    env=(root/"boot/uEnv.txt").read_text()
    assert identity["root_uuid"] in fstab and identity["root_uuid"] in env
    assert identity["boot_uuid"] in fstab and "console=ttyS0," in env
    assert "usb-storage.quirks" not in env
    boot=root/"boot"
    assert len(list(boot.glob("Image-*")))==1
    assert not list(boot.glob("*ophub*"))
    assert sha(root/"usr/lib/firmware/video/video_ucode.bin")=="80522fd7376bde74be185e822c314f9beddee0264279bb4538d104588f46b094"
    assert sha(root/"opt/yzd-s18/mali-r44p0/lib/libMali.so")=="c2524056ef47ed5b503615a2aa7bf133bffadcd0fd3dba236ee9778f725bf64d"
    listing=(root/"var/lib/yzd-s18/initramfs.list").read_text()
    versions=set()
    for line in listing.splitlines():
        if "/modules/" in line:
            versions.add(line.split("/modules/")[1].split("/")[0])
    assert versions=={RELEASE}, versions
    assert "fsck.ext4" in listing
    assert int(call(["df","-B1","--output=avail",boot]).splitlines()[-1])>=128*1024*1024
    payload=call(["sha256sum",boot/f"initrd.img-{RELEASE}"]).split()[0]
    with (boot/f"uInitrd-{RELEASE}").open("rb") as f:
        f.seek(64)
        import hashlib
        assert hashlib.file_digest(f,"sha256").hexdigest()==payload
    assert not (root/"var/lib/yzd-s18/dpkg-audit.txt").read_text()
    return {"status":"offline-validation-passed","hardware_acceptance":"pending","identity":identity,
            "initramfs_sha256":payload,"packages":(root/"var/lib/yzd-s18/packages.tsv").read_text().splitlines()}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=("kernel","root","partitions"))
    p.add_argument("path",type=Path)
    p.add_argument("--report",type=Path)
    args=p.parse_args()
    result={"kernel":kernel,"root":rootfs,"partitions":partitions}[args.mode](args.path)
    text=json.dumps(result,indent=2)+"\n"
    if args.report:
        args.report.write_text(text)
    print(text if args.mode!="root" else "Offline rootfs validation passed; hardware acceptance pending.")

if __name__=="__main__":
    main()
