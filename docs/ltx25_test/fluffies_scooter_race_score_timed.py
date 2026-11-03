"""Motion-aligned original racing score for Fluffies — The Big Scooter Race.

Synthesized purely in Python with numpy and scipy.signal without external audio samples.
Aligned to exact trimmed story cuts (motion onset):
- 00:00.0 - 00:10.0 (10.0s): Silent for selected vault opener (1002475080.mp4).
- 00:10.0 - 00:15.3 (S01, 5.3s): Pre-race tension, clock ticking, anticipatory chitter.
- 00:15.3 - 00:19.8 (S02, 4.5s): Numi whistle countdown & flag drop ("pip... pip... pip... GO!").
- 00:19.8 - 00:63.3 (S03-S10): Full beat drop, slap-bass groove, catchy flute/marimba theme,
                               bicycle bell at S04, bridge slide at S08, daisy slide at S09, tuba at S10.
- 00:63.3 - 00:74.7 (S11-S12): Driving double-time sprint modulation to E Major, brass fanfare,
                               finish-line ribbon snap & confetti cymbal at ~70.0s.
- 00:74.7 - 00:81.2 (S13, 6.5s): Victory celebration bounce, stinger chord.
- 00:81.2 - 00:91.2 (10.0s): Silent for selected vault outro (1002475708.mp4).
Total: 91.2 seconds (2189 frames @ 24 fps).
"""
import wave
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'fluffies_ep04_scooter_race'
OUT.mkdir(parents=True, exist_ok=True)

SR = 48000
BPM = 138.0
BEAT = 60.0 / BPM  # ~0.4348s
SIXTEENTH = BEAT / 4.0
TOTAL_SECONDS = 92.0  # 10s intro + 71.2s story + 10s outro + padding
TOTAL_SAMPLES = int(TOTAL_SECONDS * SR) + SR * 2

track = np.zeros((TOTAL_SAMPLES, 2), dtype=np.float32)
rng = np.random.default_rng(20261024)


def place(sound, at_sec, gain=1.0, pan=0.0):
    start = int(round(at_sec * SR))
    if start < 0 or start >= len(track):
        return
    n = min(len(sound), len(track) - start)
    if n <= 0:
        return
    left_gain = gain * np.sqrt((1.0 - pan) / 2.0)
    right_gain = gain * np.sqrt((1.0 + pan) / 2.0)
    track[start:start + n, 0] += sound[:n] * left_gain
    track[start:start + n, 1] += sound[:n] * right_gain


# --- Drum Synthesizers ---

def synth_kick(at_sec, gain=0.35):
    dur = 0.35
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    f_env = 160.0 * np.exp(-t * 28.0) + 45.0
    phase = 2.0 * np.pi * np.cumsum(f_env) / SR
    amp = np.exp(-t * 12.0)
    body = np.sin(phase) * amp
    click = (rng.uniform(-1.0, 1.0, len(t)) * np.exp(-t * 80.0)).astype(np.float32) * 0.3
    place(body + click, at_sec, gain=gain, pan=0.0)


def synth_snare(at_sec, gain=0.28):
    dur = 0.28
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    tone = np.sin(2.0 * np.pi * 185.0 * t) * np.exp(-t * 22.0)
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32) * np.exp(-t * 16.0)
    snap = (rng.uniform(-1.0, 1.0, len(t)) * np.exp(-t * 90.0)).astype(np.float32) * 0.5
    place(tone * 0.4 + noise * 0.5 + snap * 0.3, at_sec, gain=gain, pan=0.05)


def synth_hat(at_sec, open_hat=False, gain=0.12, pan=0.25):
    dur = 0.32 if open_hat else 0.06
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32)
    carrier = np.sin(2.0 * np.pi * 7800.0 * t) + np.sin(2.0 * np.pi * 9200.0 * t) * 0.5
    decay = 10.0 if open_hat else 70.0
    amp = np.exp(-t * decay)
    place((noise * 0.7 + carrier * 0.3) * amp, at_sec, gain=gain, pan=pan)


def synth_crash(at_sec, gain=0.28):
    dur = 1.8
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32)
    carrier = (np.sin(2.0 * np.pi * 4200.0 * t) +
               np.sin(2.0 * np.pi * 6100.0 * t) * 0.7 +
               np.sin(2.0 * np.pi * 8400.0 * t) * 0.5)
    amp = np.exp(-t * 3.5)
    place((noise * 0.75 + carrier * 0.25) * amp, at_sec, gain=gain, pan=-0.2)


def synth_tick(at_sec, gain=0.18, pan=0.0):
    dur = 0.05
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    sig = np.sin(2.0 * np.pi * 2400.0 * t) * np.exp(-t * 120.0)
    place(sig, at_sec, gain=gain, pan=pan)


