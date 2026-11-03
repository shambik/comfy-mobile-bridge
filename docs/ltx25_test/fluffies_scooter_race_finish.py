"""Fluffies — The Big Scooter Race: Broadcast Assembly with Motion Trims & Outro.

Assembles:
1. Series Intro (1002475080.mp4) - 10.0s (240 frames) with original theme.
2. Race Story (S01 - S13) - Trimmed to start DURING active motion (static freeze lead-in removed):
   - S01: trim 18 frames (starts on active pre-race bounce)
   - S02: trim 14 frames (starts on whistle drop & flag wave)
   - S03: trim 15 frames (starts on explosive forward sprint)
   - S04: trim 9 frames (starts on aerodynamic tuck & bell ding)
   - S05: trim 22 frames (starts on effortless gliding motion)
   - S06: trim 10 frames (starts on aggressive cobblestone lean)
   - S07: trim 20 frames (starts on brisk trike pedaling)
   - S08: trim 18 frames (starts on airborne bridge leap)
   - S09: trim 8 frames (starts on dynamic spinout into daisies)
   - S10: trim 12 frames (starts on cheery waving motion)
   - S11: trim 12 frames (starts on three-way acceleration)
   - S12: trim 30 frames (starts on ribbon snap & confetti explosion)
   - S13: trim 12 frames (starts on synchronized victory bounce)
3. Series Outro (1002475708.mp4) - 10.0s (240 frames) with original theme.
4. Audio:
   - Intro: original intro sound
   - Story: native nonverbal reactions + motion-aligned 138 BPM orchestral race score (ducked)
   - Outro: original outro sound
"""
import argparse
import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EP_DIR = ROOT / 'state' / 'fluffies_ep04_scooter_race'

MOTION_TRIMS = {
    'S01': {'trim_start': 18, 'frames': 127},
    'S02': {'trim_start': 14, 'frames': 107},
    'S03': {'trim_start': 15, 'frames': 130},
    'S04': {'trim_start': 9,  'frames': 136},
    'S05': {'trim_start': 22, 'frames': 123},
    'S06': {'trim_start': 10, 'frames': 135},
    'S07': {'trim_start': 20, 'frames': 125},
    'S08': {'trim_start': 18, 'frames': 127},
    'S09': {'trim_start': 8,  'frames': 137},
    'S10': {'trim_start': 12, 'frames': 133},
    'S11': {'trim_start': 12, 'frames': 157},
    'S12': {'trim_start': 30, 'frames': 115},
    'S13': {'trim_start': 12, 'frames': 157},
}


def run(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-y', *map(str, args)], check=True)


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def media_proof(path, frames, audio=False, dimensions=None):
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-count_frames', '-show_streams',
        '-show_format', '-of', 'json', str(path)
    ], check=True, capture_output=True)
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    count = int(video['nb_read_frames'])
    assert video['r_frame_rate'] == '24/1', f"Expected 24 fps, got {video['r_frame_rate']}"
    assert count >= frames, f"Frame count mismatch: {count} < {frames}"
    actual_dimensions = (video['width'], video['height'])
    assert dimensions is None or actual_dimensions == dimensions, f"Dimensions mismatch: {actual_dimensions} != {dimensions}"
    has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    assert has_audio == audio, f"Audio presence mismatch on {path}: expected {audio}, got {has_audio}"
    # Full ffmpeg decode proof
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = dict(
        path=str(path), width=video['width'], height=video['height'], fps=24,
        decoded_frames=count, duration=float(info['format']['duration']),
        audio=has_audio, full_decode='passed'
    )
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    return proof


