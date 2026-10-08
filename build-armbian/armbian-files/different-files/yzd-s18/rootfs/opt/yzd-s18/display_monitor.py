#!/usr/bin/env python3
"""Fresh SSH sampling and strict classification of display acceptance logs."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time


def inspect_glmark(text, full=False):
    renderer = re.search(r'GL_RENDERER:\s*([^\n]+)', text)
    if not renderer or not re.search(r'Mali[- ]G31', renderer[1]):
        raise RuntimeError('Mali-G31 renderer required; software fallback forbidden')
    if re.search(r'Error:|Failed to|failed to|eglInitialize failed', text):
        raise RuntimeError('graphics benchmark failed')
    surface = re.search(r'Surface Size:\s*(\d+)x(\d+)', text)
    fps = [int(n) for n in re.findall(r'FPS:\s*(\d+)', text)]
    scores = [int(n) for n in re.findall(r'glmark2 Score:\s*(\d+)', text)]
    if not fps:
        raise RuntimeError('no completed rendering scene')
    if full and (not scores or scores[-1] <= 0):
        raise RuntimeError('completed benchmark score missing')
    return {'renderer': renderer[1].strip(), 'surface': [int(surface[1]), int(surface[2])] if surface else None,
            'scenes': len(fps), 'minimum_fps': min(fps), 'maximum_fps': max(fps),
            'score': scores[-1] if scores else None}


def has_kernel_fault(text):
    return bool(re.search(r'Kernel panic|BUG: workqueue lockup|SError Interrupt|Unable to handle kernel|'
        r'GPU (?:fault|reset|soft-reset|hang)|Resetting GPU|error detected from slot \d+, job status|'
        r'(?:flip_done|hw_done|cleanup_done|vblank|commit)[^\n]*timed? out', text, re.I))


PROBE = r'''
import glob,json,os,platform,subprocess
def read(p):
    with open(p) as f:return f.read().strip()
temps={}
for p in glob.glob('/sys/class/thermal/thermal_zone*'):
    try:temps[read(p+'/type')]=int(read(p+'/temp'))/1000
    except (OSError,ValueError):pass
mem={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in open('/proc/meminfo')) if k in ('MemTotal','MemAvailable','CmaTotal','CmaFree')}
phasefile='/var/tmp/yzd-s18-display-checks/phase'
print(json.dumps({'release':platform.release(),'boot_id':read('/proc/sys/kernel/random/boot_id'),
 'phase':read(phasefile) if os.path.exists(phasefile) else 'idle',
 'root_uuid':subprocess.check_output(['findmnt','-n','-o','UUID','/'],text=True).strip(),
 'online':read('/sys/devices/system/cpu/online'),'temperature_c':temps,'memory_kb':mem,
 'link':{'speed':int(read('/sys/class/net/eth0/speed')),'duplex':read('/sys/class/net/eth0/duplex'),
 'carrier':int(read('/sys/class/net/eth0/carrier'))}}))
'''


def monitor(host, duration, interval, until_stress_complete=False):
    started = time.monotonic()
    deadline = started+duration
    expected_boot = None
    samples = []
    saw_stress = False
    completed = False
    while time.monotonic() < deadline:
        call_started = time.monotonic()
        proc = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=3',host,
            'python3 -c '+shlex.quote(PROBE)], capture_output=True, text=True, timeout=10)
        if proc.returncode:
            raise RuntimeError('SSH sampling failed: '+proc.stderr)
        data = json.loads(proc.stdout)
        data['elapsed_seconds'] = round(time.monotonic()-started, 3)
        data['ssh_seconds'] = round(time.monotonic()-call_started, 3)
        if expected_boot is None:
            expected_boot = data['boot_id']
        if (data['boot_id'] != expected_boot or data['release'] != '5.15.137-yzd-s18' or
                data['root_uuid'] != 'b6aa22de-55fc-4de1-b172-329b4f1076dd' or data['online'] != '0-3' or
                data['link'] != {'speed':1000,'duplex':'full','carrier':1}):
            raise RuntimeError('boot/root/CPU/network changed: '+json.dumps(data))
        print(json.dumps(data), flush=True)
        samples.append(data)
        saw_stress = saw_stress or data['phase'] == 'stress'
        if until_stress_complete and saw_stress and data['phase'] == 'completed-stress':
            completed = True
            break
        time.sleep(max(0, min(interval-(time.monotonic()-call_started), deadline-time.monotonic())))
    if until_stress_complete and not completed:
        raise RuntimeError('current stress completion was not observed')
    print(json.dumps({'summary': {'samples': len(samples), 'elapsed_seconds': round(time.monotonic()-started,3),
        'ssh_max_seconds': max(x['ssh_seconds'] for x in samples), 'boot_id': expected_boot,
        'phase_samples': {phase:sum(x['phase']==phase for x in samples) for phase in {x['phase'] for x in samples}},
        'maximum_temperature_c': {name:max(x['temperature_c'][name] for x in samples if name in x['temperature_c'])
            for name in {n for x in samples for n in x['temperature_c']}}}}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    log = sub.add_parser('validate-log')
    log.add_argument('path', type=Path)
    log.add_argument('--full', action='store_true')
    watch = sub.add_parser('monitor')
    watch.add_argument('--host', default='root@192.168.1.193')
    watch.add_argument('--duration', type=int, default=620)
    watch.add_argument('--interval', type=int, default=15)
    watch.add_argument('--until-stress-complete', action='store_true')
    args = parser.parse_args()
    if args.mode == 'validate-log':
        print(json.dumps(inspect_glmark(args.path.read_text(), args.full), indent=2))
    else:
        if args.duration < 1 or args.interval < 1:
            parser.error('duration/interval must be positive')
        monitor(args.host, args.duration, args.interval, args.until_stress_complete)


if __name__ == '__main__':
    main()