def synth_whistle(at_sec, f0=2200.0, dur=0.22, gain=0.25, pan=-0.1):
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    wobble = np.sin(2.0 * np.pi * 28.0 * t) * 60.0
    phase = 2.0 * np.pi * np.cumsum(f0 + wobble) / SR
    env = np.sin(np.pi * np.clip(t / dur, 0.0, 1.0)) ** 1.5
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32) * 0.08
    place((np.sin(phase) + noise) * env, at_sec, gain=gain, pan=pan)


def synth_slide(at_sec, f_start=300.0, f_end=1200.0, dur=0.5, gain=0.20, pan=0.0):
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    f_inst = np.linspace(f_start, f_end, len(t))
    phase = 2.0 * np.pi * np.cumsum(f_inst) / SR
    env = np.sin(np.pi * np.clip(t / dur, 0.0, 1.0))
    place(np.sin(phase) * env, at_sec, gain=gain, pan=pan)


def synth_bell(at_sec, gain=0.25, pan=0.3):
    dur = 0.7
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    partials = [(2640.0, 1.0, 12.0), (5280.0, 0.6, 22.0), (8100.0, 0.35, 35.0)]
    sig = np.zeros_like(t)
    for freq, p_gain, decay in partials:
        sig += np.sin(2.0 * np.pi * freq * t) * np.exp(-t * decay) * p_gain
    place(sig, at_sec, gain=gain, pan=pan)


# --- Melodic Voices ---

def midi_to_freq(midi):
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def synth_tone(midi, at_sec, length=0.2, voice='flute', gain=0.15, pan=0.0):
    dur = length + (0.05 if voice in ('marimba', 'tuba') else 0.15)
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    f0 = midi_to_freq(midi)

    if voice == 'flute':
        vib = np.sin(2.0 * np.pi * 5.5 * t) * 8.0
        phase = 2.0 * np.pi * np.cumsum(f0 + vib) / SR
        env = np.clip(t / 0.03, 0.0, 1.0) * np.clip((dur - t) / 0.08, 0.0, 1.0)
        h2 = np.sin(2.0 * phase) * 0.15
        h3 = np.sin(3.0 * phase) * 0.08
        sig = (np.sin(phase) + h2 + h3) * env

    elif voice == 'marimba':
        env = np.exp(-t * 18.0)
        h2 = np.sin(2.0 * np.pi * (f0 * 2.0) * t) * 0.25 * np.exp(-t * 26.0)
        sig = (np.sin(2.0 * np.pi * f0 * t) + h2) * env

    elif voice == 'tuba':
        env = np.clip(t / 0.04, 0.0, 1.0) * np.exp(-t * 7.0)
        h2 = np.sin(2.0 * np.pi * (f0 * 2.0) * t) * 0.55
        h3 = np.sin(2.0 * np.pi * (f0 * 3.0) * t) * 0.35
        h4 = np.sin(2.0 * np.pi * (f0 * 4.0) * t) * 0.20
        sig = (np.sin(2.0 * np.pi * f0 * t) + h2 + h3 + h4) * env

    elif voice == 'brass':
        env = np.clip(t / 0.02, 0.0, 1.0) * np.clip((dur - t) / 0.04, 0.0, 1.0)
        h2 = np.sin(2.0 * np.pi * (f0 * 2.0) * t) * 0.60
        h3 = np.sin(2.0 * np.pi * (f0 * 3.0) * t) * 0.45
        h4 = np.sin(2.0 * np.pi * (f0 * 4.0) * t) * 0.30
        h5 = np.sin(2.0 * np.pi * (f0 * 5.0) * t) * 0.18
        sig = (np.sin(2.0 * np.pi * f0 * t) + h2 + h3 + h4 + h5) * env

    elif voice == 'celesta':
        env = np.exp(-t * 10.0)
        h2 = np.sin(2.0 * np.pi * (f0 * 2.0) * t) * 0.35 * np.exp(-t * 16.0)
        sig = (np.sin(2.0 * np.pi * f0 * t) + h2) * env

    elif voice == 'bass':
        env = np.clip(t / 0.015, 0.0, 1.0) * np.exp(-t * 9.0)
        h2 = np.sin(2.0 * np.pi * (f0 * 2.0) * t) * 0.40
        sig = (np.sin(2.0 * np.pi * f0 * t) + h2) * env

    else:
        env = np.exp(-t * 12.0)
        sig = np.sin(2.0 * np.pi * f0 * t) * env

    place(sig, at_sec, gain=gain, pan=pan)


print("Composing motion-aligned musical arrangement...")

