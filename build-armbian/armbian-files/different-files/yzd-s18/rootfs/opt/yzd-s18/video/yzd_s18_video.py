#!/usr/bin/env python3
"""Manual V4L2 decode and ffplay KMSDRM entry points; no polling or autoplay."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

IDENTITY=json.loads(Path('/etc/yzd-s18/image.json').read_text())
ROOT_UUID=IDENTITY['root_uuid']
RELEASE=IDENTITY['kernel_release']
MALI_SHA='c2524056ef47ed5b503615a2aa7bf133bffadcd0fd3dba236ee9778f725bf64d'
OUT=Path('/var/tmp/yzd-s18-video')
STATE=Path('/run/yzd-s18-video/play.json')
MEDIA_BIN=Path('/opt/yzd-s18/video/ffmpeg-5.1.9/bin')

def video_binary(name):
    path=MEDIA_BIN/name
    if not path.is_file() or not os.access(path,os.X_OK):
        raise RuntimeError('Compatible video binary missing: '+str(path)+'; run build_video_ffmpeg.sh')
    return str(path)

def media_info():
    ffmpeg=video_binary('ffmpeg');ffplay=video_binary('ffplay')
    decoders=run([ffmpeg,'-hide_banner','-decoders'])
    if not all(name in decoders for name in ('h264_v4l2m2m','hevc_v4l2m2m')):
        raise RuntimeError('Private FFmpeg hardware wrappers missing')
    return {'ffmpeg_path':ffmpeg,'ffplay_path':ffplay,
            'ffmpeg_version':run([ffmpeg,'-version']).splitlines()[0],
            'ffplay_version':run([ffplay,'-version']).splitlines()[0],
            'ffmpeg_sha256':sha(ffmpeg),'ffplay_sha256':sha(ffplay)}

def run(argv,timeout=20):
    return subprocess.run([str(x) for x in argv],check=True,capture_output=True,text=True,timeout=timeout).stdout.strip()

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2)+'\n');temp.replace(path)

def find_decoder(sysroot=Path('/sys'),devroot=Path('/dev')):
    found=[devroot/p.name for p in (sysroot/'class/video4linux').glob('video*')
           if (p/'name').read_text().strip()=='aml-vcodec-dec']
    if len(found)!=1:raise RuntimeError('Exactly one aml-vcodec-dec required; v4lvideo is not a decoder')
    return found[0]

def find_card():
    found=[Path('/dev/dri')/p.name for p in Path('/sys/class/drm').glob('card[0-9]*')
           if re.fullmatch('card[0-9]+',p.name) and (p/'device/driver/module').resolve()==Path('/sys/module/aml_drm')]
    if len(found)!=1:raise RuntimeError('Exactly one vendor Meson DRM card required')
    return found[0]

def decoder_name(codec):
    names={'h264':'h264_v4l2m2m','hevc':'hevc_v4l2m2m'}
    if codec not in names:raise RuntimeError('Unsupported codec: '+codec)
    return names[codec]

def clean_env():
    env=os.environ.copy()
    for key in ('LD_LIBRARY_PATH','LD_PRELOAD','VK_ICD_FILENAMES','VK_DRIVER_FILES','DISPLAY','WAYLAND_DISPLAY'):
        env.pop(key,None)
    env['AV_LOG_FORCE_NOCOLOR']='1'
    return env

def validate_log(text,decoder,device,play=False):
    failure=re.search(r'^.*(?:Could not|Failed to|Error while|Invalid argument|No such device|Conversion failed|Error initializing).*$',text,re.I|re.M)
    if failure:raise RuntimeError(failure[0].strip())
    if decoder not in text or not re.search(r'Using device\s+'+re.escape(str(device))+r'(?:\s|$)',text):
        raise RuntimeError('Expected hardware decoder/device not confirmed in log')
    if re.search(r'Could not|Failed to|Error while|Invalid argument|No such device|Conversion failed|Error initializing',text,re.I):
        raise RuntimeError('Decoder/player reported failure; no software fallback accepted')
    if play and not re.search(r'Initialized opengles2 renderer\.',text):
        raise RuntimeError('opengles2 renderer not confirmed; software rendering forbidden')

def proc_start(pid,procroot=Path('/proc')):
    # comm may contain spaces or parentheses; fields following its final ')' start at field3.
    return (procroot/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[19]

def verify_owner(state,procroot=Path('/proc')):
    try:
        actual=(procroot/str(state['pid'])/'cmdline').read_bytes().split(b'\0')
        argv=[x.decode() for x in actual if x]
        valid=(state['boot_id']==(procroot/'sys/kernel/random/boot_id').read_text().strip()
               and state['starttime']==proc_start(state['pid'],procroot) and state['argv']==argv)
    except (OSError,KeyError,IndexError):valid=False
    if not valid:raise RuntimeError('Playback process identity changed or already exited; no signal sent')

def ready():
    if os.uname().release!=RELEASE or run(['findmnt','-n','-o','UUID','/'])!=ROOT_UUID:
        raise RuntimeError('Expected candidate USB system required')
    if not Path('/sys/firmware/devicetree/base/yzd-s18,video-profile').exists():
        raise RuntimeError('Video DTS marker missing')
    if not Path('/sys/bus/platform/devices/codec_mm/driver').exists():
        raise RuntimeError('codec_mm has not bound')
    device=find_decoder()
    if not device.is_char_device():raise RuntimeError('Decoder device is not a character node')
    expected={'multiplanar':'Y','bypass_vpp':'1','enable_drm_mode':'N'}
    params={key:(Path('/sys/module/amvdec_ports/parameters')/key).read_text().strip() for key in expected}
    if params!=expected:raise RuntimeError('Unexpected decoder parameters: '+str(params))
    backends=('ammvdec_h264_v4l','ammvdec_h265_v4l')
    if not all((Path('/sys/bus/platform/drivers')/name).exists() for name in backends):
        raise RuntimeError('V4L2 decoder backend drivers missing; load amvdec_mh264_v4l and amvdec_h265_v4l')
    return {'device':str(device),'parameters':params,'backend_drivers':list(backends)}

def check():
    result=ready()
    run(['systemctl','is-active','--quiet','yzd-s18-video'])
    card=find_card()
    if not Path('/dev/mali0').is_char_device():raise RuntimeError('Mali device missing')
    backend=Path('/usr/lib/aarch64-linux-gnu/yzd-s18/mali-r44p0/libMali.so')
    if sha(backend)!=MALI_SHA or Path('/usr/lib/aarch64-linux-gnu/libEGL.so.1').resolve()!=backend:
        raise RuntimeError('System Mali graphics entry changed')
    fw=Path('/lib/firmware/video/video_ucode.bin')
    if not fw.is_file():raise RuntimeError('Video firmware missing')
    all_info=run(['v4l2-ctl','-d',result['device'],'--all'])
    if 'Video Memory-to-Memory Multiplanar' not in all_info or 'Streaming' not in all_info:
        raise RuntimeError('Decoder lacks M2M/streaming capabilities')
    formats=run(['v4l2-ctl','-d',result['device'],'--list-formats-out'])
    if not all(x in formats for x in ('H264','HEVC')):raise RuntimeError('H264/HEVC compressed formats missing')
    media=media_info()
    connectors={p.name:{'status':(p/'status').read_text().strip(),'modes':(p/'modes').read_text().splitlines()}
                for p in Path('/sys/class/drm').glob(card.name+'-HDMI-*')}
    if not any(x['status']=='connected' for x in connectors.values()):raise RuntimeError('No connected HDMI monitor')
    result.update({'kernel':os.uname().release,'root_uuid':ROOT_UUID,'card':str(card),
        'connectors':connectors,'firmware_sha256':sha(fw),'firmware_package':
        subprocess.run(['dpkg-query','-S',str(fw)],capture_output=True,text=True).stdout.strip() or 'pre-existing unowned file',
        'ffmpeg':media['ffmpeg_version'],'media_runtime':media,
        'packages':run(['dpkg-query','-W','ffmpeg','libsdl2-2.0-0','v4l-utils']),
        'codec_mm':run(['cat','/sys/class/codec_mm/codec_mm_dump']),
        'v4l2':all_info,'compressed_formats':formats,
        'drm_state':run(['cat','/sys/kernel/debug/dri/'+card.name[4:]+'/state'])})
    return result

def sample_info(sample):
    path=Path(sample).resolve(strict=True)
    data=json.loads(run(['/usr/bin/ffprobe','-v','error','-select_streams','v:0','-show_entries',
        'stream=codec_name,profile,width,height,pix_fmt,field_order,r_frame_rate','-of','json',path]))
    if len(data['streams'])!=1:raise RuntimeError('Exactly one selected video stream required')
    info=data['streams'][0];decoder=decoder_name(info['codec_name'])
    if info['pix_fmt']!='yuv420p':raise RuntimeError('Only nonsecure 8-bit progressive sample preparation is supported')
    if info.get('field_order')!='progressive':raise RuntimeError('Only explicitly progressive samples are supported')
    return path,info,decoder

def new_report(kind):
    path=OUT/(time.strftime('%Y%m%d-%H%M%S')+'-'+kind+'-'+uuid.uuid4().hex[:6])
    path.mkdir(parents=True);return path

def decode(sample):
    state=check();path,info,decoder=sample_info(sample);out=new_report('decode')
    argv=[video_binary('ffmpeg'),'-hide_banner','-nostdin','-loglevel','verbose','-c:v',decoder,'-i',str(path),
          '-map','0:v:0','-an','-sn','-vf','format=yuv420p','-fps_mode','passthrough','-f','framemd5',str(out/'frames.md5')]
    save(out/'run.json',{'sample':str(path),'sample_sha256':sha(path),'stream':info,'check':state,'argv':argv})
    with (out/'decoder.log').open('wb') as log:
        result=subprocess.run(argv,env=clean_env(),stdout=log,stderr=log)
    summary={'exit_status':result.returncode}
    try:
        if result.returncode:raise RuntimeError('Hardware decode failed')
        validate_log((out/'decoder.log').read_text(errors='replace'),decoder,state['device'])
        frames=[line for line in (out/'frames.md5').read_text().splitlines() if line and not line.startswith('#')]
        if not frames:raise RuntimeError('No decoded frames')
        summary.update({'frames':len(frames),'result':'decoded; compare with software reference manually'})
    except Exception as exc:
        summary['error']=str(exc);raise
    finally:
        save(out/'result.json',summary);print('Reports:',out,flush=True)
    print(json.dumps(summary,indent=2))

class PlaybackInterrupted(RuntimeError):
    pass

def supervise_player(argv,env,out,previous,decoder,device):
    """The VT child owns the lock, player and restoration for their lifetime."""
    STATE.parent.mkdir(parents=True,exist_ok=True)
    with (STATE.parent/'play.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('An owned playback is already running')
        watched=(signal.SIGTERM,signal.SIGHUP,signal.SIGINT)
        original={s:signal.getsignal(s) for s in watched}
        def interrupt(signum,frame):raise PlaybackInterrupted('Supervisor interrupted')
        for s in watched:signal.signal(s,interrupt)
        proc=None;state=None;interrupted=False;mode_snapshot=None
        try:
            with (out/'player.log').open('wb') as log:
                if (out/'cancel.request').exists():raise PlaybackInterrupted('Cancelled before launch')
                proc=subprocess.Popen(argv,env=env,stdout=log,stderr=log)
                state={'pid':proc.pid,'starttime':proc_start(proc.pid),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                       'argv':argv,'report':str(out),'phase':'playing'}
                save(STATE,state)
                if 'SDL_KMSDRM_DEVICE_INDEX' in env:
                    # One snapshot during an explicitly requested playback,
                    # not a recurring monitor. SDL establishes KMS before decode.
                    def snapshot_mode():
                        try:
                            path=Path('/sys/kernel/debug/dri')/env['SDL_KMSDRM_DEVICE_INDEX']/'state'
                            (out/'drm-state-during-play.txt').write_text(path.read_text())
                            (out/'player-maps.txt').write_text(Path('/proc',str(proc.pid),'maps').read_text())
                        except OSError as exc:(out/'drm-state-during-play.txt').write_text(str(exc))
                    mode_snapshot=threading.Timer(2,snapshot_mode)
                    mode_snapshot.daemon=True;mode_snapshot.start()
                if (out/'cancel.request').exists():proc.terminate();interrupted=True
                proc.wait()
        except PlaybackInterrupted:
            interrupted=True
        finally:
            for s in watched:signal.signal(s,signal.SIG_IGN)
            try:
                if mode_snapshot is not None:mode_snapshot.cancel()
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=15)
                if state is None:state={'report':str(out)}
                if STATE.exists() and 'pid' in state:
                    requested=json.loads(STATE.read_text())
                    if requested.get('pid')==state['pid'] and requested.get('starttime')==state['starttime']:
                        state['stop_requested']=bool(requested.get('stop_requested'))
                state.update({'phase':'finished','exit_status':proc.returncode if proc is not None else None,'interrupted':interrupted})
                if 'pid' in state:save(STATE,state)
                run(['chvt',str(previous)])
            finally:
                for s,handler in original.items():signal.signal(s,handler)
        try:
            if interrupted or (out/'cancel.request').exists():
                state['result']='stopped; playback acceptance not evaluated'
            else:
                validate_log((out/'player.log').read_text(errors='replace'),decoder,device,play=True)
                allowed=(0,-signal.SIGTERM,123) if state.get('stop_requested') else (0,-signal.SIGTERM)
                if state['exit_status'] not in allowed:raise RuntimeError('Player failed: '+str(state['exit_status']))
                state['result']='player finished; visible output awaits user confirmation'
        except Exception as exc:state['error']=str(exc);save(out/'result.json',state);raise
        save(out/'result.json',state)

def play_child(out,sample,device,card,previous):
    out=Path(out).resolve()
    if out.parent!=OUT.resolve() or not (out/'run.json').is_file():raise RuntimeError('Invalid playback report directory')
    path,info,decoder=sample_info(sample)
    argv=[video_binary('ffplay'),'-hide_banner','-loglevel','verbose','-vcodec',decoder,'-an','-sn',
          '-x',str(info['width']),'-y',str(info['height']),'-fs','-autoexit','-sync','video',str(path)]
    env=clean_env();env.update({'SDL_VIDEODRIVER':'KMSDRM','SDL_RENDER_DRIVER':'opengles2',
        'SDL_OPENGL_ES_DRIVER':'1','SDL_KMSDRM_DEVICE_INDEX':Path(card).name[4:],'YZD_S18_MALI_GBM':'1'})
    supervise_player(argv,env,out,previous,decoder,device)

def play(sample):
    if os.geteuid()!=0:raise RuntimeError('Run play as root for VT/DRM master')
    state=check();path,info,decoder=sample_info(sample);out=new_report('play')
    previous=int(run(['fgconsole']))
    save(out/'run.json',{'sample':str(path),'sample_sha256':sha(path),'stream':info,'decoder':decoder,'check':state,'previous_vt':previous})
    print('Reports:',out,'; stop from another SSH session with: yzd-s18-video stop',flush=True)
    watched=(signal.SIGTERM,signal.SIGHUP,signal.SIGINT)
    original={s:signal.getsignal(s) for s in watched}
    def interrupt(signum,frame):
        (out/'cancel.request').touch()
        if STATE.exists():
            owned=json.loads(STATE.read_text())
            if owned.get('report')==str(out) and owned.get('phase')=='playing':
                try:stop()
                except (OSError,RuntimeError):pass  # Already-exited player is reaped by the VT supervisor.
        raise PlaybackInterrupted('Launcher interrupted; player stop requested')
    for s in watched:signal.signal(s,interrupt)
    proc=None
    try:
        proc=subprocess.Popen(['openvt','-c','8','-s','-w','--',sys.executable,str(Path(__file__).resolve()),
            '_play_child',str(out),str(path),state['device'],state['card'],str(previous)])
        proc.wait()
        if not (out/'result.json').exists():raise RuntimeError('VT player produced no result; see '+str(out))
        result=json.loads((out/'result.json').read_text())
        if 'error' in result:raise RuntimeError(result['error'])
        if proc.returncode:raise RuntimeError('VT player failed; see '+str(out))
        print(json.dumps(result,indent=2))
    except PlaybackInterrupted:
        if proc is not None:proc.wait(timeout=35)
        raise
    finally:
        for s,handler in original.items():signal.signal(s,handler)
        if not (out/'result.json').exists():run(['chvt',str(previous)])

def stop():
    if not STATE.exists():raise RuntimeError('No owned playback state')
    state=json.loads(STATE.read_text())
    if state.get('phase')!='playing':raise RuntimeError('No active owned playback')
    # pidfd binds signaling to this process even if the numeric PID is reused.
    fd=os.pidfd_open(state['pid'])
    try:
        verify_owner(state)
        state['stop_requested']=True
        save(STATE,state)
        signal.pidfd_send_signal(fd,signal.SIGTERM)
    finally:os.close(fd)
    print('Stop requested for owned ffplay; its VT launcher restores the previous VT.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='mode',required=True)
    for mode in ('check','stop','_ready'):sub.add_parser(mode)
    for mode in ('decode','play'):sub.add_parser(mode).add_argument('sample')
    child=sub.add_parser('_play_child')
    for name in ('out','sample','device','card'):child.add_argument(name)
    child.add_argument('previous',type=int)
    args=parser.parse_args()
    try:
        if args.mode=='check':print(json.dumps(check(),indent=2))
        elif args.mode=='_ready':print(json.dumps(ready(),indent=2))
        elif args.mode=='decode':decode(args.sample)
        elif args.mode=='play':play(args.sample)
        elif args.mode=='stop':stop()
        else:play_child(args.out,args.sample,args.device,args.card,args.previous)
        return 0
    except (OSError,RuntimeError,subprocess.SubprocessError,ValueError,KeyError) as exc:
        print('Video operation failed:',exc,file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
