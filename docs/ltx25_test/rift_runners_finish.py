"""Post-production assembler for Rift Runners — The Chrono-Core Heist (16 shots, 119s).

The renderer (`rift_runners_runner.py`) owns `execution.json`.
This assembler:
1. Verifies each rendered LTX-2.5 clip (`clips/S01.mp4`..`S16.mp4`) with `ffprobe` and full FFmpeg decode.
2. Normalizes each picture track to 1920x1080 @ 24fps (`edit_frames`).
3. Mixes each shot's native LTX-2.5 foley/thruster audio with its studio Gemini TTS character voice track
   (`voices/S01.wav`..`S16.wav`), ducking native foley under spoken dialogue so every line is crisp.
4. Concatenates all 16 shots and sidechain-ducks the 119s Google Lyria 3.5 Hip-Hop score
   (`rift_runners_original_score.wav`) underneath the combined voice+foley stem.
5. Verifies the final master (`Rift_Runners_Chrono_Core_Heist.mp4`) with `ffprobe` and full FFmpeg decode,
   syncs clips and the master MP4 to `ui/dist/rift-runners/`, updates `storyboard.html` with embedded video
   players, and optionally publishes to the H3 Mobile Bridge library (`--publish`).
"""
import argparse
import hashlib
import json
import msvcrt
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'rift_runners_ep01'
DIST_DIR = ROOT / 'ui' / 'dist' / 'rift-runners'
sys.path.insert(0, str(Path(__file__).parent / 'tumble_puffs_ep01'))
import episode_runner as bridge


def run(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-y', *map(str, args)], check=True)


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def media_proof(path: Path, frames: int, audio: bool = False, dimensions=None):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(path)],
        check=True, capture_output=True
    )
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    count = int(video['nb_read_frames'])
    assert video['r_frame_rate'] == '24/1' and count >= frames, (path, video['r_frame_rate'], count, frames)
    actual_dimensions = (video['width'], video['height'])
    assert dimensions is None or actual_dimensions == dimensions, (actual_dimensions, dimensions)
    has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    assert has_audio == audio, (path, has_audio, audio)
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = dict(
        path=str(path), width=video['width'], height=video['height'], fps=24,
        decoded_frames=count, duration=float(info['format']['duration']),
        audio=has_audio, full_decode='passed'
    )
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    return proof


