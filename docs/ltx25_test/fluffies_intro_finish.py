"""Original instrumental intro theme, deterministic title, native character sounds."""
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).parent/'tumble_puffs_ep01'))
import episode_runner as bridge

OUT=ROOT/'state'/'fluffies_intro'
native=OUT/'clips'/'I00.mp4'
assert native.exists(),'Wait for the intro render to finish.'
bridge.probe(native,192,audio=True)
font=(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'COOPBL.TTF').as_posix().replace(':','\\:')
alpha="clip((t-0.55)/0.2,0,1)"
y="26-10*exp(-4*max(t-0.55,0))*sin(12*max(t-0.55,0))"
title=(f"drawtext=fontfile='{font}':text='Fluffies':fontsize=124:fontcolor=0x238A91:bordercolor=0x238A91:borderw=12:"
       f"x=(w-text_w)/2+4:y='{y}+6':alpha='{alpha}',"
       f"drawtext=fontfile='{font}':text='Fluffies':fontsize=124:fontcolor=0xFFD469:bordercolor=white:borderw=6:"
       f"x=(w-text_w)/2:y='{y}':alpha='{alpha}'")
video=f'[0:v]trim=end_frame=192,setpts=PTS-STARTPTS,{title}[picture]'
audio=('[0:a]atrim=duration=8,asetpts=PTS-STARTPTS,aresample=48000,asplit=2[voice][trigger];'
       '[1:a]atrim=duration=8,asetpts=PTS-STARTPTS,volume=0.35[music];'
       '[music][trigger]sidechaincompress=threshold=0.04:ratio=4:attack=12:release=180[duck];'
       '[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9[mix]')
filters=OUT/'intro_filters.txt'
filters.write_text(video+';'+audio,encoding='utf-8')
final=OUT/'Fluffies_Intro_8s.mp4'
subprocess.run(['ffmpeg','-v','error','-y','-i',str(native),'-i',str(OUT/'fluffies_intro_theme.wav'),
 '-filter_complex_script',str(filters),'-map','[picture]','-map','[mix]','-r','24','-frames:v','192',
 '-t','8','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
 '-ar','48000','-movflags','+faststart',str(final)],check=True)
# Also retain a titled/native-sound-only source for the complete episode mix.
titled=OUT/'Fluffies_Intro_titled_native.mp4'
subprocess.run(['ffmpeg','-v','error','-y','-i',str(native),'-vf',f'trim=end_frame=192,setpts=PTS-STARTPTS,{title}',
 '-r','24','-frames:v','192','-t','8','-c:v','libx264','-preset','fast','-crf','17','-pix_fmt','yuv420p',
 '-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',str(titled)],check=True)
proof=bridge.probe(final,192,audio=True)
assert proof['decoded_frames']==192 and abs(proof['duration']-8)<.001
bridge.probe(titled,192,audio=True)
bridge.OUT,bridge.JOURNAL,bridge.FINAL=OUT,OUT/'execution.json',final
data=bridge.read();data['master']=proof;bridge.write(data)
bridge.publish(final,192,'Fluffies - Series Intro - 8 seconds.mp4')
