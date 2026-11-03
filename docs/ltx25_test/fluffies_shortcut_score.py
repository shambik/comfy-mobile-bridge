"""Original instrumental underscore for The Great Shortcut; no samples or voices.

Run with the bundled media Python (numpy). First eight seconds are silent: the
published series ident already has its own music and native designed effects.
"""
import json
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'fluffies_ep01_shortcut'
SR = 48000
DURATION = 120
TRACK = np.zeros((SR * DURATION, 2), dtype=np.float32)
RNG = np.random.default_rng(1024300)
EVENTS = []


def add(signal, at, gain, pan=0):
    start = round(at * SR)
    count = min(len(signal), len(TRACK) - start)
    if start < 0 or count <= 0:
        return
    sound = signal[:count] * gain
    TRACK[start:start + count, 0] += sound * np.sqrt((1 - pan) / 2)
    TRACK[start:start + count, 1] += sound * np.sqrt((1 + pan) / 2)


def note(midi, at, length, gain, voice='wood', pan=0):
    t = np.arange(round(length * SR), dtype=np.float32) / SR
    frequency = 440 * 2 ** ((midi - 69) / 12)
    signal = np.zeros_like(t)
    if voice == 'strings':
        for harmonic in range(1, 10):
            signal += np.sin(2 * np.pi * harmonic * frequency * t) / harmonic ** 1.65
        signal *= np.exp(-t / .115)
    elif voice == 'bass':
        signal = (np.sin(2 * np.pi * frequency * t)
                  + .22 * np.sin(2 * np.pi * frequency * 2 * t)) * np.exp(-t / .2)
    elif voice == 'air':
        phase = 2 * np.pi * frequency * t + .012 * np.sin(2 * np.pi * 5.2 * t)
        signal = (np.sin(phase) + .12 * np.sin(phase * 2)) * np.minimum(t / .045, 1)
        signal *= np.minimum((length - t) / .1, 1)
    else:
        signal = (np.sin(2 * np.pi * frequency * t) * np.exp(-t / .19)
                  + .19 * np.sin(2 * np.pi * 2.76 * frequency * t) * np.exp(-t / .045)
                  + .07 * np.sin(2 * np.pi * 4.9 * frequency * t) * np.exp(-t / .025))
    signal *= np.minimum(t / .003, 1) * np.minimum((length - t) / .015, 1)
    add(signal, at, gain, pan)
    EVENTS.append(dict(at=at, midi=midi, duration=length, voice=voice))


def percussion(at, gain, kind='brush', pan=0):
    length = .11 if kind == 'brush' else .14
    t = np.arange(round(length * SR), dtype=np.float32) / SR
    if kind == 'brush':
        noise = RNG.normal(0, .5, len(t)).astype(np.float32)
        signal = np.diff(noise, prepend=0) * np.exp(-t / .025)
    else:
        signal = (np.sin(2 * np.pi * 740 * t) + .32 * np.sin(2 * np.pi * 1180 * t)) * np.exp(-t / .023)
    signal *= np.minimum(t / .001, 1)
    add(signal, at, gain, pan)


chords = [(48, 52, 55), (53, 57, 60), (57, 60, 64), (55, 59, 62),
          (48, 52, 55), (53, 57, 60), (50, 53, 57), (55, 59, 62)]
# Original melodic family: an upward invitation, an amused reply, then a warm
# descending answer. Leave alternate bars open for character reactions.
motifs = [
    [(76, 0), (79, .5), (81, 1), (79, 1.5)],
    [(74, .25), (76, .75), (72, 1.25)],
    [(79, 0), (84, .5), (81, 1.25)],
    [(77, 0), (76, .5), (74, 1), (72, 1.5)],
]
for bar in range(56):
    at = 8 + bar * 2
    chord = chords[bar % len(chords)]
    hedge = 38 <= at < 56
    playground = 56 <= at < 96
    home = at >= 104
    energy = .7 if hedge else (.88 if playground else .62 if home else .8)
    for beat in range(4):
        when = at + beat * .5
        if beat in (0, 2):
            note(chord[0] - 12 + (7 if beat == 2 else 0), when, .36, .105 * energy, 'bass', -.06)
        if not hedge or beat in (1, 3):
            for index, pitch in enumerate(chord):
                note(pitch + 12, when + .012 * index, .22, .035 * energy, 'strings', (index - 1) * .25)
        if playground or beat % 2:
            percussion(when + .25, .018 * energy, 'brush', .3)
        if playground and beat in (1, 3):
            percussion(when, .012, 'wood', -.3)
    if bar % 2 == 0 and at < 112:
        phrase = motifs[(bar // 2) % 4]
        for index, (pitch, offset) in enumerate(phrase):
            # The hedge gets tentative short punctuation; walking sections use
            # a soft airy answering phrase rather than a constant bell loop.
            if hedge and index > 1:
                continue
            voice = 'air' if (bar // 4) % 3 == 1 and not hedge else 'wood'
            note(pitch, at + offset, .29 if hedge else .38, .065 * energy, voice, .12)
    if bar % 8 == 7 and at < 110:
        note(72, at + 1.25, .55, .045, 'air', -.12)

# A clear, gentle ending that leaves space for the visual return-home joke.
for pitch, at, length in [(76, 112, .55), (79, 113, .55), (81, 114, .55),
                           (79, 115, .55), (74, 116, .55), (72, 117, 1.7)]:
    note(pitch, at, length, .055, 'wood', .08)
for pitch in [48, 60, 64, 67]:
    note(pitch, 118, 1.7, .035, 'air', 0)

peak = float(np.max(np.abs(TRACK)))
TRACK *= .55 / max(peak, .001)
TRACK[8 * SR:8 * SR + 4800] *= np.linspace(0, 1, 4800)[:, None]
TRACK[-24000:] *= np.linspace(1, 0, 24000)[:, None]
OUT.mkdir(parents=True, exist_ok=True)
with wave.open(str(OUT / 'shortcut_original_score_120s.wav'), 'wb') as stream:
    stream.setparams((2, 2, SR, len(TRACK), 'NONE', 'not compressed'))
    stream.writeframes((np.clip(TRACK, -1, 1) * 32767).astype('<i2').tobytes())
(OUT / 'score_manifest.json').write_text(json.dumps(dict(
    duration=DURATION, sample_rate=SR, channels=2, bpm=120,
    policy='Original instrumental underscore only. Preserve native voices/effects. Intro 0-8 seconds silent here.',
    sections=[dict(start=8, end=38, arrangement='light travelling pizzicato and wood melody'),
              dict(start=38, end=56, arrangement='sparse tentative hedge punctuation'),
              dict(start=56, end=96, arrangement='brighter playground rhythm'),
              dict(start=96, end=112, arrangement='warm shared walking and picnic'),
              dict(start=112, end=120, arrangement='return-home cadence')],
    events=EVENTS), indent=2), encoding='utf-8')
print(json.dumps(dict(score=str(OUT / 'shortcut_original_score_120s.wav'), duration=DURATION, peak=float(np.max(np.abs(TRACK))))))
