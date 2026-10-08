#!/usr/bin/env bash
set -euo pipefail
RUNTIME=/opt/yzd-s18/mali-r44p0
[[ -c /dev/mali0 ]] || { echo 'No /dev/mali0; boot the Khadas candidate first' >&2; exit 1; }
python3 -c 'import json,os,subprocess; c=json.load(open("/etc/yzd-s18/image.json")); assert os.uname().release==c["kernel_release"]; assert subprocess.check_output(["findmnt","-n","-o","UUID","/"],text=True).strip()==c["root_uuid"]'
export OCL_ICD_VENDORS="${RUNTIME}/vendors"
export LD_LIBRARY_PATH="${RUNTIME}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec /opt/yzd-s18/opencl_smoke "${@}"
