"""Original instrumental score for The Little Lost Star, synthesized without samples.

Run with Python + numpy. Cues follow the manifest's scene timings (whole scenes,
no trims). The opener's ten seconds stay silent here so its own soundtrack plays.
A single "Twinkle" leitmotif returns in wonder, sad, hopeful, triumphant and
lullaby colours so the music carries the story arc.
"""
import json
import wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state/fluffies_ep03_lost_star'
spec = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
SR = 48000
TOTAL = 10 + sum(s['edit_seconds'] for s in spec['shots'])
track = np.zeros((int(TOTAL * SR) + SR * 3, 2), dtype=np.float32)
rng = np.random.default_rng(1030000)
events = []
BEAT = 60 / 96
BAR = 4 * BEAT


def place(sound, at, gain, pan=0.0):
    start = round(at * SR)
    n = min(len(sound), len(track) - start)
    if start < 0 or n <= 0:
        return
    track[start:start + n, 0] += sound[:n] * gain * np.sqrt((1 - pan) / 2)
    track[start:start + n, 1] += sound[:n] * gain * np.sqrt((1 + pan) / 2)


def note(midi, at, length=.4, gain=.05, voice='pizz', pan=0.0):
    t = np.arange(round(length * SR), dtype=np.float32) / SR
    f = 440 * 2 ** ((midi - 69) / 12)
    if voice == 'pizz':
        s = sum(np.sin(2 * np.pi * h * f * t) * np.exp(-t / (.13 / (1 + .1 * h))) / h ** 1.6 for h in range(1, 10))
    elif voice == 'bass':
        s = (np.sin(2 * np.pi * f * t) + .25 * np.sin(4 * np.pi * f * t)) * np.exp(-t / .35)
    elif voice == 'celesta':
        s = (np.sin(2 * np.pi * f * t) + .3 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / .08)) * np.exp(-t / .9)
    elif voice == 'harp':
        s = sum(np.sin(2 * np.pi * h * f * t) / h ** 2 for h in range(1, 6)) * np.exp(-t / .7)
    elif voice == 'flute':
        p = 2 * np.pi * f * t + .02 * np.sin(2 * np.pi * 5 * t)
        s = (np.sin(p) + .1 * np.sin(2 * p) + .03 * np.sin(3 * p)) * np.minimum(t / .06, 1)
        s *= np.minimum((length - t) / .12, 1)
    elif voice == 'clarinet':
        p = 2 * np.pi * f * t + .01 * np.sin(2 * np.pi * 5 * t)
        s = (np.sin(p) + .25 * np.sin(3 * p) + .08 * np.sin(5 * p)) * np.minimum(t / .05, 1)
        s *= np.minimum((length - t) / .12, 1)
    elif voice == 'pad':
        s = sum(np.sin(2 * np.pi * f * d * t + d) for d in (1, 1.004, .996, 2.002)) / 4
        s *= np.minimum(t / min(1.2, length / 3), 1) * np.minimum((length - t) / min(1.2, length / 3), 1)
    else:  # wood block / marimba
        s = (np.sin(2 * np.pi * f * t) * np.exp(-t / .2) + .15 * np.sin(2 * np.pi * 3.9 * f * t) * np.exp(-t / .04))
    s = s * np.minimum(t / .003, 1) * np.minimum((length - t) / .015, 1)
    place(s.astype(np.float32), at, gain, pan)
    events.append(dict(at=round(at, 3), midi=midi, voice=voice))


def slide(at, up=True, length=.7, gain=.04):
    t = np.arange(round(length * SR), dtype=np.float32) / SR
    f = np.linspace(500, 1500, len(t)) if up else np.linspace(1300, 380, len(t))
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.minimum(t / .03, 1) * np.minimum((length - t) / .1, 1)
    place(s, at, gain, .2)


def shimmer(at, length=2.0, gain=.02):
    for k in range(int(length * 10)):
        note(int(rng.choice([84, 86, 88, 91, 93, 96])), at + k * .1, .8, gain * rng.uniform(.5, 1), 'celesta', float(rng.uniform(-.7, .7)))