# 1. 00:00 - 00:10: Opener is 100% silent (vault 1002475080.mp4 has own music)

# 2. 10.0s - 15.3s: S01 The Starting Line (Tension / anticipation)
for beat_i in range(12):
    t_beat = 10.0 + beat_i * BEAT
    synth_tick(t_beat, gain=0.20 + (beat_i * 0.01), pan=(beat_i % 2) * 0.4 - 0.2)
    if beat_i % 2 == 0:
        synth_tone(48, t_beat, length=0.15, voice='bass', gain=0.12)
    if beat_i == 8:
        synth_bell(t_beat, gain=0.20, pan=0.3)

# 3. 15.3s - 19.8s: S02 Numi Whistle Countdown & Flag Drop
whistle_times = [15.5, 16.8, 18.0]
for wt in whistle_times:
    synth_whistle(wt, f0=2400.0, dur=0.14, gain=0.22, pan=-0.2)
    synth_kick(wt, gain=0.25)
# Long GO whistle at 19.2s
synth_whistle(19.2, f0=2650.0, dur=0.45, gain=0.35, pan=0.0)
synth_crash(19.75, gain=0.32)

# 4. 19.8s - 63.3s: S03-S10 Full Driving Cartoon Race Groove (C Major: C=48 / 60)
THEME_A = [
    (60, 0.0, 0.2), (64, 0.5, 0.2), (67, 1.0, 0.2), (72, 1.5, 0.35),
    (71, 2.0, 0.2), (67, 2.5, 0.2), (65, 3.0, 0.25), (64, 3.5, 0.18)
]
THEME_B = [
    (65, 0.0, 0.2), (69, 0.5, 0.2), (72, 1.0, 0.25), (71, 1.5, 0.35),
    (67, 2.0, 0.2), (64, 2.5, 0.2), (62, 3.0, 0.25), (60, 3.5, 0.4)
]
PEBBLE_THEME = [
    (36, 0.0, 0.35), (43, 1.0, 0.35), (40, 2.0, 0.35), (43, 3.0, 0.35)
]

t = 19.75
bar_idx = 0
roots = [48, 48, 53, 55]  # C, C, F, G

while t < 63.3:
    cur_root = roots[bar_idx % len(roots)]
    is_pebble_shot = (41.5 <= t < 46.8) or (57.8 <= t < 63.3)

    for b in range(4):
        bt = t + b * BEAT
        if is_pebble_shot:
            if b % 2 == 0:
                synth_kick(bt, gain=0.32)
                synth_tone(PEBBLE_THEME[b][0], bt, length=0.35, voice='tuba', gain=0.22, pan=-0.2)
            else:
                synth_snare(bt, gain=0.18)
            synth_hat(bt + SIXTEENTH * 2, open_hat=False, gain=0.08, pan=0.1)
        else:
            if b in (0, 2):
                synth_kick(bt, gain=0.34)
            if b in (1, 3):
                synth_snare(bt, gain=0.24)
            for s in range(4):
                synth_hat(bt + s * SIXTEENTH, open_hat=(s == 2 and b % 2 == 1), gain=0.09, pan=(s - 1.5) * 0.15)
            # Bassline
            synth_tone(cur_root, bt, length=0.18, voice='bass', gain=0.13, pan=-0.1)
            synth_tone(cur_root + 7, bt + SIXTEENTH * 2, length=0.15, voice='bass', gain=0.10, pan=-0.1)

    # Lead melody
    if not is_pebble_shot:
        theme = THEME_A if (bar_idx % 2 == 0) else THEME_B
        for note_midi, beat_offset, dur in theme:
            synth_tone(note_midi, t + beat_offset * BEAT, length=dur, voice='flute', gain=0.11, pan=-0.1)
            synth_tone(note_midi + 12, t + beat_offset * BEAT, length=dur, voice='marimba', gain=0.09, pan=0.2)
            synth_tone(note_midi + 24, t + beat_offset * BEAT, length=dur, voice='celesta', gain=0.06, pan=0.3)

    # Specific sound flourishes:
    # Bicycle bell in Bobo's shot (S04: 25.2s - 30.8s)
    if 26.5 <= t < 28.0 or 29.0 <= t < 30.5:
        synth_bell(t + 0.3, gain=0.24, pan=0.3)

    # Bridge Hop glissando at S08 (46.8s - 52.1s)
    if 48.0 <= t < 49.5:
        synth_slide(t, f_start=400.0, f_end=1200.0, dur=0.45, gain=0.18)

    # Daisy drift slide whistle down at S09 (52.1s - 57.8s)
    if 53.5 <= t < 55.0:
        synth_slide(t + 0.2, f_start=1100.0, f_end=350.0, dur=0.55, gain=0.20)

    t += 4 * BEAT
    bar_idx += 1

