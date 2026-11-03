"""Energetic original racing score for Fluffies — The Big Scooter Race.

Synthesized purely in Python with numpy and scipy.signal without external audio samples.
- Tempo: 138 BPM (driving, bouncy, upbeat cartoon race).
- Opener: 00:00 - 00:10 stays 100% silent so the selected vault opener plays cleanly.
- Act 1 (10s - 21s): Tension, pizzicato ticking, starting whistle countdown ("pip... pip... pip... GO!").
- Act 2 (21s - 69s): High-energy drum beat drop, slap-bass groove, catchy flute/synth/marimba race theme,
  slapstick slide whistle & comic tuba breakdown for Pebble.
- Act 3 (69s - 89s): Key modulation to E Major, galloping double-time percussion, soaring brass fanfare,
  confetti cymbal crashes, triumphant victory stinger!
"""
import json
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
TOTAL_SECONDS = 90.0  # 10s opener + 79s story + margin
TOTAL_SAMPLES = int(TOTAL_SECONDS * SR) + SR * 2

track = np.zeros((TOTAL_SAMPLES, 2), dtype=np.float32)
rng = np.random.default_rng(20261024)


def place(sound, at_sec, gain=1.0, pan=0.0):
    """Place a mono sound onto the stereo master track at at_sec with panning [-1, 1]."""
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
    # Exponential frequency drop from 150 Hz to 42 Hz
    freq = 42.0 + (150.0 - 42.0) * np.exp(-t / 0.045)
    phase = 2.0 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase) * np.exp(-t / 0.12)
    # High frequency initial click
    click = (rng.uniform(-1.0, 1.0, len(t)) * np.exp(-t / 0.005)).astype(np.float32)
    s = body + 0.3 * click
    place(s, at_sec, gain, pan=0.0)


def synth_snare(at_sec, gain=0.28):
    dur = 0.25
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    # Snappy tonal body (190 Hz)
    tone = np.sin(2.0 * np.pi * 190.0 * t) * np.exp(-t / 0.035)
    # White noise snap with high-pass filtering feel
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32) * np.exp(-t / 0.08)
    s = 0.45 * tone + 0.7 * noise
    place(s, at_sec, gain, pan=0.0)


def synth_hat(at_sec, open_hat=False, gain=0.12, pan=0.2):
    dur = 0.22 if open_hat else 0.05
    decay = 0.09 if open_hat else 0.02
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32)
    # Metallic tone interference
    metal = (np.sin(2.0 * np.pi * 5800.0 * t) + np.sin(2.0 * np.pi * 8400.0 * t)) * 0.2
    s = (noise + metal) * np.exp(-t / decay)
    place(s, at_sec, gain, pan=pan)


def synth_crash(at_sec, gain=0.25, pan=-0.2):
    dur = 1.6
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    noise = rng.uniform(-1.0, 1.0, len(t)).astype(np.float32)
    s = noise * np.exp(-t / 0.45)
    place(s, at_sec, gain, pan=pan)


def synth_bell(at_sec, gain=0.18, pan=0.3):
    """Cartoon bicycle thumb-bell ping-ping."""
    dur = 0.4
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    # Dual ringing high sines
    s1 = np.sin(2.0 * np.pi * 2350.0 * t) * np.exp(-t / 0.15)
    s2 = np.sin(2.0 * np.pi * 2810.0 * t) * np.exp(-t / 0.12)
    s = 0.5 * (s1 + s2)
    place(s, at_sec, gain, pan=pan)
    # Second ping slightly offset
    place(s, at_sec + 0.11, gain * 0.9, pan=pan)


def synth_whistle(at_sec, dur=0.1, freq=1100.0, gain=0.22):
    """Starter referee whistle."""
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    # Slight frequency wobble (trill)
    trill = 1.0 + 0.03 * np.sin(2.0 * np.pi * 32.0 * t)
    s = np.sin(2.0 * np.pi * freq * trill * t)
    # Fast attack and release
    s *= np.minimum(t / 0.01, 1.0) * np.minimum((dur - t) / 0.015, 1.0)
    # Add a touch of airy noise
    air = rng.uniform(-0.15, 0.15, len(t)).astype(np.float32)
    s = (s + air) * np.minimum(t / 0.01, 1.0)
    place(s, at_sec, gain, pan=0.0)


def synth_slide(at_sec, f_start=300.0, f_end=900.0, dur=0.6, gain=0.15):
    """Slapstick slide whistle."""
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    freq = np.linspace(f_start, f_end, len(t))
    phase = 2.0 * np.pi * np.cumsum(freq) / SR
    s = np.sin(phase) * np.minimum(t / 0.03, 1.0) * np.minimum((dur - t) / 0.05, 1.0)
    place(s, at_sec, gain, pan=0.1)


