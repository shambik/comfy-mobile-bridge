"""Original instrumental score for The Wobbly Surprise, synthesized without samples.

Run in the bundled media Python with numpy. The chosen opener's ten seconds
remain silent in this underscore so its existing soundtrack stays intact.
"""
import json
import wave
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state/fluffies_ep02_carnival'
SR=48000
track=np.zeros((120*SR,2),dtype=np.float32)
rng=np.random.default_rng(1025000)
events=[]


def place(sound,at,gain,pan=0):
    start=round(at*SR)
    n=min(len(sound),len(track)-start)
    if start<0 or n<=0:
        return
    track[start:start+n,0]+=sound[:n]*gain*np.sqrt((1-pan)/2)
    track[start:start+n,1]+=sound[:n]*gain*np.sqrt((1+pan)/2)


def note(midi,at,length=.3,gain=.06,voice='pizz',pan=0):
    t=np.arange(round(length*SR),dtype=np.float32)/SR
    frequency=440*2**((midi-69)/12)
    sound=np.zeros_like(t)
    if voice=='pizz':
        for h in range(1,12):
            sound+=np.sin(2*np.pi*h*frequency*t)*np.exp(-t/(.12/(1+.1*h)))/h**1.65
    elif voice=='bass':
        sound=(np.sin(2*np.pi*frequency*t)+.2*np.sin(4*np.pi*frequency*t))*np.exp(-t/.21)
    elif voice=='flute':
        phase=2*np.pi*frequency*t+.018*np.sin(2*np.pi*4.6*t)
        sound=np.sin(phase)+.1*np.sin(phase*2)+.035*np.sin(phase*3)
        sound*=np.minimum(t/.04,1)*np.minimum((length-t)/.09,1)
    elif voice=='clarinet':
        phase=2*np.pi*frequency*t+.008*np.sin(2*np.pi*5*t)
        sound=np.sin(phase)+.23*np.sin(phase*3)+.08*np.sin(phase*5)
        sound*=np.minimum(t/.025,1)*np.minimum((length-t)/.07,1)
    else:
        sound=(np.sin(2*np.pi*frequency*t)*np.exp(-t/.23)
               +.14*np.sin(2*np.pi*2.76*frequency*t)*np.exp(-t/.045))
    sound*=np.minimum(t/.003,1)*np.minimum((length-t)/.012,1)
    place(sound,at,gain,pan)
    events.append(dict(at=at,midi=midi,length=length,voice=voice))


def brush(at,gain=.01):
    t=np.arange(round(.08*SR),dtype=np.float32)/SR
    noise=rng.normal(0,.4,len(t)).astype(np.float32)
    sound=np.diff(noise,prepend=0)*np.exp(-t/.016)*np.minimum(t/.001,1)
    place(sound,at,gain,.3)


major=[(48,52,55),(53,57,60),(57,60,64),(55,59,62),
       (48,52,55),(53,57,60),(50,53,57),(55,59,62)]
comic=[(57,60,64),(50,53,57),(55,59,62),(48,52,55)]
melodies=[[(76,0),(79,.5),(81,1.25)],[(77,.25),(76,.75),(74,1.25)],
          [(79,0),(84,.75),(81,1.5)],[(74,0),(76,.5),(72,1.25)]]
for bar in range(55):
    at=10+bar*2
    bridge=42.5<=at<77.5
    warm=100.5<=at<112.5
    celebrate=at>=112.5
    energy=.64 if bridge else .53 if warm else .88 if celebrate else .75
    chord=comic[bar%4] if bridge else major[bar%8]
    for beat in range(4):
        when=at+beat*.5
        if beat in [0,2]:
            note(chord[0]-12+(7 if beat==2 else 0),when,.36,.11*energy,'bass',-.05)
        if not warm or beat in [1,3]:
            for index,pitch in enumerate(chord):
                note(pitch+12,when+.012*index,.24,.035*energy,'pizz',(index-1)*.28)
        if beat%2 or celebrate:
            brush(when+.25,.016*energy)
    if bar%2==0 and at<116:
        motif=melodies[(bar//2)%len(melodies)]
        for index,(pitch,offset) in enumerate(motif):
            if warm and index==1:
                continue
            note(pitch-(12 if bridge else 0),at+offset,.34 if bridge else .43,
                 .065*energy,'clarinet' if bridge else 'flute',.1)
    if bar%8==7 and at<112:
        note(72,at+1.25,.48,.04,'wood',-.1)

# Score transitions are musical accents only; native video owns action effects.
for at in [42.5,77.5,93.5,112.5]:
    for pitch in [60,64,67]:
        note(pitch,at,.6,.035,'wood',0)
for midi,at,length in [(79,116,.45),(76,116.75,.45),(74,117.5,.45),(72,118.25,1.5)]:
    note(midi,at,length,.06,'wood',.1)
for pitch in [48,60,64,67]:
    note(pitch,118.25,1.65,.035,'flute',0)
track*=.55/max(float(np.max(np.abs(track))),.001)
track[10*SR:10*SR+4800]*=np.linspace(0,1,4800)[:,None]
track[-24000:]*=np.linspace(1,0,24000)[:,None]
with wave.open(str(OUT/'wobbly_original_score_120s.wav'),'wb') as stream:
    stream.setparams((2,2,SR,len(track),'NONE','not compressed'))
    stream.writeframes((np.clip(track,-1,1)*32767).astype('<i2').tobytes())
(OUT/'score_manifest.json').write_text(json.dumps(dict(
    title='The Wobbly Surprise — original instrumental underscore',duration=120,bpm=120,
    source='Original synthesized composition, no external recordings or samples',
    opener_policy='0–10 seconds silent here; retain the selected opener soundtrack',
    sections=[dict(start=10,end=42.5,mood='conspiratorial party preparations'),
              dict(start=42.5,end=77.5,mood='comic bridge and ribbon complications'),
              dict(start=77.5,end=93.5,mood='friends gather and anticipation builds'),
              dict(start=93.5,end=100.5,mood='bright surprise reveal'),
              dict(start=100.5,end=112.5,mood='warm caring icing-nose punchline'),
              dict(start=112.5,end=120,mood='shared bouncy celebration and cadence')],
    events=events),indent=2),encoding='utf-8')
print(json.dumps(dict(score=str(OUT/'wobbly_original_score_120s.wav'),duration=120)))