# Twinkle leitmotif in scale steps of a major key (semitones from the root)
THEME = [(4, 0, 1), (7, 1, 1), (12, 2, 1.5), (11, 3.5, .5), (9, 4, 1), (7, 5, 2), (5, 7, 1), (4, 8, 1), (2, 9, 1), (4, 10, 2)]
MAJOR = [(0, 4, 7), (5, 9, 12), (-3, 0, 4), (7, 11, 14)]  # I IV vi V
MINOR = [(0, 3, 7), (-4, 0, 3), (5, 8, 12), (7, 10, 14)]   # i VI iv v
STYLE = {  # shot id -> (style, key root)
 'S01': ('walk', 65), 'S02': ('wonder', 65), 'S03': ('mystery', 62), 'S04': ('mystery', 62), 'S05': ('mystery', 62),
 'S06': ('tender', 65), 'S07': ('sad', 62), 'S08': ('comic', 67), 'S09': ('hurry', 67), 'S10': ('comic', 67),
 'S11': ('comic', 67), 'S12': ('comic', 67), 'S13': ('hope', 65), 'S14': ('hope', 65), 'S15': ('danger', 62),
 'S16': ('sad', 62), 'S17': ('idea', 65), 'S18': ('build', 67), 'S19': ('swell', 67), 'S20': ('swell', 67),
 'S21': ('triumph', 67), 'S22': ('joy', 67), 'S23': ('lullaby', 65)}

segments = []
for shot in spec['shots']:
    style, root = STYLE[shot['id']]
    if segments and segments[-1]['style'] == style:
        segments[-1]['end'] = shot['end']
    else:
        segments.append(dict(style=style, root=root, start=shot['start'], end=shot['end'], first=shot['id']))


def theme(root, at, voice, gain, step=BEAT, octave=12, upto=None):
    for pitch, when, dur in THEME[:upto]:
        note(root + octave + pitch, at + when * step, dur * step * 1.1, gain, voice, .1)


for seg in segments:
    s, e, r, st = seg['start'], seg['end'], seg['root'], seg['style']
    bars = int(np.ceil((e - s) / BAR))
    for b in range(bars):
        at = s + b * BAR
        if at >= e - .2:
            break
        chords = MINOR if st in {'mystery', 'sad', 'danger'} else MAJOR
        c = chords[b % 4]
        if st == 'walk':
            for beat in range(4):
                note(r - 24 + c[0] + (7 if beat % 2 else 0), at + beat * BEAT, .4, .10, 'bass')
                for i, p in enumerate(c):
                    note(r + p, at + beat * BEAT + BEAT / 2 + .01 * i, .25, .03, 'pizz', (i - 1) * .3)
            if b % 2 == 0:
                theme(r, at, 'flute', .05, upto=6)
        elif st in {'wonder', 'tender', 'lullaby'}:
            note(r - 12 + c[0], at, BAR * 1.05, .05, 'pad')
            note(r + c[1], at, BAR * 1.05, .03, 'pad')
            for k in range(8):
                note(r + 12 + c[k % 3] + (12 if k > 3 else 0), at + k * BEAT / 2, 1.0, .028, 'harp' if st != 'lullaby' else 'celesta', (k % 3 - 1) * .4)
            if b % 3 == 0:
                theme(r, at, 'celesta', .045, step=BEAT * (1.25 if st == 'lullaby' else 1), upto=None if st != 'tender' else 7)
        elif st == 'mystery':
            note(r - 12 + c[0], at, BAR * 1.05, .06, 'pad')
            note(r - 24 + c[0], at, BAR, .05, 'bass')
            for k in (0, 3, 6):
                note(r + 24 + c[k % 3], at + k * BEAT / 2, 1.2, .022, 'celesta', .5 - .3 * k / 3)
        elif st == 'sad':
            note(r - 12 + c[0], at, BAR * 1.05, .055, 'pad')
            note(r + c[1], at, BAR * 1.05, .03, 'pad')
            if b % 2 == 0:
                for pitch, when, dur in [(7, 0, 1.5), (5, 1.5, .5), (3, 2, 1), (2, 3, 1), (0, 4, 2), (-2, 6, 2)]:
                    note(r + pitch, at + when * BEAT, dur * BEAT * 1.1, .055, 'clarinet', -.1)
        elif st in {'comic', 'hurry'}:
            step = BEAT / (2 if st == 'hurry' else 1)
            for k in range(int(BAR / step)):
                note(r - 24 + c[0] + (7 if k % 2 else 0), at + k * step, .3, .09, 'bass')
                note(r + 12 + c[k % 3], at + k * step + step / 2, .2, .035, 'pizz', .3 if k % 2 else -.3)
            if b % 2 == 1:
                note(r + 19, at + 3 * BEAT, .2, .04, 'wood')
                note(r + 24, at + 3.5 * BEAT, .2, .04, 'wood')
        elif st in {'hope', 'idea'}:
            note(r - 12 + c[0], at, BAR * 1.05, .05, 'pad')
            for k in range(8):
                note(r + 12 + c[k % 3] + (12 if k % 4 == 3 else 0), at + k * BEAT / 2, .9, .03, 'harp', .3)
            if b % 2 == 0:
                theme(r, at, 'flute', .05, upto=6)
        elif st == 'danger':
            for k in range(8):
                note(r - 24 + c[0], at + k * BEAT / 2, .25, .08, 'bass')
                note(r + 12 + c[k % 2], at + k * BEAT / 2, .18, .03, 'pizz', .2)
        elif st == 'build':
            for k in range(8):
                note(r - 24 + c[0] + (12 if k % 4 == 2 else 0), at + k * BEAT / 2, .3, .08, 'bass')
                note(r + 12 + c[k % 3], at + k * BEAT / 2 + .02, .22, .03, 'pizz', (k % 3 - 1) * .3)
                note(r + 24 + c[(k + 1) % 3], at + k * BEAT / 2 + BEAT / 4, .2, .018, 'wood', .4)
            if b % 2 == 0:
                theme(r, at, 'flute', .05)
        elif st in {'swell', 'triumph', 'joy'}:
            grow = min(1.0, .55 + .15 * b) if st == 'swell' else 1.0
            note(r - 12 + c[0], at, BAR * 1.05, .07 * grow, 'pad')
            note(r + c[1], at, BAR * 1.05, .045 * grow, 'pad')
            note(r + 7 + c[0], at, BAR * 1.05, .035 * grow, 'pad')
            note(r - 24 + c[0], at, BAR, .09 * grow, 'bass')
            for k in range(8):
                note(r + 12 + c[k % 3] + (12 if k > 3 else 0), at + k * BEAT / 2, .9, .03 * grow, 'harp', (k % 3 - 1) * .4)
            if st == 'joy':
                for k in range(4):
                    note(r + 12 + c[k % 3], at + k * BEAT + BEAT / 2, .22, .035, 'pizz', .3)
            if b % 2 == 0 and st != 'swell':
                theme(r, at, 'flute', .06)
                theme(r, at, 'celesta', .03, octave=24)

