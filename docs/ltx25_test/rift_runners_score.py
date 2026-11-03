"""Original 8-12 action-adventure instrumental score for Rift Runners — The Chrono-Core Heist.

Synthesized with Python + numpy (48 kHz stereo PCM).
Designed for an 8-12 tween adventure audience:
- Driving synth-bass ostinatos, heroic brass/lead motifs, clockwork crystal chimes, and warm pads.
- Dynamic drum & percussion grooves (punchy kick, crisp snare/rim, hi-hat/shaker pulse, tom fills)
  that kick in during stealth/heist/chase/climax scenes (S01-S06, S09-S13, S16) and drop out during
  the quiet sanctum discovery (S07-S08) and cliffside breather (S14-S15) so the drum entrances land
  with real cinematic energy.
"""
import json
import wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state/rift_runners_ep01'
spec = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
SR = 48000
TOTAL = sum(s['edit_seconds'] for s in spec['shots'])
track = np.zeros((int(TOTAL * SR) + SR * 3, 2), dtype=np.float32)
rng = np.random.default_rng(2040000)
events = []

# 112 BPM adventure tempo
BEAT = 60.0 / 112.0
BAR = 4.0 * BEAT


def place(sound, at, gain, pan=0.0):
    start = round(at * SR)
    n = min(len(sound), len(track) - start)
    if start < 0 or n <= 0:
        return
    track[start:start + n, 0] += sound[:n] * gain * np.sqrt((1 - pan) / 2)
    track[start:start + n, 1] += sound[:n] * gain * np.sqrt((1 + pan) / 2)


def drum(kind, at, gain=0.12, pan=0.0):
    if kind == 'kick':
        length = 0.22
        t = np.arange(round(length * SR), dtype=np.float32) / SR
        freq = 52.0 + 115.0 * np.exp(-t / 0.022)
        phase = 2 * np.pi * np.cumsum(freq) / SR
        body = np.sin(phase) * np.exp(-t / 0.095)
        click = rng.normal(0, 1, len(t)).astype(np.float32) * np.exp(-t / 0.004) * 0.25
        s = np.tanh((body + click) * 1.6)
    elif kind == 'snare':
        length = 0.18
        t = np.arange(round(length * SR), dtype=np.float32) / SR
        tone = np.sin(2 * np.pi * 185.0 * t) * np.exp(-t / 0.035) * 0.45
        noise = rng.normal(0, 1, len(t)).astype(np.float32)
        # simple high-pass feel via diff
        noise = np.diff(noise, prepend=noise[0]) * np.exp(-t / 0.055) * 0.85
        s = np.tanh((tone + noise) * 1.4)
    elif kind == 'rim':
        length = 0.07
        t = np.arange(round(length * SR), dtype=np.float32) / SR
        s = (np.sin(2 * np.pi * 480 * t) + 0.6 * np.sin(2 * np.pi * 1120 * t)) * np.exp(-t / 0.015)
    elif kind == 'hat':
        length = 0.06
        t = np.arange(round(length * SR), dtype=np.float32) / SR
        noise = rng.normal(0, 1, len(t)).astype(np.float32)
        hp = np.diff(np.diff(noise, prepend=0), prepend=0)
        s = hp * np.exp(-t / 0.016) * 0.5
    elif kind == 'tom':
        length = 0.24
        t = np.arange(round(length * SR), dtype=np.float32) / SR
        freq = 95.0 + 45.0 * np.exp(-t / 0.035)
        s = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / 0.11)
    else:  # crash / swell
        length = 0.65
        t = np.arange(round(length * SR), dtype=np.float32) / SR
        noise = rng.normal(0, 1, len(t)).astype(np.float32)
        hp = np.diff(noise, prepend=0)
        s = hp * np.minimum(t / 0.01, 1.0) * np.exp(-t / 0.25) * 0.35
    place(s.astype(np.float32), at, gain, pan)
    events.append(dict(at=round(at, 3), drum=kind))


