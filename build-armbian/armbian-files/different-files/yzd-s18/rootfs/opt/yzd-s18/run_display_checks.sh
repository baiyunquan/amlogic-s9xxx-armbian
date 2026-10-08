#!/usr/bin/env bash
# Run on the target after system graphics installation.
set -euo pipefail
MODE="${1:-smoke}"
case "${MODE}" in smoke|benchmark|stress) ;; *) echo 'Usage: run_display_checks.sh smoke|benchmark|stress' >&2; exit 2;; esac
python3 -c 'import json,os,subprocess; c=json.load(open("/etc/yzd-s18/image.json")); assert os.uname().release==c["kernel_release"]; assert subprocess.check_output(["findmnt","-n","-o","UUID","/"],text=True).strip()==c["root_uuid"]'
[[ -e /sys/firmware/devicetree/base/yzd-s18,display-profile ]]
systemctl is-active --quiet yzd-s18-display
unset LD_LIBRARY_PATH LD_PRELOAD VK_ICD_FILENAMES VK_DRIVER_FILES OCL_ICD_VENDORS DISPLAY WAYLAND_DISPLAY
card=''
for path in /sys/class/drm/card[0-9]*; do
    name="${path##*/}"
    [[ "$name" =~ ^card[0-9]+$ ]] || continue
    if [[ "$(readlink -f "$path/device/driver/module")" == /sys/module/aml_drm ]]; then
        card="/dev/dri/$name"
        break
    fi
done
[[ -n "$card" && -c "$card" && -c /dev/mali0 && -c /dev/dma_heap/system-uncached ]]
OUT="/var/tmp/yzd-s18-display-checks"
mkdir -p "$OUT"
if [[ "$MODE" == smoke ]]; then
    eglinfo --gbm-device "$card" > "$OUT/eglinfo.txt" 2>&1
    grep -q 'EGL vendor string: ARM' "$OUT/eglinfo.txt"
    /opt/yzd-s18/graphics_smoke gles "$card" > "$OUT/gles-pixels.txt" 2>&1
    /opt/yzd-s18/graphics_smoke vulkan > "$OUT/vulkan-device.txt" 2>&1
    vulkaninfo --summary > "$OUT/vulkan-summary.txt" 2>&1
    vulkaninfo > "$OUT/vulkan-full.txt" 2>&1
    modetest -D "$card" -c -e -p > "$OUT/modetest.txt" 2>&1
    for connector in /sys/class/drm/"${card##*/}"-HDMI-*; do
        [[ -e "$connector/status" ]] || continue
        [[ "$(cat "$connector/status")" == connected ]]
        cat "$connector/edid" > "$OUT/edid.bin"
        cat "$connector/modes" > "$OUT/modes.txt"
    done
    printf 'PASS: EGL GBM, GLES pixels, Vulkan GPU/device/queue. Reports: %s\n' "$OUT"
    exit 0
fi
printf '%s\n' "$MODE" > "$OUT/phase"
dmesg > "$OUT/dmesg-before-$MODE.txt"
stamp=$(python3 -c 'import time;print(time.monotonic())')
# A failed VT launch must never reuse a successful result from an older run.
rm -f "$OUT/glmark2-$MODE.exit" "$OUT/glmark2-$MODE.log"
vt_result=0
openvt -c 8 -s -w -- bash -c '
    mode="$1"; card="$2"; out="$3"
    set +e
    if [[ "$mode" == stress ]]; then
        timeout --signal=INT --kill-after=15s 600 \
            stdbuf -oL -eL glmark2-es2-drm --winsys-options "drm-device=$card" --swap-mode fifo --run-forever > "$out/glmark2-$mode.log" 2>&1
    else
        stdbuf -oL -eL glmark2-es2-drm --winsys-options "drm-device=$card" --swap-mode fifo > "$out/glmark2-$mode.log" 2>&1
    fi
    result=$?
    printf "%s\n" "$result" > "$out/glmark2-$mode.exit"
    exit "$result"
' run-display "$MODE" "$card" "$OUT" || vt_result=$?
[[ -f "$OUT/glmark2-$MODE.exit" ]] || { echo "VT launch produced no child result (status $vt_result)" >&2; exit 1; }
result=$(cat "$OUT/glmark2-$MODE.exit")
elapsed=$(python3 -c 'import sys,time;print(time.monotonic()-float(sys.argv[1]))' "$stamp")
if [[ "$MODE" == stress ]]; then
    [[ "$result" == 0 || "$result" == 124 ]]
    python3 -c 'import sys;assert float(sys.argv[1])>=599' "$elapsed"
    python3 /opt/yzd-s18/display_monitor.py validate-log "$OUT/glmark2-$MODE.log"
else
    [[ "$result" == 0 ]]
    python3 /opt/yzd-s18/display_monitor.py validate-log "$OUT/glmark2-$MODE.log" --full
fi
dmesg > "$OUT/dmesg-after-$MODE.txt"
python3 - "$OUT" "$MODE" <<'PY'
from pathlib import Path
import sys
sys.path.insert(0,'/opt/yzd-s18')
from display_monitor import has_kernel_fault
root=Path(sys.argv[1]);mode=sys.argv[2]
before=(root/f'dmesg-before-{mode}.txt').read_text()
after=(root/f'dmesg-after-{mode}.txt').read_text()
if not after.startswith(before):raise SystemExit('Kernel log wrapped or boot changed; recheck acceptance')
new=after[len(before):]
(root/f'dmesg-new-{mode}.txt').write_text(new)
if has_kernel_fault(new):raise SystemExit('Kernel/GPU/display failure during test')
print('New kernel log bytes:',len(new.encode()))
PY
printf 'PASS: %s, elapsed %ss, child status %s. Reports: %s\n' "$MODE" "$elapsed" "$result" "$OUT"
printf 'completed-%s\n' "$MODE" > "$OUT/phase"