# Story accents (musical only; the scenes' native sound owns the action effects)
shots = {s['id']: s for s in spec['shots']}
shimmer(shots['S03']['start'] + 1.0, 2.5, .02)
note(50, shots['S04']['start'] + 2.0, 2.5, .07, 'pad')
shimmer(shots['S06']['start'] + 4.0, 2.0, .018)
slide(shots['S11']['start'] + 1.6, True, .8)
slide(shots['S12']['start'] + .8, False, 1.0, .03)
slide(shots['S15']['start'] + 1.8, False, 1.2, .03)
shimmer(shots['S17']['start'] + 2.5, 3.0, .02)
shimmer(shots['S21']['start'] + 1.5, 4.0, .03)
shimmer(shots['S22']['start'] + .5, 3.0, .025)
end = shots['S23']['end']
for midi, at, length in [(77, end - 6, 1.2), (76, end - 4.8, 1.2), (74, end - 3.6, 1.2), (72, end - 2.4, 2.4)]:
    note(midi, at, length, .05, 'celesta', .1)
for p in (53, 60, 65, 69):
    note(p, end - 4.8, 4.8, .04, 'pad')

track = track[:int(TOTAL * SR)]
track *= .55 / max(float(np.max(np.abs(track))), .001)
track[:10 * SR] = 0
track[10 * SR:10 * SR + 4800] *= np.linspace(0, 1, 4800)[:, None]
track[-48000:] *= np.linspace(1, 0, 48000)[:, None]
target = OUT / spec['score_file']
with wave.open(str(target), 'wb') as stream:
    stream.setparams((2, 2, SR, len(track), 'NONE', 'not compressed'))
    stream.writeframes((np.clip(track, -1, 1) * 32767).astype('<i2').tobytes())
(OUT / 'score_manifest.json').write_text(json.dumps(dict(
    title='The Little Lost Star — original instrumental underscore', duration=TOTAL, bpm=96,
    source='Original synthesized composition, no external recordings or samples',
    opener_policy='0–10 s silent; the selected opener keeps its own soundtrack',
    segments=segments, events=len(events)), indent=2, ensure_ascii=False), encoding='utf-8')
print(json.dumps(dict(score=str(target), seconds=TOTAL, segments=len(segments))))
