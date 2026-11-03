"""Original 120 BPM instrumental cartoon score. No samples or voice synthesis.

Run with a project/bundled Python containing numpy. Separate music and foley
stems remain available for revisions. This is composed for the frozen edit.
"""
import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'state' / 'tumble_puffs_ep01'
SR, LENGTH = 48000, 120
RNG = np.random.default_rng(1024101)
music = np.zeros((SR * LENGTH, 2), dtype=np.float32)
foley = np.zeros_like(music)
events = []


def add(track, signal, at, gain=1., pan=0.):
    begin = round(at * SR)
    if begin < 0 or begin >= len(track):
        return
    size = min(len(signal), len(track) - begin)
    signal = signal[:size] * gain
    track[begin:begin+size, 0] += signal * np.sqrt((1 - pan) / 2)
    track[begin:begin+size, 1] += signal * np.sqrt((1 + pan) / 2)


def hz(midi):
    return 440 * 2 ** ((midi - 69) / 12)


def note(midi, duration, voice='mallet'):
    t = np.arange(round((duration + .22) * SR), dtype=np.float32) / SR
    f = hz(midi)
    attack = np.minimum(t / .006, 1)
    release = np.minimum(np.maximum(duration + .2 - t, 0) / .2, 1)
    if voice == 'mallet':
        sound = (np.sin(2*np.pi*f*t)*np.exp(-t/ .32) +
                 .28*np.sin(2*np.pi*f*2.76*t)*np.exp(-t/.075) +
                 .11*np.sin(2*np.pi*f*5.4*t)*np.exp(-t/.035))
    elif voice == 'pluck':
        sound = sum(np.sin(2*np.pi*f*k*t)*np.exp(-t/(.32/k)) / k**1.65 for k in range(1, 7))
    elif voice == 'reed':
        env = np.minimum(t/.035, 1) * np.exp(-t/1.4)
        sound = env*(np.sin(2*np.pi*f*t + .005*np.sin(2*np.pi*4.5*t)) + .15*np.sin(6*np.pi*f*t))
    elif voice == 'bass':
        sound = (np.sin(2*np.pi*f*t) + .15*np.sin(4*np.pi*f*t)) * np.exp(-t/.22)
    else:  # airy, quiet pad made of sines, with no formant or voice model
        sound = np.sin(2*np.pi*f*t) * np.minimum(t/.18, 1)
    return (sound * attack * release).astype(np.float32)


def play(midi, at, duration=.22, voice='mallet', gain=.1, pan=0):
    add(music, note(midi, duration, voice), at, gain, pan)


def wood(at, gain=.055, pan=0.):
    t = np.arange(int(.085*SR), dtype=np.float32)/SR
    signal = (np.sin(2*np.pi*870*t)+.3*np.sin(2*np.pi*1390*t))*np.exp(-t/.012)
    add(music, signal, at, gain, pan)


# C major, with warm vi/ii detours and a clear dominant-to-tonic ending.
chords = [(48,52,55,59), (53,57,60,64), (50,53,57,60), (55,59,62,65),
          (57,60,64,67), (53,57,60,64), (55,59,62,65), (48,52,55,60)]