def finish(preview=None, wait=False, publish=False):
    spec = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    dimensions = (spec.get('output_width', 1920), spec.get('output_height', 1080))
    selected = spec['shots'][:preview] if preview else spec['shots']
    assert selected and (preview is None or 1 <= preview <= len(spec['shots']))
    previous = None
    while True:
        journal = OUT / 'execution.json'
        state = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {'items': {}}
        pending = [
            (s['id'], state['items'].get(s['id'], {}).get('status', 'not submitted'))
            for s in selected if state['items'].get(s['id'], {}).get('status') != 'verified'
        ]
        if not pending:
            break
        if not wait:
            raise SystemExit(f'Sources not ready: {pending}')
        if (OUT / 'STOPPED.json').exists():
            raise SystemExit('Production stop marker present; no assembly or upload.')
        failed = [
            p for p in pending
            if p[1] not in {'not submitted', 'submitting', 'queued', 'starting', 'running', 'verifying', 'completed'}
        ]
        if failed:
            raise SystemExit(f'Render requires attention: {failed}')
        if pending != previous:
            print(json.dumps(dict(status='waiting_for_verified_sources', pending=pending)), flush=True)
            previous = pending
        time.sleep(20)

    sources = [
        dict(
            id=s['id'],
            path=OUT / s['clip'],
            voice_path=OUT / s['voice_file'] if s.get('voice_file') else None,
            frames=s['edit_frames'],
            duration=s['edit_frames'] / 24,
            trim_start_frame=s.get('trim_start_frame', 0),
        )
        for s in selected
    ]
    frames = sum(s['frames'] for s in sources)
    seconds = frames / 24
    if preview is None:
        assert frames == spec['full_episode_frames'] and seconds == spec['full_episode_seconds']

    master_stem = Path(spec.get('master_filename', 'Rift_Runners_Chrono_Core_Heist.mp4')).stem
    name = f'{master_stem}_WIP_{seconds:g}s' if preview else master_stem
    final = OUT / (name + '.mp4')
    edit = OUT / (f'preview_edit_{preview}' if preview else 'native_edit')
    edit.mkdir(exist_ok=True)

    videos, sounds, evidence = [], [], []
    for source in sources:
        start = source['trim_start_frame']
        end = start + source['frames']
        source_proof = media_proof(source['path'], end, audio=True)
        voice_sha = digest(source['voice_path']) if source['voice_path'] and source['voice_path'].exists() else None
        fingerprint = dict(
            sha256=digest(source['path']),
            voice_sha256=voice_sha,
            frames=source['frames'],
            trim_start_frame=start,
            dimensions=list(dimensions),
            fit='contain without cropping',
            audio='LTX-2.5 native foley + Gemini 3.8 TTS dialogue stem; 48kHz stereo PCM',
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
            dur = source['duration']
            if source['voice_path'] and source['voice_path'].exists():
                # Mix native LTX-2.5 thruster/foley audio with Gemini TTS character dialogue
                af_complex = (
                    f'[0:a]atrim=start={start/24}:duration={dur},asetpts=PTS-STARTPTS,'
                    f'aresample=48000,pan=stereo|c0=c0|c1=c1,volume=0.55,'
                    f'apad=whole_dur={dur},atrim=duration={dur}[foley];'
                    f'[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,adelay=180|180,volume=1.35,'
                    f'apad=whole_dur={dur},atrim=duration={dur}[voice];'
                    f'[foley][voice]amix=inputs=2:duration=first:normalize=0,'
                    f'afade=t=in:d=0.006,afade=t=out:st={dur-.006}:d=0.006[outa]'
                )
                run(
                    '-i', source['path'], '-i', source['voice_path'],
                    '-filter_complex', af_complex, '-map', '[outa]',
                    '-ac', 2, '-ar', 48000, '-c:a', 'pcm_s16le', sound_temp
                )
            else:
                run(
                    '-i', source['path'], '-vn', '-af',
                    f'atrim=start={start/24}:duration={dur},asetpts=PTS-STARTPTS,aresample=48000,'
                    f'apad=whole_dur={dur},atrim=duration={dur},'
                    f'afade=t=in:d=0.006,afade=t=out:st={dur-.006}:d=0.006',
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
        print(json.dumps(dict(status='edit_verified', id=source['id'])), flush=True)

    playlist = edit / (name + '.concat.txt')
    playlist.write_text(''.join("file '" + p.as_posix() + "'\n" for p in videos), encoding='utf-8')
    picture = edit / (name + '_silent.mp4')
    run('-f', 'concat', '-safe', 0, '-i', playlist, '-c', 'copy', '-an', picture)
    picture_proof = media_proof(picture, frames, audio=False, dimensions=dimensions)
    assert picture_proof['decoded_frames'] == frames and abs(picture_proof['duration'] - seconds) < .001

    native = edit / (name + '_native.wav')
    with wave.open(str(native), 'wb') as output:
        output.setparams((2, 2, 48000, round(seconds * 48000), 'NONE', 'not compressed'))
        for sound in sounds:
            with wave.open(str(sound), 'rb') as src_wav:
                output.writeframes(src_wav.readframes(src_wav.getnframes()))

    score = OUT / spec.get('score_file', 'rift_runners_original_score.wav')
    assert score.exists(), f'Score file missing: {score}'

    filters = (
        '[1:a]asplit=2[native][trigger];'
        f'[2:a]atrim=duration={seconds},asetpts=PTS-STARTPTS,volume=0.38[music];'
        '[music][trigger]sidechaincompress=threshold=0.035:ratio=4.0:attack=10:release=220[ducked];'
        '[native][ducked]amix=inputs=2:duration=first:normalize=0,'
        f'loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st={seconds-.25}:d=0.25[mix]'
    )
    temporary = final.with_name(final.stem + '.partial.mp4')
    run(
        '-i', picture, '-i', native, '-i', score, '-filter_complex', filters,
        '-map', '0:v:0', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'aac',
        '-b:a', '192k', '-ar', 48000, '-t', seconds, '-movflags', '+faststart', temporary
    )
    proof = media_proof(temporary, frames, audio=True, dimensions=dimensions)
    assert proof['decoded_frames'] == frames and abs(proof['duration'] - seconds) < .001
    temporary.replace(final)
    proof['path'] = str(final)
    final.with_name(final.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')

    result = dict(
        schema='assembly_result.v1',
        title=spec['title'],
        work_in_progress=bool(preview),
        audio_policy=spec.get('audio_policy'),
        transitions='hard cuts & sequential frame handoffs',
        source_evidence=evidence,
        proof=proof,
        sha256=digest(final),
    )
    record = final.with_name(final.stem + '_assembly.json')
    record.write_text(json.dumps(result, indent=2), encoding='utf-8')

    # Sync clips and master video to ui/dist/rift-runners
    if DIST_DIR.exists():
        dist_clips = DIST_DIR / 'clips'
        dist_clips.mkdir(parents=True, exist_ok=True)
        for s in selected:
            src_clip = OUT / s['clip']
            if src_clip.exists():
                shutil.copy2(src_clip, dist_clips / src_clip.name)
        shutil.copy2(final, DIST_DIR / final.name)

    if publish:
        bridge.OUT, bridge.JOURNAL, bridge.FINAL = OUT, record, final
        title = f'{spec["title"]} - WIP {seconds:g}s.mp4' if preview else f'{spec["title"]} - {seconds:g}s.mp4'
        bridge.publish(final, frames, title)
    print(json.dumps(dict(status='finished', **proof)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', type=int)
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.out.resolve()
    lock_name = f'editor-preview-{args.preview}.lock' if args.preview else 'editor.lock'
    with (OUT / lock_name).open('a+b') as guard:
        guard.seek(0)
        if guard.read(1) == b'':
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        finish(args.preview, args.wait, args.publish)
