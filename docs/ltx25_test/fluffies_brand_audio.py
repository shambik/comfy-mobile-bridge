"""Original instrumental logo sting with synchronized plush pops and airy whooshes."""
import json
import wave
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'fluffies_brand_intro'
OUT.mkdir(exist_ok=True)
SR=48000
with wave.open(str(ROOT/'state'/'fluffies_intro'/'fluffies_intro_theme.wav'),'rb') as source:
    music=np.frombuffer(source.readframes(source.getnframes()),dtype='<i2').astype(np.float32).reshape(-1,2)/32768
sound=music*.62
rng=np.random.default_rng(1024250)
cues=[]
def add(at,kind,level=.2,pan=0):
    duration=.6 if kind=='whoosh' else .34
    t=np.arange(round(duration*SR),dtype=np.float32)/SR
    if kind=='whoosh':
        raw=rng.normal(size=len(t)).astype(np.float32)
        signal=np.convolve(raw,np.ones(13,dtype=np.float32)/13,'same')*np.sin(np.pi*t/duration)**2
    else:
        phase=2*np.pi*(140*t+65*(1-np.exp(-12*t))/12)
        signal=np.sin(phase+1.2*np.sin(2*np.pi*15*t)*np.exp(-10*t))*np.exp(-13*t)
    signal*=np.minimum(t/.008,1)*level
    start=round(at*SR);n=min(len(signal),len(sound)-start)
    sound[start:start+n,0]+=signal[:n]*np.sqrt((1-pan)/2)
    sound[start:start+n,1]+=signal[:n]*np.sqrt((1+pan)/2)
    cues.append(dict(at=at,kind=kind,level=level,pan=pan))
for args in [(.08,'pop',.12,-.6),(.26,'pop',.12,.6),(.4,'pop',.14,0),(.48,'whoosh',.27,0),(1.12,'pop',.25,0),(1.43,'pop',.13,0),(2.42,'whoosh',.12,.2)]:
    add(*args)
sound*=.82/max(float(np.max(np.abs(sound))),.001)
sound[-3600:]*=np.linspace(1,0,3600)[:,None]
with wave.open(str(OUT/'Fluffies_Brand_Sting.wav'),'wb') as target:
    target.setparams((2,2,SR,len(sound),'NONE','not compressed'))
    target.writeframes((np.clip(sound,-1,1)*32767).astype('<i2').tobytes())
(OUT/'audio_cues.json').write_text(json.dumps(dict(duration=8,bpm=120,origin='Original composition and synthesized non-vocal effects; no external samples',cues=cues),indent=2))
print(OUT/'Fluffies_Brand_Sting.wav')