def note(midi, at, length=0.4, gain=0.05, voice='pluck', pan=0.0):
    t = np.arange(round(length * SR), dtype=np.float32) / SR
    if len(t) == 0:
        return
    f = 440.0 * 2.0 ** ((midi - 69.0) / 12.0)
    if voice == 'bass':
        # Punchy synth-bass with warm harmonics
        s = (np.sin(2 * np.pi * f * t) + 0.45 * np.sin(4 * np.pi * f * t) + 0.2 * np.sin(6 * np.pi * f * t))
        s *= np.exp(-t / 0.26)
    elif voice == 'pluck':
        s = sum(np.sin(2 * np.pi * h * f * t) * np.exp(-t / (0.16 / (1 + 0.15 * h))) / (h ** 1.35) for h in range(1, 9))
    elif voice == 'brass':
        # Heroic French horn / synth-brass lead
        vib = 0.008 * np.sin(2 * np.pi * 5.2 * t)
        p = 2 * np.pi * f * (t + vib)
        s = sum(np.sin(h * p) / (h ** 1.15) for h in range(1, 8))
        s *= np.minimum(t / 0.045, 1.0) * np.minimum((length - t) / 0.09, 1.0)
    elif voice == 'crystal':
        # Clockwork-crystal bell for Pip
        s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2.76 * f * t) * np.exp(-t / 0.09)) * np.exp(-t / 0.75)
    elif voice == 'pad':
        s = sum(np.sin(2 * np.pi * f * d * t + d) for d in (1.0, 1.003, 0.997, 2.001)) / 4.0
        ramp = min(0.8, length / 3.0)
        s *= np.minimum(t / ramp, 1.0) * np.minimum((length - t) / ramp, 1.0)
    else:
        s = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.25)
    s = s * np.minimum(t / 0.003, 1.0) * np.minimum((length - t) / 0.012, 1.0)
    place(s.astype(np.float32), at, gain, pan)
    events.append(dict(at=round(at, 3), midi=midi, voice=voice))


# Heroic minor adventure motif (D Dorian / Aeolian intervals from root)
HERO_MOTIF = [
    (0, 0.0, 0.75), (3, 0.75, 0.25), (5, 1.0, 0.5), (7, 1.5, 1.0),
    (10, 2.5, 0.5), (7, 3.0, 0.5), (5, 3.5, 0.5), (7, 4.0, 1.5),
]
MIN_PROG = [(0, 3, 7), (-2, 2, 5), (-4, 0, 3), (-5, -1, 2)]  # i - VII - VI - v
HERO_PROG = [(0, 3, 7), (5, 8, 12), (-2, 2, 5), (7, 10, 14)]

SCENE_CUE = {
    'S01': ('stealth_groove', 62),   # D minor cool recon groove
    'S02': ('stealth_groove', 62),
    'S03': ('trap_action', 62),      # Fast syncopated drums + tension
    'S04': ('trap_action', 62),
    'S05': ('heavy_drums', 60),      # C minor heavy tom & kick march for Bram
    'S06': ('heavy_drums', 60),
    'S07': ('crystal_mystery', 65),  # Drums drop out! Shimmering clockwork-crystal & bass pulse
    'S08': ('crystal_mystery', 65),
    'S09': ('chase_drums', 62),      # Full driving adventure drum beat kicks back in!
    'S10': ('chase_drums', 62),
    'S11': ('chase_drums', 64),      # Modulate up to E minor for the chasm launch
    'S12': ('chase_drums', 64),
    'S13': ('hero_triumph', 67),     # G minor/Dorian heroic brass + big drum groove
    'S14': ('breather_calm', 65),    # Drums rest; warm twilight pad & gentle pluck
    'S15': ('warm_bond', 65),        # Sincere melody for the fist bump
    'S16': ('finale_anthem', 62),    # Heroic drum rhythm returns for the horizon reveal
}


