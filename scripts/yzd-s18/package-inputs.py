#!/usr/bin/env python3
"""Package proven local artifacts; never read a rootfs from the USB disk."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from inputs import BASE, KERNEL, RELEASE, sha

def archive(directory, output):
    with tarfile.open(output, "w:gz", compresslevel=6) as tar:
        for file in sorted(directory.rglob("*")):
            if file.is_file() and not file.is_symlink():
                tar.add(file, arcname=str(file.relative_to(directory)), recursive=False)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--porting-dir", type=Path, required=True)
    p.add_argument("--base-image", type=Path, required=True)
    p.add_argument("--firmware", type=Path, required=True)
    p.add_argument("--vendor-bundle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    src = args.porting_dir.resolve()
    kernel = src / "output_debs/yzd-s18-peripherals"
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["sha256sum", "-c", "SHA256SUMS"], cwd=kernel, check=True, stdout=subprocess.DEVNULL)
    assert sha(args.base_image) == "c7a35424aa383bb1ff9190fa0c9492d6e7dbf426cc7bc09b7118b8e1e491476a"
    assert sha(args.firmware) == "80522fd7376bde74be185e822c314f9beddee0264279bb4538d104588f46b094"
    mali = src / "output_debs/yzd-s18/opencl/linux-gpu-mali-wayland_1.4-r44p0-202311_arm64.deb"
    assert sha(mali) == "7ad4a803d02f0e5ac9be7db4b3d7b2e69e14b3ba695d384cfc7e21086bd1a822"
    shutil.copyfile(args.base_image, out / BASE)
    with tempfile.TemporaryDirectory(prefix="yzd-package-") as tmp:
        stage = Path(tmp)
        boot = stage / "boot"
        shutil.copytree(kernel / "boot", boot)
        for f in boot.glob("uEnv*"):
            f.unlink()
        for name in ("config-" + RELEASE, "System.map", "build-manifest.txt"):
            shutil.copyfile(kernel / name, stage / name)
        shutil.copyfile(kernel / ("linux-headers_" + RELEASE + "-1_arm64.deb"), stage / "headers.deb")
        shutil.copytree(kernel / ("modules/lib/modules/" + RELEASE), stage / "modules", symlinks=True)
        for f in (stage / "modules").rglob("*"):
            if f.is_symlink():
                f.unlink()
        shutil.copytree(kernel / "usbfix-patches", stage / "patches")
        for f in kernel.glob("*.dts"):
            shutil.copyfile(f, stage / f.name)
        files = {str(f.relative_to(stage)): sha(f) for f in stage.rglob("*") if f.is_file()}
        (stage / "manifest.json").write_text(json.dumps({"kernel_release": RELEASE, "module_count": 1514, "files": files}, indent=2) + "\n")
        archive(stage, out / KERNEL)
    vendor = out / "yzd-s18-vendor-runtime.tar.gz"
    assert sha(args.vendor_bundle) == "58ba165f8a9c7ff987ce70076cd94d508700a2ab6240518ff601ef6d22e1c73e"
    shutil.copyfile(args.vendor_bundle, vendor)
    # Exact compiled source snapshots: git-listed source paths, using their
    # working-tree contents so uncommitted porting fixes are included.
    source = out / "yzd-s18-kernel-source.tar.gz"
    with tarfile.open(source, "w:gz", compresslevel=6) as tar:
        for tree in ("linux", "common_drivers"):
            root = src / ".build-workspaces/peripherals" / tree
            names = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root).split(b"\0")
            for raw in sorted(set(names)):
                if raw:
                    f = root / raw.decode()
                    if f.is_file() or f.is_symlink():
                        tar.add(f, arcname=tree + "/" + raw.decode(), recursive=False)
        for name in ("Dockerfile.builder", "build_kernel_deb.sh"):
            tar.add(src / name, arcname="build/" + name)
        for name in ("build-manifest.txt", "config-" + RELEASE, "drivers-working-tree.patch", "linux-working-tree.patch"):
            tar.add(kernel / name, arcname="build/" + name)
    assets = {f.name: sha(f) for f in sorted(out.iterdir()) if f.name in (BASE, KERNEL, vendor.name, source.name)}
    lock = {"schema_version": 1, "repository": "baiyunquan/amlogic-s9xxx-armbian",
            "release_tag": "yzd-s18-inputs-v2", "kernel_release": RELEASE,
            "base_image": BASE, "kernel_bundle": KERNEL, "vendor_bundle": vendor.name,
            "assets": assets, "asset_releases": {
                BASE: "yzd-s18-inputs-v1", vendor.name: "yzd-s18-inputs-v1",
                KERNEL: "yzd-s18-inputs-v2", source.name: "yzd-s18-inputs-v2"}}
    (out / "inputs.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    (out / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in assets.items()))
    print(out)

if __name__ == "__main__":
    main()