# --- Melodic & Harmonic Synthesizers ---

def midi_to_freq(m):
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def synth_tone(midi, at_sec, length=0.3, voice='marimba', gain=0.08, pan=0.0):
    t = np.arange(int(length * SR), dtype=np.float32) / SR
    f = midi_to_freq(midi)
    if voice == 'marimba':
        s = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.18) + 0.25 * np.sin(2 * np.pi * 3.8 * f * t) * np.exp(-t / 0.04)
        s *= np.minimum(t / 0.003, 1.0)
    elif voice == 'bass':
        # Punchy electric/synth bass with sub & harmonic
        s = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(4 * np.pi * f * t) + 0.15 * np.sin(6 * np.pi * f * t)) * np.exp(-t / 0.28)
        s *= np.minimum(t / 0.004, 1.0)
    elif voice == 'flute':
        # Cheerful agile cartoon lead flute
        vibrato = 0.015 * np.sin(2 * np.pi * 6.0 * t)
        phase = 2 * np.pi * f * (1.0 + vibrato) * t
        s = np.sin(phase) + 0.18 * np.sin(2 * phase) + 0.05 * np.sin(3 * phase)
        s *= np.minimum(t / 0.02, 1.0) * np.minimum((length - t) / 0.04, 1.0)
    elif voice == 'brass':
        # Warm, punchy synth horn
        phase = 2 * np.pi * f * t
        s = sum(np.sin((k + 1) * phase) / (k + 1) ** 0.85 for k in range(5))
        s *= np.minimum(t / 0.03, 1.0) * np.minimum((length - t) / 0.05, 1.0)
    elif voice == 'pizz':
        s = sum(np.sin(2 * np.pi * h * f * t) * np.exp(-t / (0.12 / (1 + 0.1 * h))) / (h ** 1.5) for h in range(1, 8))
        s *= np.minimum(t / 0.002, 1.0)
    elif voice == 'tuba':
        # Comic low oompah tuba
        phase = 2 * np.pi * f * t
        s = (np.sin(phase) + 0.6 * np.sin(2 * phase) + 0.25 * np.sin(3 * phase)) * np.exp(-t / 0.35)
        s *= np.minimum(t / 0.01, 1.0)
    else:  # celesta / glockenspiel
        s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.08)) * np.exp(-t / 0.8)
        s *= np.minimum(t / 0.002, 1.0)

    place(s.astype(np.float32), at_sec, gain, pan)


# --- Score Construction ---
print("Synthesizing energetic Fluffies racing score...")

# 1. 0s - 10s: Opener is completely silent on this track.
# 2. 10s - 16s: S01 The Starting Line - Ticking clock, pizzicato anticipation
t_start = 10.0
for b in range(14):
    t_beat = t_start + b * BEAT
    if t_beat >= 16.0:
        break
    # Ticking pizzicato
    synth_tone(74 if b % 2 == 0 else 69, t_beat, length=0.15, voice='pizz', gain=0.06, pan=-0.2)
    synth_hat(t_beat, open_hat=False, gain=0.08, pan=0.3)
    synth_hat(t_beat + SIXTEENTH * 2, open_hat=False, gain=0.05, pan=0.3)

# 3. 16s - 21s: S02 The Countdown & Whistle
# Three whistle pips at 17.0, 18.0, 19.0, then long GO whistle at 20.0
synth_whistle(17.0, dur=0.12, freq=1050.0, gain=0.25)
synth_tone(74, 17.0, length=0.15, voice='celesta', gain=0.09)

synth_whistle(18.0, dur=0.12, freq=1050.0, gain=0.25)
synth_tone(74, 18.0, length=0.15, voice='celesta', gain=0.09)

synth_whistle(19.0, dur=0.12, freq=1050.0, gain=0.25)
synth_tone(74, 19.0, length=0.15, voice='celesta', gain=0.09)

# Snare roll build up from 19.2 to 20.0
snare_gains = np.linspace(0.08, 0.28, 12)
for k, sub in enumerate(np.linspace(19.2, 19.9, 12)):
    synth_snare(sub, gain=float(snare_gains[k]))

# Big GO whistle at 20.0
synth_whistle(20.0, dur=0.45, freq=1600.0, gain=0.35)
synth_tone(86, 20.0, length=0.5, voice='celesta', gain=0.15)
synth_crash(20.0, gain=0.28)

# 4. 21s - 69s: ACT 2 - Full Racing Beats & Themes
# Section A: 21s - 39s (S03-S05 Village Sprint: Bobo & Lulu) - Key: D Major (D=62)
# Root notes: D (50/62), G (43/55), A (45/57), Bm (47/59)
bar_start = 21.0
current_time = bar_start

