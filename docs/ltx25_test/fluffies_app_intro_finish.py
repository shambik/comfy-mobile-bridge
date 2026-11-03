"""Trim the bridge-rendered logo ident and mix its native effects with the theme."""
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).parent/'tumble_puffs_ep01'))
import episode_runner as bridge
OUT=ROOT/'state'/'fluffies_brand_intro_app'
native=OUT/'clips'/'B01.mp4'
theme=ROOT/'state'/'fluffies_intro'/'fluffies_intro_theme.wav'
final=OUT/'Fluffies_App_Rainbow_Intro_8s.mp4'
bridge.probe(native,192,audio=True)
filters=('[0:v]trim=end_frame=192,setpts=PTS-STARTPTS[picture];'
 '[0:a]atrim=duration=8,asetpts=PTS-STARTPTS,aresample=48000,asplit=2[native][trigger];'
 '[1:a]atrim=duration=8,asetpts=PTS-STARTPTS,volume=0.28[music];'
 '[music][trigger]sidechaincompress=threshold=0.04:ratio=3.5:attack=12:release=180[duck];'
 '[native][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st=7.86:d=0.14[mix]')
subprocess.run(['ffmpeg','-v','error','-y','-i',str(native),'-i',str(theme),
 '-filter_complex',filters,'-map','[picture]','-map','[mix]','-r','24','-frames:v','192','-t','8',
 '-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000',
 '-movflags','+faststart',str(final)],check=True)
proof=bridge.probe(final,192,audio=True)
assert proof['decoded_frames']==192 and abs(proof['duration']-8)<.001
bridge.OUT,bridge.JOURNAL,bridge.FINAL=OUT,OUT/'execution.json',final
data=bridge.read();data['master']=proof;data['audio_policy']='Preserve native LTX designed effects, mix original Fluffies theme underneath; no static title overlay'
bridge.write(data)
bridge.publish(final,192,'Fluffies - App LTX rainbow 3D intro - v3 with music.mp4')