def assemble():
    dimensions = (1920, 1080)
    spec = json.loads((EP_DIR / 'manifest.json').read_text(encoding='utf-8'))

    intro_path = EP_DIR / 'refs' / '1002475080.mp4'
    outro_path = EP_DIR / 'refs' / '1002475708.mp4'
    assert intro_path.exists(), f"Intro missing at {intro_path}"
    assert outro_path.exists(), f"Outro missing at {outro_path}"

    sources = []
    # 1. Intro (10.0s = 240 frames)
    sources.append(dict(
        id='Intro', path=intro_path, frames=240, duration=10.0, trim_start_frame=0
    ))

    # 2. Story shots S01 through S13 with motion trims
    for i in range(1, 14):
        shot_id = f'S{i:02d}'
        clip_path = EP_DIR / f'clips/{shot_id}.mp4'
        assert clip_path.exists(), f"Clip {shot_id} missing at {clip_path}"
        trim_cfg = MOTION_TRIMS[shot_id]
        sources.append(dict(
            id=shot_id,
            path=clip_path,
            frames=trim_cfg['frames'],
            duration=trim_cfg['frames'] / 24.0,
            trim_start_frame=trim_cfg['trim_start']
        ))

    # 3. Outro (10.0s = 240 frames)
    sources.append(dict(
        id='Outro', path=outro_path, frames=240, duration=10.0, trim_start_frame=0
    ))

    total_frames = sum(s['frames'] for s in sources)
    total_seconds = total_frames / 24.0

    edit = EP_DIR / 'motion_trimmed_edit'
    edit.mkdir(parents=True, exist_ok=True)

    videos, sounds, evidence = [], [], []

    print(f"Conforming {len(sources)} segments (total {total_frames} frames / {total_seconds:.2f}s)...")
    for source in sources:
        start = source['trim_start_frame']
        end = start + source['frames']
        source_proof = media_proof(source['path'], end, audio=True)
        fingerprint = dict(
            sha256=digest(source['path']), frames=source['frames'], trim_start_frame=start,
            dimensions=list(dimensions), fit='contain without cropping', audio='native stereo PCM; 6ms edge fades'
        )
        target = edit / (source['id'] + '.mp4')
        sound = edit / (source['id'] + '.wav')
        stamp = edit / (source['id'] + '.source.json')
        cached = json.loads(stamp.read_text(encoding='utf-8')) if stamp.exists() else None

        if cached != fingerprint or not target.exists() or not sound.exists():
            picture_temp = target.with_name(target.stem + '.partial.mp4')
            sound_temp = sound.with_name(sound.stem + '.partial.wav')
            run(
                '-i', source['path'], '-an', '-vf',
                f'trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,'
                f'scale={dimensions[0]}:{dimensions[1]}:force_original_aspect_ratio=decrease,'
                f'pad={dimensions[0]}:{dimensions[1]}:(ow-iw)/2:(oh-ih)/2,setsar=1',
                '-r', 24, '-frames:v', source['frames'], '-c:v', 'libx264',
                '-threads', 4, '-preset', 'fast', '-crf', 17, '-pix_fmt', 'yuv420p',
                '-video_track_timescale', 12288, picture_temp
            )
            run(
                '-i', source['path'], '-vn', '-af',
                f'atrim=start={start/24.0}:duration={source["duration"]},asetpts=PTS-STARTPTS,aresample=48000,'
                f'apad=whole_dur={source["duration"]},atrim=duration={source["duration"]},'
                f'afade=t=in:d=0.006,afade=t=out:st={source["duration"]-0.006}:d=0.006',
                '-ac', 2, '-ar', 48000, '-c:a', 'pcm_s16le', sound_temp
            )
            picture_temp.replace(target)
            sound_temp.replace(sound)
            stamp.write_text(json.dumps(fingerprint, indent=2), encoding='utf-8')

        picture_proof = media_proof(target, source['frames'], audio=False, dimensions=dimensions)
        assert picture_proof['decoded_frames'] == source['frames']
        with wave.open(str(sound), 'rb') as stream:
            assert (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) == (2, 2, 48000)
            assert stream.getnframes() == round(source['duration'] * 48000)

        evidence.append(dict(id=source['id'], source=source_proof, edit=picture_proof, fingerprint=fingerprint))
        videos.append(target)
        sounds.append(sound)
        print(f"Segment verified: {source['id']} ({source['frames']} frames, {source['duration']:.2f}s)")

    # 4. Concatenate picture
    playlist = edit / 'full_episode.concat.txt'
    playlist.write_text(''.join("file '" + p.as_posix() + "'\n" for p in videos), encoding='utf-8')
    picture = edit / 'full_episode_silent.mp4'
    run('-f', 'concat', '-safe', 0, '-i', playlist, '-c', 'copy', '-an', picture)
    picture_proof = media_proof(picture, total_frames, audio=False, dimensions=dimensions)
    assert picture_proof['decoded_frames'] == total_frames and abs(picture_proof['duration'] - total_seconds) < 0.01

    # 5. Concatenate native audio
    native = edit / 'full_episode_native.wav'
    with wave.open(str(native), 'wb') as output:
        output.setparams((2, 2, 48000, round(total_seconds * 48000), 'NONE', 'not compressed'))
        for sound in sounds:
            with wave.open(str(sound), 'rb') as src:
                output.writeframes(src.readframes(src.getnframes()))

    # 6. Original timed score
    score_path = EP_DIR / 'scooter_race_motion_timed_score.wav'
    assert score_path.exists(), f"Motion-timed score missing at {score_path}"

    # 7. Mix audio with ducking
    filters = (
        '[1:a]asplit=2[native][trigger];'
        f'[2:a]atrim=duration={total_seconds},asetpts=PTS-STARTPTS,volume=0.55[music];'
        '[music][trigger]sidechaincompress=threshold=0.045:ratio=3.5:attack=12:release=180[ducked];'
        '[native][ducked]amix=inputs=2:duration=first:normalize=0,'
        f'loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st={total_seconds-0.18}:d=0.18[mix]'
    )

    final_master = EP_DIR / 'Fluffies_The_Big_Scooter_Race.mp4'
    temporary = final_master.with_name(final_master.stem + '.partial.mp4')
    print("Muxing final master MP4...")
    run(
        '-i', picture, '-i', native, '-i', score_path, '-filter_complex', filters,
        '-map', '0:v:0', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'aac',
        '-b:a', '192k', '-ar', 48000, '-t', total_seconds, '-movflags', '+faststart', temporary
    )
    proof = media_proof(temporary, total_frames, audio=True, dimensions=dimensions)
    assert proof['decoded_frames'] == total_frames and abs(proof['duration'] - total_seconds) < 0.01
    temporary.replace(final_master)
    proof['path'] = str(final_master)
    final_master.with_name(final_master.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')

    result = dict(
        schema='assembly_result.v1',
        title=spec['title'],
        motion_trimmed=True,
        has_intro=True,
        has_outro=True,
        intro_file='1002475080.mp4',
        outro_file='1002475708.mp4',
        audio_policy='Series intro theme in full (10s) + native nonverbal reactions ducked with 138 BPM original orchestral race score (71.2s) + series outro theme in full (10s).',
        transitions='Immediate-motion hard cuts (leading static freezes trimmed)',
        picture_policy='1080p Full HD (1920x1080) 24fps exact conform',
        total_frames=total_frames,
        duration_seconds=total_seconds,
        source_evidence=evidence,
        proof=proof,
        sha256=digest(final_master)
    )
    record = final_master.with_name(final_master.stem + '_assembly.json')
    record.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f"Broadcast master complete: {final_master} ({total_frames} frames, {total_seconds:.2f}s)")
    return final_master


if __name__ == '__main__':
    assemble()