# Main melody riff (D Major): D5, F#5, A5, B5, A5, F#5, E5, D5
MELODY_A = [
    (74, 0.0, 0.35), (78, 1.0, 0.35), (81, 1.75, 0.25), (83, 2.25, 0.4),
    (81, 3.0, 0.35), (78, 4.0, 0.35), (76, 5.0, 0.35), (74, 6.0, 0.6)
]

MELODY_B = [
    (78, 0.0, 0.35), (81, 1.0, 0.35), (86, 2.0, 0.5), (83, 3.0, 0.35),
    (81, 4.0, 0.35), (78, 5.0, 0.35), (76, 5.75, 0.25), (74, 6.25, 0.6)
]


def play_racing_beat_bar(bar_t, key_root=50, style='full'):
    """Plays 1 full 4-beat bar at 138 BPM."""
    # Beats 0, 1, 2, 3
    for b in range(4):
        bt = bar_t + b * BEAT
        if style == 'full':
            # Kick on 1 and 3 (b=0, 2), snare on 2 and 4 (b=1, 3)
            if b % 2 == 0:
                synth_kick(bt, gain=0.34)
            else:
                synth_snare(bt, gain=0.26)
            # Hi-hats on all 16ths with off-beat accent
            for s in range(4):
                st = bt + s * SIXTEENTH
                is_up = (s == 2)
                synth_hat(st, open_hat=is_up, gain=0.10 if is_up else 0.05, pan=0.25)
        elif style == 'chug':  # Pebble's steady comic oompah
            if b % 2 == 0:
                synth_kick(bt, gain=0.28)
                synth_tone(key_root - 12, bt, length=0.3, voice='tuba', gain=0.12, pan=-0.2)
            else:
                synth_snare(bt, gain=0.18)
                synth_tone(key_root + 4, bt, length=0.18, voice='pizz', gain=0.08, pan=0.2)
                synth_tone(key_root + 7, bt, length=0.18, voice='pizz', gain=0.08, pan=0.25)
            synth_hat(bt + SIXTEENTH * 2, open_hat=True, gain=0.08, pan=0.2)

        # Funk bassline on 8th notes (style == 'full')
        if style == 'full':
            root = key_root
            synth_tone(root, bt, length=0.2, voice='bass', gain=0.11, pan=-0.1)
            synth_tone(root + 12 if b % 2 == 1 else root + 7, bt + SIXTEENTH * 2, length=0.18, voice='bass', gain=0.09, pan=-0.1)


# Fill Act 2 (21s to 69s):
t = 21.0
bar_idx = 0
roots = [50, 50, 55, 45, 50, 50, 55, 45]  # D, D, G, A progression

while t < 69.0:
    cur_root = roots[bar_idx % len(roots)]
    # S06 / S07 / S10: Pebble's steady chug or comic moments
    is_pebble_section = (45.0 <= t < 51.0) or (63.0 <= t < 69.0)
    style = 'chug' if is_pebble_section else 'full'

    play_racing_beat_bar(t, key_root=cur_root, style=style)

    # Lead Melody & Accents
    if not is_pebble_section:
        # Play melodic flute/brass leads
        if bar_idx % 4 == 0:
            for note_midi, beat_offset, dur in MELODY_A:
                synth_tone(note_midi, t + beat_offset * BEAT, length=dur, voice='flute', gain=0.09, pan=0.1)
                synth_tone(note_midi, t + beat_offset * BEAT, length=dur, voice='marimba', gain=0.06, pan=-0.15)
        elif bar_idx % 4 == 2:
            for note_midi, beat_offset, dur in MELODY_B:
                synth_tone(note_midi, t + beat_offset * BEAT, length=dur, voice='brass', gain=0.08, pan=-0.1)
                synth_tone(note_midi, t + beat_offset * BEAT, length=dur, voice='marimba', gain=0.05, pan=0.15)

    # Specific sound flourishes:
    # Bicycle bell in Bobo's shot (around 28.5s and 34.0s)
    if 28.0 <= t < 29.5 or 34.0 <= t < 35.5:
        synth_bell(t + 0.3, gain=0.22, pan=0.3)

    # Bridge Hop glissando at 53.0s
    if 53.0 <= t < 54.5:
        synth_slide(t, f_start=400.0, f_end=1200.0, dur=0.45, gain=0.16)

    # Daisy drift slide whistle down at 59.5s
    if 59.0 <= t < 60.5:
        synth_slide(t + 0.2, f_start=1100.0, f_end=350.0, dur=0.55, gain=0.18)

    t += 4 * BEAT
    bar_idx += 1

# 5. 69s - 82s: ACT 3 - The Final Sprint & Finish Line (Modulate to E Major: E=52 / 64)
# Double time driving feel, soaring triumphant brass fanfare!
t_sprint = 69.0
synth_crash(t_sprint, gain=0.3)

