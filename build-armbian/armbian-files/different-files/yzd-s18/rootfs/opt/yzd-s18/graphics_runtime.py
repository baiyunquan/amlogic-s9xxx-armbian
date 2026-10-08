#!/usr/bin/env python3
"""Recoverable system EGL/GLES/GBM aliases and Mali Vulkan ICD installation."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

MALI_SHA256 = 'c2524056ef47ed5b503615a2aa7bf133bffadcd0fd3dba236ee9778f725bf64d'
LIBDIR = 'usr/lib/aarch64-linux-gnu'
BACKEND = LIBDIR+'/yzd-s18/mali-r44p0/libMali.so'
FAMILIES = ('libEGL.so', 'libGLESv1_CM.so', 'libGLESv2.so', 'libgbm.so', 'libwayland-egl.so')
ALIASES = ('libMali.so', 'libEGL.so', 'libEGL.so.1', 'libGLESv1_CM.so',
           'libGLESv1_CM.so.1', 'libGLESv2.so', 'libGLESv2.so.2',
           'libgbm.so', 'libgbm.so.1', 'libwayland-egl.so', 'libwayland-egl.so.1')


def checksum(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run_command(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True).stdout


class RuntimeManager:
    def __init__(self, root=Path('/'), runner=run_command):
        self.root = Path(root)
        self.run = runner
        self.lib = self.root/LIBDIR
        self.backend = self.root/BACKEND
        self.originals = self.root/'usr/lib/yzd-s18/graphics-original'
        self.state = self.root/'var/lib/yzd-s18-graphics/state.json'
        self.icd = self.root/'etc/vulkan/icd.d/yzd-s18-mali.json'

    def save(self, state):
        self.state.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2)+'\n')
        temp.replace(self.state)

    def load(self):
        return json.loads(self.state.read_text()) if self.state.exists() else None

    def true_name(self, path):
        return self.run(['dpkg-divert', '--truename', str(path)]).strip()

    def icd_bytes(self):
        return (json.dumps({'file_format_version': '1.0.0', 'ICD': {
            'library_path': '/'+BACKEND, 'api_version': '1.2.200'}}, indent=2)+'\n').encode()

    def is_our_link(self, path):
        return path.is_symlink() and os.readlink(path) == str(self.backend)

    def original_matches(self, path, record):
        if 'link' in record:
            return path.is_symlink() and os.readlink(path) == record['link']
        return path.is_file() and not path.is_symlink() and checksum(path) == record['sha256']

    def status(self):
        state = self.load()
        result = {'phase': state['phase'] if state else 'not-installed'}
        if state and state['phase'] == 'active':
            result['library_sha256'] = checksum(self.backend)
            result['aliases_correct'] = all(self.is_our_link(self.lib/name) for name in ALIASES)
            result['icd_correct'] = self.icd.exists() and self.icd.read_bytes() == self.icd_bytes()
            if result['library_sha256'] != MALI_SHA256 or not result['aliases_correct'] or not result['icd_correct']:
                raise RuntimeError('active graphics installation has changed: '+str(result))
        return result

    def make_plan(self):
        paths = set()
        for family in FAMILIES:
            paths.update(self.lib.glob(family+'*'))
        for name in ALIASES:
            path = self.lib/name
            if path.exists() or path.is_symlink():
                paths.add(path)
        records = []
        for path in sorted(paths):
            if not path.is_file() and not path.is_symlink():
                raise RuntimeError('unexpected library path type: '+str(path))
            if self.true_name(path) != str(path):
                raise RuntimeError('conflicting diversion: '+str(path))
            destination = self.originals/path.relative_to(self.root)
            if destination.exists() or destination.is_symlink():
                raise RuntimeError('original backup already exists: '+str(destination))
            record = {'source': str(path), 'destination': str(destination)}
            if path.is_symlink():
                record['link'] = os.readlink(path)
            else:
                record['sha256'] = checksum(path)
            records.append(record)
        # Check absent aliases too: an existing diversion can target a path
        # whose original object has already been removed by another owner.
        for name in ALIASES:
            path = self.lib/name
            if self.true_name(path) != str(path):
                raise RuntimeError('conflicting diversion: '+str(path))
        if self.icd.is_symlink():
            raise RuntimeError('refusing to replace a symlinked ICD: '+str(self.icd))
        return {'phase': 'installing', 'library_sha256': MALI_SHA256,
                'records': records, 'aliases': list(ALIASES),
                'icd_before': base64.b64encode(self.icd.read_bytes()).decode() if self.icd.exists() else None}

    def install(self, library):
        if checksum(library) != MALI_SHA256:
            raise RuntimeError('Mali library checksum mismatch')
        state = self.load()
        if state and state['phase'] == 'active':
            return self.status()
        if state and state['phase'] != 'restored':
            self.restore()
        state = self.make_plan()  # Preflight every path before any diversion.
        self.save(state)
        try:
            self.backend.parent.mkdir(parents=True, exist_ok=True)
            if self.backend.exists() and checksum(self.backend) != MALI_SHA256:
                raise RuntimeError('versioned Mali library has changed')
            if not self.backend.exists():
                shutil.copy2(library, self.backend)
                self.backend.chmod(0o644)
            for rec in state['records']:
                Path(rec['destination']).parent.mkdir(parents=True, exist_ok=True)
                self.run(['dpkg-divert', '--local', '--rename', '--add',
                          '--divert', rec['destination'], rec['source']])
            for name in ALIASES:
                (self.lib/name).symlink_to(self.backend)
            self.icd.parent.mkdir(parents=True, exist_ok=True)
            self.icd.write_bytes(self.icd_bytes())
            self.run(['ldconfig'])
            state['phase'] = 'active'
            self.save(state)
            return self.status()
        except Exception:
            # The persisted plan lets restore recover an interrupted partial
            # install as well. Unknown later changes are never overwritten.
            self.restore()
            raise

    def restore(self):
        state = self.load()
        if not state or state['phase'] == 'restored':
            return {'phase': 'restored'}
        records = {rec['source']: rec for rec in state['records']}
        applied = {}
        for source, rec in records.items():
            actual = self.true_name(source)
            if actual not in (source, rec['destination']):
                raise RuntimeError('diversion changed since installation: '+source)
            applied[source] = actual == rec['destination']
            if applied[source] and not self.original_matches(Path(rec['destination']),rec):
                raise RuntimeError('original backup has changed: '+rec['destination'])
        # Audit the entire rollback before removing even a single managed link.
        for name in state['aliases']:
            path = self.lib/name
            if path.exists() or path.is_symlink():
                if self.is_our_link(path):
                    continue
                rec = records.get(str(path))
                if state['phase'] in ('installing','restoring') and rec and not applied[str(path)] and self.original_matches(path,rec):
                    continue  # Original never moved, or a prior restore returned it.
                raise RuntimeError('library alias changed since installation: '+str(path))
        for source, rec in records.items():
            path = Path(source)
            if applied[source] and (path.exists() or path.is_symlink()) and not self.is_our_link(path):
                raise RuntimeError('diverted original path changed: '+source)
        before = base64.b64decode(state['icd_before']) if state['icd_before'] is not None else None
        if self.icd.exists() and self.icd.read_bytes() not in (self.icd_bytes(), before):
            raise RuntimeError('ICD changed since installation')
        state['phase'] = 'restoring'
        self.save(state)
        for name in state['aliases']:
            path = self.lib/name
            if self.is_our_link(path):
                path.unlink()
        for source, rec in reversed(list(records.items())):
            if applied[source]:
                self.run(['dpkg-divert', '--local', '--rename', '--remove',
                          '--divert', rec['destination'], source])
            path = Path(source)
            if 'link' in rec:
                if not path.is_symlink() or os.readlink(path) != rec['link']:
                    raise RuntimeError('restored original link differs: '+source)
            elif checksum(path) != rec['sha256']:
                raise RuntimeError('restored original checksum differs: '+source)
        if before is None:
            if self.icd.exists():
                self.icd.unlink()
        else:
            self.icd.write_bytes(before)
        self.run(['ldconfig'])
        state['phase'] = 'restored'
        self.save(state)
        return {'phase': 'restored', 'originals_checked': len(records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check', 'install', 'restore', 'status'])
    parser.add_argument('--library', default='/opt/yzd-s18/mali-r44p0/lib/libMali.so')
    args = parser.parse_args()
    manager = RuntimeManager()
    if args.mode in ('check', 'status'):
        result = manager.status()
        if args.mode == 'check' and result['phase'] != 'active':
            if checksum(args.library) != MALI_SHA256:
                raise RuntimeError('Mali library checksum mismatch')
            result['planned_originals'] = len(manager.make_plan()['records'])
    else:
        manager.state.parent.mkdir(parents=True, exist_ok=True)
        with (manager.state.parent/'switch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = manager.install(args.library) if args.mode == 'install' else manager.restore()
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
