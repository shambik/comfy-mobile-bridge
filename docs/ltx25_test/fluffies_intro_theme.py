"""Original four-bar instrumental Fluffies signature; no voice or samples."""
import wave
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/"state"/"fluffies_intro"
SR=48000
track=np.zeros((SR*8,2),dtype=np.float32)


def pluck(midi,at,length=.4,gain=.12,pan=0):
    t=np.arange(int(length*SR),dtype=np.float32)/SR
    f=440*2**((midi-69)/12)
    signal=(np.sin(2*np.pi*f*t)*np.exp(-t/.22)+.23*np.sin(2*np.pi*2.76*f*t)*np.exp(-t/.045))
    signal*=np.minimum(t/.004,1)*np.minimum((length-t)/.02,1)*gain
    start=int(at*SR);n=min(len(signal),len(track)-start)
    track[start:start+n,0]+=signal[:n]*np.sqrt((1-pan)/2)
    track[start:start+n,1]+=signal[:n]*np.sqrt((1+pan)/2)


# A four-bar C-major signature, with a melodic answer and a clean final tonic.
for midi,at,length in [(76,0,.35),(79,.5,.35),(81,1,.35),(79,1.5,.45),
                       (76,2.25,.3),(74,2.75,.3),(72,3.25,.55),
                       (76,4,.35),(79,4.5,.35),(84,5,.6),(81,5.75,.3),
                       (79,6.25,.3),(74,6.75,.3),(72,7.25,.7)]:
    pluck(midi,at,length,.13,.1)
for bar,chord in enumerate([(48,52,55),(53,57,60),(55,59,62),(48,52,55)]):
    for beat in range(4):
        pluck(chord[0]-12,bar*2+beat*.5,.28,.085,-.05)
        if beat%2:
            for index,midi in enumerate(chord):
                pluck(midi+12,bar*2+beat*.5+index*.015,.18,.045,(index-1)*.3)
for midi in [60,64,67,72]:
    pluck(midi,7.25,.7,.07,0)
track*=.65/max(float(np.max(np.abs(track))),.001)
track[:2400]*=np.linspace(0,1,2400)[:,None]
track[-4800:]*=np.linspace(1,0,4800)[:,None]
with wave.open(str(OUT/'fluffies_intro_theme.wav'),'wb') as wav:
    wav.setparams((2,2,SR,len(track),'NONE','not compressed'))
    wav.writeframes((np.clip(track,-1,1)*32767).astype('<i2').tobytes())