pentatonic = [72,74,76,79,81,84]
themes = [
    [0,2,3,2,1,0,2,3], [2,3,4,3,2,1,0,1],
    [3,2,1,0,1,2,4,3], [4,3,2,1,0,2,1,0],
]
for bar in range(60):
    at = bar * 2.
    section = 0 if at < 28 else 1 if at < 59 else 2 if at < 89 else 3 if at < 107 else 4
    chord = chords[(bar // 2 + (2 if section == 2 else 0)) % len(chords)]
    energy = [.64,.76,.9,.61,.78][section]
    # Alternating bass and short, widely spaced plucked chord answers.
    for beat in [0,2]:
        play(chord[0]-12, at+beat*.5, .28, 'bass', .11*energy, -.06)
    for beat in [1,3]:
        for index, pitch in enumerate(chord[:3]):
            play(pitch+12, at+beat*.5+index*.013, .14, 'pluck', .032*energy, (index-1)*.25)
    if section in [1,2,4]:
        for off in [0,.5,1,1.5]:
            wood(at+off, .028*energy, -.3 if off in [0,1] else .3)
    else:
        wood(at+.5, .018, -.25)
        wood(at+1.5, .018, .25)
    # Four-bar phrases breathe: the fourth bar leaves room for reactions.
    phrase = themes[(bar//4) % len(themes)]
    pattern = [0,.5,.75,1.5] if section != 2 else [0,.25,.5,.75,1,1.25,1.5]
    if bar % 4 == 3:
        pattern = [0,.5]
    if section == 3:
        pattern = [0,1]
    for index, offset in enumerate(pattern):
        pitch = pentatonic[phrase[(bar % 4 * 2 + index) % 8]]
        voice = 'reed' if section == 3 else 'mallet'
        play(pitch, at+offset, .2 if section != 3 else .48, voice, .061*energy, .15)
    if section == 3:
        for pitch in chord[:3]:
            play(pitch+12, at, 1.55, 'pad', .009, -.2)

# Character signatures enter near the opening of individual reaction shots.
spec = json.loads((OUT/'manifest.json').read_text())
for shot in spec['shots']:
    if len(shot['cast']) != 1:
        continue
    who = shot['cast'][0]
    motif, voice, pan = {'Pip':([76,79,84,79],'mallet',-.2),
                         'Momo':([48,55,52],'bass',0),
                         'Tiki':([79,81,79,76],'reed',.2)}[who]
    for index, pitch in enumerate(motif):
        play(pitch, shot['start']+.25+index*.25, .16, voice, .045, pan)

# Leave musical space at comic realizations; never remove the continuous bed.
for start, end in [(9.2,10.8),(25.3,27.5),(43.3,45.5),(56,58.7),(79.8,82.5),(109.4,111.3),(115.1,116.5)]:
    a,b = int(start*SR),int(end*SR)
    curve = np.ones(b-a, dtype=np.float32)*.43
    ramp = min(int(.12*SR),len(curve)//2)
    curve[:ramp]=np.linspace(1,.43,ramp)
    curve[-ramp:]=np.linspace(.43,1,ramp)
    music[a:b] *= curve[:,None]


def effect(at, kind, gain=.11, pan=0):
    duration = {'boing':.45,'tap':.1,'rustle':.48,'roll':.8,'flutter':1.3,'twinkle':.7}[kind]
    t = np.arange(int(duration*SR),dtype=np.float32)/SR
    if kind == 'boing':
        phase = 2*np.pi*(165*t + 60*(1-np.exp(-8*t))/8)
        sound = np.sin(phase+1.8*np.sin(2*np.pi*13*t)*np.exp(-8*t))*np.exp(-9*t)
    elif kind == 'tap':
        sound = (np.sin(2*np.pi*230*t)+.2*RNG.normal(size=len(t)))*np.exp(-55*t)
    elif kind in {'rustle','roll','flutter'}:
        noise = RNG.normal(size=len(t)).astype(np.float32)
        # A small moving-average filter softens the noise into leaves/soft grass.
        filtered = np.convolve(noise,np.ones(21,dtype=np.float32)/21,'same')
        envelope = np.sin(np.pi*t/duration)**2
        if kind == 'flutter':
            envelope *= (.5+.5*np.sin(2*np.pi*16*t))**2
        elif kind == 'roll':
            envelope *= .65+.35*np.sin(2*np.pi*9*t)
        sound = filtered*envelope
    else:
        sound = sum(np.sin(2*np.pi*f*t)*np.exp(-t/.18) for f in [1568,2093,2637])*.3
    fade = np.minimum(t/.004,1)*np.minimum((duration-t)/.015,1)
    add(foley,np.asarray(sound*fade,dtype=np.float32),at,gain,pan)
    events.append(dict(at=at,kind=kind,gain=gain,pan=pan))


# Designed non-vocal accents. Preserve these cue times for user-requested edits.
for at,kind,pan in [
 (3.0,'rustle',.15),(7.5,'tap',-.2),(9.0,'roll',.3),(13,'tap',0),(14,'roll',.3),
 (18.5,'rustle',.2),(20,'tap',0),(23.5,'rustle',.15),(25,'roll',.35),
 (30.5,'twinkle',-.2),(35,'rustle',-.2),(36.6,'boing',0),(38.2,'roll',.3),
 (41,'twinkle',0),(48,'rustle',-.2),(54.8,'boing',.2),(57,'tap',.3),
 (60.5,'roll',.2),(65.5,'rustle',-.3),(67.2,'roll',.2),
 (71.5,'rustle',.2),(73.7,'roll',.25),(77,'tap',0),(80,'roll',.3),
 (86.2,'tap',0),(90.8,'rustle',0),(93,'tap',-.2),(95.8,'rustle',0),
 (99,'twinkle',0),(103.5,'tap',0),(108,'rustle',.3),(110,'twinkle',.35),
 (114,'flutter',.25),(115.4,'boing',.05),(118,'twinkle',.1)]:
    effect(at,kind,.09 if kind!='boing' else .065,pan)

# Three small bell tones close the musical arc, while the last face holds.
for at,pitches in [(117,[72,76,79]),(118,[71,74,79]),(119,[72,76,79,84])]:
    for index,pitch in enumerate(pitches):
        play(pitch,at+index*.025,.4,'mallet',.034,(index-1.5)*.12)

# A tiny stereo room tail, without phase inversion or long muddy echoes.
for delay,gain in [(.061,.10),(.113,.065),(.173,.035)]:
    samples = int(delay*SR)
    music[samples:] += music[:-samples,::-1]*gain
fade_in = int(.12*SR)
fade_out = int(.18*SR)
music[:fade_in] *= np.linspace(0,1,fade_in)[:,None]
music[-fade_out:] *= np.linspace(1,0,fade_out)[:,None]
combined = music+foley
peak = float(np.max(np.abs(combined)))
scale = min(1.,.82/max(peak,.001))


def save(name,signal):
    with wave.open(str(OUT/name),'wb') as handle:
        handle.setparams((2,2,SR,len(signal),'NONE','not compressed'))
        handle.writeframes((np.clip(signal*scale,-1,1)*32767).astype('<i2').tobytes())


save('episode_music.wav',music)
save('episode_foley.wav',foley)
save('episode_score_and_foley.wav',combined)
(OUT/'score_cues.json').write_text(json.dumps(dict(duration=120,bpm=120,sample_rate=SR,
    origin='Original procedural composition; all instruments and effects synthesized; no voice or external samples',
    sections=[dict(start=0,end=28,name='curiosity'),dict(start=28,end=59,name='bounce and misunderstanding'),
              dict(start=59,end=89,name='light chase'),dict(start=89,end=107,name='teamwork'),
              dict(start=107,end=120,name='reveal and cadence')],foley=events,peak_before_normalization=peak),indent=2))
print(json.dumps(dict(seconds=LENGTH,bpm=120,foley_cues=len(events),peak=peak,output=str(OUT/'episode_score_and_foley.wav'))))
