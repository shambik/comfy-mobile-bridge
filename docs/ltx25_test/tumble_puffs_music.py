"""An original four-bar mallet/plucked-string cartoon cue, composed locally."""
import argparse
import json
import math
import re
import subprocess
import wave
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'tumble_puffs'
RATE=48000

def command(args,log=None):
    r=subprocess.run(args,capture_output=True)
    if log:(OUT/log).write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace')[-4000:])
    return r

def midi_frequency(note):return 440*2**((note-69)/12)

def compose(length,stem):
    count=int(round(length*RATE));audio=np.zeros((count,2),dtype=np.float64);beat=length/16
    notes=[]
    def note(midi,start,duration,gain,voice,pan=0):
        start=int(round(start*RATE));n=min(int(duration*RATE),count-start)
        if n<=0:return
        t=np.arange(n)/RATE;f=midi_frequency(midi)
        attack=1-np.exp(-t/.003)
        if voice=='mallet':
            signal=(np.sin(2*np.pi*f*t)*np.exp(-t/.34)+.23*np.sin(2*np.pi*f*2.756*t)*np.exp(-t/.17)+.09*np.sin(2*np.pi*f*5.404*t)*np.exp(-t/.08))*attack
        else:
            signal=sum(np.sin(2*np.pi*f*k*t)/(k**1.55)*np.exp(-t*(3.5+k)) for k in range(1,9))*attack
        tail=min(n,int(.025*RATE));signal[-tail:]*=np.linspace(1,0,tail)
        signal*=gain
        audio[start:start+n,0]+=signal*math.sqrt((1-pan)/2)
        audio[start:start+n,1]+=signal*math.sqrt((1+pan)/2)
        notes.append({'midi':midi,'start_seconds':start/RATE,'duration_seconds':n/RATE,'voice':voice,'gain':gain,'pan':pan})
    # An original C-major four-bar phrase; no recordings or copied tunes.
    melody=[(0,84,.65),(1,88,.65),(2,91,.65),(3,88,.65),
            (4,89,.55),(4.5,93,.4),(5.5,91,.55),(6.5,88,.65),
            (8,86,.65),(9,89,.65),(10,93,.55),(11,91,.55),
            (12,88,.65),(13,91,.55),(14,86,.45),(15,84,1)]
    for i,(when,pitch,hold) in enumerate(melody):note(pitch,when*beat,hold*beat+.18,.22,'mallet',-.18 if i%2 else .18)
    chords=[(48,[60,64,67]),(53,[60,65,69]),(55,[59,62,67]),(48,[60,64,67])]
    for bar,(bass,chord) in enumerate(chords):
        for b in (0,2):note(bass,(bar*4+b)*beat,.55,.22,'pluck',-.12)
        for b in (1,3):
            for j,pitch in enumerate(chord):note(pitch,(bar*4+b)*beat+j*.008,.32,.105,'pluck',.15)
    # Small, measured accents around the breath/gust and the final reaction.
    for b in (6,6.5,7):note(96 if b!=6.5 else 98,b*beat,.18,.045,'mallet',.25)
    audio*=np.minimum(np.arange(count)/(RATE*.045),1)[:,None]
    fade=int(min(.35,length/8)*RATE);audio[-fade:]*=np.linspace(1,0,fade)[:,None]
    peak=np.abs(audio).max()
    if peak>0:audio*=.72/peak
    dest=OUT/(stem+'_music.wav')
    with wave.open(str(dest),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(RATE);w.writeframes((audio*32767).astype('<i2').tobytes())
    (OUT/(stem+'_score.json')).write_text(json.dumps({'composer':'Original locally synthesized Tumble Puffs four-bar cue','sample_rate':RATE,'duration':length,'tempo_bpm':60/beat,'notes':notes},indent=2))
    return dest

def mean_volume(path):
    r=command(['ffmpeg','-hide_banner','-i',str(path),'-vn','-af','volumedetect','-f','null','-'])
    text=r.stderr.decode(errors='replace');match=re.findall(r'mean_volume: ([\-\d.]+) dB',text)
    return float(match[-1]) if match else -90

def mix(key):
    source=OUT/(key+'.mp4')
    data=json.loads(command(['ffprobe','-v','error','-show_format','-of','json',str(source)]).stdout)
    length=float(data['format']['duration']);music=compose(length,key)
    native_rms=mean_volume(source);music_rms=mean_volume(music)
    native_gain=min(12,-23-native_rms);music_gain=-24-music_rms
    filters=(f'[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={native_gain:.5f}dB[fx];'
             f'[1:a]volume={music_gain:.5f}dB[music];'
             f'[fx][music]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json[a]')
    output=OUT/(key+'_with_music.mp4')
    command(['ffmpeg','-hide_banner','-y','-i',str(source),'-i',str(music),'-filter_complex',filters,'-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','-shortest',str(output)],key+'-mix.log')
    (OUT/(key+'_mix.json')).write_text(json.dumps({'source':str(source),'music':str(music),'output':str(output),'native_mean_db':native_rms,'music_mean_db':music_rms,'native_gain_db':native_gain,'music_gain_db':music_gain,'loudness_target_lufs':-16,'video':'stream copied, no picture re-encode','music_duration':length},indent=2))
    print(json.dumps({'music':str(music),'output':str(output),'duration':length}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--key',default='gag_02_pinwheel');a=p.parse_args();mix(a.key)