FANFARE = [
    (76, 0.0, 0.3), (80, 0.75, 0.25), (83, 1.25, 0.25), (88, 1.75, 0.6),  # E - G# - B - E
    (85, 3.0, 0.4), (88, 4.0, 0.8), (92, 5.5, 1.2)                         # D# - E - G# high climax!
]

bar_sprint = 0
sprint_roots = [52, 52, 57, 47]  # E, E, A, B progression

while t_sprint < 82.0:
    cur_root = sprint_roots[bar_sprint % len(sprint_roots)]
    # Four-on-the-floor kick during the final sprint!
    for b in range(4):
        bt = t_sprint + b * BEAT
        synth_kick(bt, gain=0.38)
        if b % 2 == 1:
            synth_snare(bt, gain=0.30)
        # Galloping hi-hat
        for s in range(4):
            synth_hat(bt + s * SIXTEENTH, open_hat=(s == 2), gain=0.11, pan=0.2)
        # Galloping bass
        synth_tone(cur_root, bt, length=0.18, voice='bass', gain=0.14, pan=0.0)
        synth_tone(cur_root + 12, bt + SIXTEENTH * 2, length=0.18, voice='bass', gain=0.12, pan=0.0)

    # Soaring Brass Fanfare
    if bar_sprint == 0:
        for note_midi, beat_offset, dur in FANFARE:
            synth_tone(note_midi, t_sprint + beat_offset * BEAT, length=dur, voice='brass', gain=0.12, pan=-0.1)
            synth_tone(note_midi, t_sprint + beat_offset * BEAT, length=dur, voice='flute', gain=0.08, pan=0.15)
            synth_tone(note_midi + 12, t_sprint + beat_offset * BEAT, length=dur, voice='celesta', gain=0.07, pan=0.2)

    # Finish Line Ribbon Burst at ~78.0s
    if 77.5 <= t_sprint < 79.5:
        synth_crash(t_sprint + 0.2, gain=0.35)
        synth_bell(t_sprint + 0.4, gain=0.25, pan=-0.2)
        synth_bell(t_sprint + 0.7, gain=0.25, pan=0.3)

    t_sprint += 4 * BEAT
    bar_sprint += 1

# 6. 82s - 89s: S13 Victory Celebration Bounce & Outro
t_outro = 82.0
synth_crash(t_outro, gain=0.3)
while t_outro < 89.0:
    for b in range(4):
        bt = t_outro + b * BEAT
        if bt >= 89.0:
            break
        if b % 2 == 0:
            synth_kick(bt, gain=0.30)
            synth_tone(52, bt, length=0.2, voice='bass', gain=0.10)
        else:
            synth_snare(bt, gain=0.22)
            synth_tone(64, bt, length=0.15, voice='bass', gain=0.08)
        synth_hat(bt, open_hat=False, gain=0.08)
        synth_hat(bt + SIXTEENTH * 2, open_hat=True, gain=0.08)

        # Joyful bouncy arpeggios
        synth_tone(76 + (b * 4) % 12, bt, length=0.2, voice='marimba', gain=0.08)
        synth_tone(88, bt + SIXTEENTH * 2, length=0.2, voice='celesta', gain=0.07)

    t_outro += 4 * BEAT

# Final triumphant stinger chord at 88.5s
synth_tone(52, 88.5, length=1.2, voice='bass', gain=0.15)
synth_tone(64, 88.5, length=1.5, voice='brass', gain=0.12)
synth_tone(68, 88.5, length=1.5, voice='brass', gain=0.11)
synth_tone(71, 88.5, length=1.5, voice='brass', gain=0.11)
synth_tone(76, 88.5, length=1.8, voice='flute', gain=0.10)
synth_tone(88, 88.5, length=2.0, voice='celesta', gain=0.12)
synth_crash(88.5, gain=0.35)

# --- Normalize & Export ---
# Smooth fade out over last 0.8 seconds
fade_start = int((TOTAL_SECONDS - 0.8) * SR)
fade_len = len(track) - fade_start
if fade_len > 0:
    fade_env = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)[:, np.newaxis]
    track[fade_start:] *= fade_env

peak = np.max(np.abs(track))
if peak > 0.0:
    track = (track / peak) * 0.92  # Leave 0.8 dB headroom for ducking and mastering

out_wav = OUT / 'scooter_race_original_score.wav'
pcm = (track * 32767.0).astype(np.int16)
with wave.open(str(out_wav), 'wb') as stream:
    stream.setnchannels(2)
    stream.setsampwidth(2)
    stream.setframerate(SR)
    stream.writeframes(pcm.tobytes())

print(f"Energetic original score synthesized successfully: {out_wav} ({TOTAL_SECONDS}s, peak {peak:.2f})")