def play_motif(root, at, voice='brass', gain=0.048, octave=0, count=8):
    for pitch, beat_pos, dur in HERO_MOTIF[:count]:
        note(root + octave + pitch, at + beat_pos * BEAT, dur * BEAT, gain, voice, 0.08)


for shot in spec['shots']:
    sid = shot['id']
    start, end = shot['start'], shot['end']
    style, root = SCENE_CUE[sid]
    bars = int(np.ceil((end - start) / BAR))
    for b in range(bars):
        at = start + b * BAR
        if at >= end - 0.15:
            break
        prog = HERO_PROG if style in {'hero_triumph', 'finale_anthem', 'warm_bond'} else MIN_PROG
        c = prog[b % 4]

        if style == 'stealth_groove':
            # Cool 8-12 spy/adventure groove: light kick, rimshot, 8th-note hats, plucked bass
            for step in range(8):
                t_step = at + step * (BEAT / 2)
                if t_step >= end:
                    break
                drum('hat', t_step, 0.045, 0.25 if step % 2 else -0.25)
                if step in (0, 3, 6):
                    drum('kick', t_step, 0.11)
                    note(root - 24 + c[0], t_step, 0.24, 0.095, 'bass')
                if step in (2, 6):
                    drum('rim', t_step, 0.075, -0.15)
                if step in (1, 4, 7):
                    note(root - 12 + c[step % 3], t_step, 0.2, 0.038, 'pluck', (step % 3 - 1) * 0.35)
            if b == 0:
                play_motif(root, at, 'pluck', 0.045, octave=0, count=6)

        elif style == 'trap_action':
            # Energetic breakbeat drum rhythm + urgent staccato strings/plucks
            for step in range(8):
                t_step = at + step * (BEAT / 2)
                if t_step >= end:
                    break
                drum('hat', t_step, 0.055)
                if step in (0, 3, 5):
                    drum('kick', t_step, 0.13)
                if step in (2, 6):
                    drum('snare', t_step, 0.11)
                if step == 7 and b % 2 == 1:
                    drum('tom', t_step, 0.10, 0.3)
                note(root - 24 + c[0] + (7 if step % 2 else 0), t_step, 0.2, 0.09, 'bass')
                if step % 2 == 1:
                    note(root + c[step % 3], t_step, 0.16, 0.04, 'pluck', 0.3 if step < 4 else -0.3)

        elif style == 'heavy_drums':
            # Heavy tom + kick rhythm for Bram holding the stone slab
            for beat in range(4):
                t_beat = at + beat * BEAT
                if t_beat >= end:
                    break
                drum('kick', t_beat, 0.14)
                drum('tom', t_beat + BEAT / 2, 0.11, -0.25 if beat % 2 else 0.25)
                if beat in (1, 3):
                    drum('snare', t_beat, 0.11)
                note(root - 24 + c[0], t_beat, 0.42, 0.11, 'bass')
            if b == 0:
                play_motif(root, at, 'brass', 0.048, octave=0, count=4)

        elif style == 'crystal_mystery':
            # Drums pause! Atmospheric pad + clockwork-crystal arpeggios for Pip
            note(root - 12 + c[0], at, BAR * 0.98, 0.05, 'pad', -0.2)
            note(root + c[2], at, BAR * 0.98, 0.04, 'pad', 0.2)
            for k in range(8):
                t_k = at + k * (BEAT / 2)
                if t_k >= end:
                    break
                note(root + 12 + c[k % 3] + (7 if k % 4 == 3 else 0), t_k, 0.45, 0.036, 'crystal', (k % 3 - 1) * 0.4)

        elif style == 'chase_drums':
            # High-energy driving adventure drums + bass + brass stabs
            if b == 0:
                drum('crash', at, 0.09)
            for step in range(8):
                t_step = at + step * (BEAT / 2)
                if t_step >= end:
                    break
                drum('hat', t_step, 0.06, 0.2)
                if step in (0, 2, 5):
                    drum('kick', t_step, 0.14)
                if step in (2, 6):
                    drum('snare', t_step, 0.12)
                if step in (6, 7) and b % 2 == 1:
                    drum('tom', t_step, 0.10, (step - 6.5) * 0.5)
                note(root - 24 + c[0] + (12 if step % 2 else 0), t_step, 0.21, 0.10, 'bass')
            if b % 2 == 0:
                play_motif(root, at, 'brass', 0.052, octave=0, count=8)

        elif style == 'hero_triumph':
            # Triumphant drum groove + soaring brass + crystal sparkles
            drum('crash', at, 0.10)
            note(root - 12 + c[0], at, BAR, 0.055, 'pad')
            for step in range(8):
                t_step = at + step * (BEAT / 2)
                if t_step >= end:
                    break
                if step in (0, 3, 4):
                    drum('kick', t_step, 0.13)
                if step in (2, 6):
                    drum('snare', t_step, 0.11)
                drum('hat', t_step, 0.05)
                note(root + 12 + c[step % 3], t_step, 0.35, 0.032, 'crystal', (step % 3 - 1) * 0.45)
            if b == 0:
                play_motif(root, at, 'brass', 0.06, octave=0, count=8)

        elif style in {'breather_calm', 'warm_bond'}:
            # Gentle no-drum breather on the twilight cliff, then warm melodic bond
            note(root - 12 + c[0], at, BAR * 0.98, 0.05, 'pad', -0.2)
            note(root + c[1], at, BAR * 0.98, 0.04, 'pad', 0.2)
            for beat in range(4):
                t_beat = at + beat * BEAT
                if t_beat >= end:
                    break
                note(root + c[beat % 3], t_beat, 0.5, 0.038, 'pluck', (beat % 3 - 1) * 0.3)
            if style == 'warm_bond' and b == 0:
                play_motif(root, at, 'crystal', 0.045, octave=12, count=6)

        elif style == 'finale_anthem':
            # Heroic drum rhythm returns for the final horizon crane-up
            if b == 0:
                drum('crash', at, 0.10)
                play_motif(root, at, 'brass', 0.062, octave=0, count=8)
            note(root - 12 + c[0], at, BAR, 0.06, 'pad')
            for step in range(8):
                t_step = at + step * (BEAT / 2)
                if t_step >= end:
                    break
                if step in (0, 3, 6):
                    drum('kick', t_step, 0.13)
                if step in (2, 6):
                    drum('snare', t_step, 0.11)
                drum('hat', t_step, 0.05)
                note(root - 24 + c[0], t_step, 0.22, 0.095, 'bass')

# Final chord swell at end of episode
end_fade = np.minimum(np.maximum((TOTAL + 0.5 - np.arange(len(track)) / SR) / 1.0, 0.0), 1.0)[:, None]
track = np.tanh(track * 1.15) * end_fade
pcm = np.clip(track[:int(TOTAL * SR)] * 30000, -32767, 32767).astype('<i2')

wav_path = OUT / spec['score_file']
with wave.open(str(wav_path), 'wb') as w:
    w.setparams((2, 2, SR, len(pcm), 'NONE', 'not compressed'))
    w.writeframes(pcm.tobytes())

score_meta = dict(
    path=str(wav_path),
    duration_seconds=TOTAL,
    sample_rate=SR,
    bpm=112,
    audience='8-12 years old action-adventure',
    features='Dynamic drum grooves (kick, snare, rimshot, hi-hat, toms) alternating with atmospheric crystal/clockwork discovery and warm bond cues',
    event_count=len(events),
)
(OUT / 'score_manifest.json').write_text(json.dumps(score_meta, indent=2), encoding='utf-8')
print(json.dumps(score_meta))