# 5. 63.3s - 74.7s: S11-S12 Final Sprint & Ribbon Finish (Modulate to E Major: E=52 / 64)
t_sprint = 63.3
synth_crash(t_sprint, gain=0.32)

FANFARE = [
    (76, 0.0, 0.3), (80, 0.75, 0.25), (83, 1.25, 0.25), (88, 1.75, 0.6),
    (85, 3.0, 0.4), (88, 4.0, 0.8), (92, 5.5, 1.2)
]

bar_sprint = 0
sprint_roots = [52, 52, 57, 47]

while t_sprint < 74.7:
    cur_root = sprint_roots[bar_sprint % len(sprint_roots)]
    for b in range(4):
        bt = t_sprint + b * BEAT
        synth_kick(bt, gain=0.38)
        if b % 2 == 1:
            synth_snare(bt, gain=0.30)
        for s in range(4):
            synth_hat(bt + s * SIXTEENTH, open_hat=(s == 2), gain=0.11, pan=0.2)
        synth_tone(cur_root, bt, length=0.18, voice='bass', gain=0.14, pan=0.0)
        synth_tone(cur_root + 12, bt + SIXTEENTH * 2, length=0.18, voice='bass', gain=0.12, pan=0.0)

    if bar_sprint == 0:
        for note_midi, beat_offset, dur in FANFARE:
            synth_tone(note_midi, t_sprint + beat_offset * BEAT, length=dur, voice='brass', gain=0.12, pan=-0.1)
            synth_tone(note_midi + 12, t_sprint + beat_offset * BEAT, length=dur, voice='celesta', gain=0.07, pan=0.2)

    # Finish Line Ribbon Burst at ~70.0s (S12 start)
    if 69.8 <= t_sprint < 71.5:
        synth_crash(t_sprint + 0.2, gain=0.38)
        synth_bell(t_sprint + 0.4, gain=0.25, pan=-0.2)
        synth_bell(t_sprint + 0.7, gain=0.25, pan=0.3)

    t_sprint += 4 * BEAT
    bar_sprint += 1

# 6. 74.7s - 81.2s: S13 Victory Celebration Bounce & Stinger Chord
t_vic = 74.7
synth_crash(t_vic, gain=0.30)
while t_vic < 80.5:
    for b in range(4):
        bt = t_vic + b * BEAT
        if bt >= 80.5:
            break
        if b % 2 == 0:
            synth_kick(bt, gain=0.30)
            synth_tone(52, bt, length=0.2, voice='bass', gain=0.10)
        else:
            synth_snare(bt, gain=0.22)
            synth_tone(64, bt, length=0.15, voice='bass', gain=0.08)
        synth_hat(bt, open_hat=False, gain=0.08)
        synth_hat(bt + SIXTEENTH * 2, open_hat=True, gain=0.08)
        synth_tone(76 + (b * 4) % 12, bt, length=0.2, voice='marimba', gain=0.08)
        synth_tone(88, bt + SIXTEENTH * 2, length=0.2, voice='celesta', gain=0.07)
    t_vic += 4 * BEAT

# Final triumphant stinger chord at 80.6s (right before outro cut at 81.2s)
synth_tone(52, 80.6, length=0.8, voice='bass', gain=0.15)
synth_tone(64, 80.6, length=0.8, voice='brass', gain=0.12)
synth_tone(68, 80.6, length=0.8, voice='brass', gain=0.11)
synth_tone(71, 80.6, length=0.8, voice='brass', gain=0.11)
synth_tone(76, 80.6, length=0.8, voice='flute', gain=0.10)
synth_tone(88, 80.6, length=0.8, voice='celesta', gain=0.12)
synth_crash(80.6, gain=0.35)

# Fade out music right at 81.2s so Outro theme enters cleanly
fade_start = int(80.8 * SR)
fade_end = int(81.2 * SR)
fade_len = fade_end - fade_start
if fade_len > 0:
    track[fade_start:fade_end] *= np.linspace(1.0, 0.0, fade_len, dtype=np.float32)[:, np.newaxis]
track[fade_end:] = 0.0  # Silent for Outro

peak = np.max(np.abs(track))
if peak > 0.0:
    track = (track / peak) * 0.92

out_wav = OUT / 'scooter_race_motion_timed_score.wav'
pcm = (track * 32767.0).astype(np.int16)
with wave.open(str(out_wav), 'wb') as stream:
    stream.setnchannels(2)
    stream.setsampwidth(2)
    stream.setframerate(SR)
    stream.writeframes(pcm.tobytes())

print(f"Synthesized motion-timed score: {out_wav} (peak {peak:.2f})")
