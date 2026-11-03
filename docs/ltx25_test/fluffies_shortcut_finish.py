"""Hard-cut native-audio Fluffies assembly with original instrumental underscore.

The renderer owns execution.json. This editor writes separate assembly records,
preserves source files, never submits/cancels jobs and never retries an uncertain
vault upload. --preview N makes an explicitly named work-in-progress prefix.
"""
import argparse
import hashlib
import json
import msvcrt
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'fluffies_ep01_shortcut'
sys.path.insert(0, str(Path(__file__).parent / 'tumble_puffs_ep01'))
import episode_runner as bridge


def run(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-y', *map(str, args)], check=True)


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def media_proof(path, frames, audio=False, dimensions=None):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                             '-show_format', '-of', 'json', str(path)], check=True, capture_output=True)
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    count = int(video['nb_read_frames'])
    assert video['r_frame_rate'] == '24/1' and count >= frames
    actual_dimensions = (video['width'], video['height'])
    assert dimensions is None or actual_dimensions == dimensions
    has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
    assert has_audio == audio
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = dict(path=str(path), width=video['width'], height=video['height'], fps=24,
                 decoded_frames=count, duration=float(info['format']['duration']),
                 audio=has_audio, full_decode='passed')
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2))
    return proof


def finish(preview=None, wait=False, publish=False, full_scenes=False):
    spec = json.loads((OUT / 'manifest.json').read_text(encoding='utf-8'))
    dimensions = (spec.get('output_width', 1600), spec.get('output_height', 896))
    selected = spec['shots'][:preview] if preview else spec['shots']
    assert selected and (preview is None or 1 <= preview <= len(spec['shots']))
    previous = None
    while True:
        journal = OUT / 'execution.json'
        state = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else {'items': {}}
        pending = [(s['id'], state['items'].get(s['id'], {}).get('status', 'not submitted'))
                   for s in selected if state['items'].get(s['id'], {}).get('status') != 'verified']
        if not pending:
            break
        if not wait:
            raise SystemExit(f'Sources not ready: {pending}')
        if (OUT / 'STOPPED.json').exists():
            raise SystemExit('Production stop marker present; no assembly or upload.')
        failed = [p for p in pending if p[1] not in {'not submitted', 'submitting', 'queued', 'starting', 'running', 'verifying', 'completed'}]
        if failed:
            raise SystemExit(f'Render requires attention: {failed}')
        if pending != previous:
            print(json.dumps(dict(status='waiting_for_verified_sources', pending=pending)), flush=True)
            previous = pending
        time.sleep(20)

    sources = [dict(id='Intro', path=ROOT / spec['intro'], frames=spec.get('intro_frames', 192),
                    duration=spec.get('intro_seconds', 8), trim_start_frame=0)]
    sources += [dict(id=s['id'], path=OUT / s['clip'], frames=s['edit_frames'],
                     duration=s['edit_frames']/24, trim_start_frame=s.get('trim_start_frame', 0)) for s in selected]
    for source in sources:
        source['score_duration'] = source['duration']
        if full_scenes:
            proof = media_proof(source['path'], 1, audio=True)
            source.update(frames=proof['decoded_frames'], duration=proof['decoded_frames']/24,
                          trim_start_frame=0, source_proof=proof)
    frames = sum(s['frames'] for s in sources)
    seconds = frames / 24
    if preview is None and not full_scenes:
        assert frames == spec['full_episode_frames'] and seconds == spec['full_episode_seconds']
    name = f'{Path(spec.get("master_filename", "Fluffies_The_Great_Shortcut_120s.mp4")).stem}_WIP_{seconds:g}s' if preview else Path(spec.get('master_filename', 'Fluffies_The_Great_Shortcut_120s.mp4')).stem
    if full_scenes:
        stem = spec.get('full_scenes_stem', 'Fluffies_The_Wobbly_Surprise')
        name = f'{stem}_Full_Scenes_{frames}frames' + (f'_WIP_{preview}' if preview else '')
    final = OUT / (name + '.mp4')
    edit = OUT / (('full_scenes_' if full_scenes else '') + (f'preview_edit_{preview}' if preview else 'native_edit'))
    edit.mkdir(exist_ok=True)
    videos, sounds, evidence = [], [], []
    for source in sources:
        start = source['trim_start_frame']
        end = start + source['frames']
        source_proof = source.get('source_proof') or media_proof(source['path'], end, audio=True)
        fingerprint = dict(sha256=digest(source['path']), frames=source['frames'], trim_start_frame=start,
                           dimensions=dimensions, fit='contain without cropping', audio='native stereo PCM; 6ms edge fades')
        # JSON serializes tuples as lists; use the serialized representation for cache comparisons.
        fingerprint['dimensions'] = list(dimensions)
        target = edit / (source['id'] + '.mp4')
        sound = edit / (source['id'] + '.wav')
        stamp = edit / (source['id'] + '.source.json')
        cached = json.loads(stamp.read_text()) if stamp.exists() else None
        if cached != fingerprint or not target.exists() or not sound.exists():
            picture_temp = target.with_name(target.stem + '.partial.mp4')
            sound_temp = sound.with_name(sound.stem + '.partial.wav')
            run('-i', source['path'], '-an', '-vf',
                f'trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,'
                f'scale={dimensions[0]}:{dimensions[1]}:force_original_aspect_ratio=decrease,'
                f'pad={dimensions[0]}:{dimensions[1]}:(ow-iw)/2:(oh-ih)/2,setsar=1',
                '-r', 24, '-frames:v', source['frames'], '-c:v', 'libx264',
                '-threads', 4, '-preset', 'fast', '-crf', 17, '-pix_fmt', 'yuv420p',
                '-video_track_timescale', 12288, picture_temp)
            run('-i', source['path'], '-vn', '-af',
                f'atrim=start={start/24}:duration={source["duration"]},asetpts=PTS-STARTPTS,aresample=48000,'
                f'apad=whole_dur={source["duration"]},atrim=duration={source["duration"]},'
                f'afade=t=in:d=0.006,afade=t=out:st={source["duration"]-.006}:d=0.006',
                '-ac', 2, '-ar', 48000, '-c:a', 'pcm_s16le', sound_temp)
            picture_temp.replace(target)
            sound_temp.replace(sound)
            stamp.write_text(json.dumps(fingerprint, indent=2))
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
            with wave.open(str(sound), 'rb') as source:
                output.writeframes(source.readframes(source.getnframes()))
    score = OUT / spec.get('score_file', 'shortcut_original_score_120s.wav')
    assert score.exists(), 'Create the manifest-specified original score with the bundled numpy Python before assembly.'
    if full_scenes:
        # Keep each existing musical cue with its scene. Only the underscore is
        # stretched, with pitch preserved; picture and native sound stay at 1x.
        original_score = score
        score = edit / 'full_scenes_score.wav'
        score_start = 0
        with wave.open(str(score), 'wb') as output:
            output.setparams((2, 2, 48000, round(seconds * 48000), 'NONE', 'not compressed'))
            for source in sources:
                part = edit / (source['id'] + '_score.wav')
                ratio = source['score_duration'] / source['duration']
                run('-i', original_score, '-vn', '-af',
                    f'atrim=start={score_start}:duration={source["score_duration"]},asetpts=PTS-STARTPTS,'
                    f'atempo={ratio},aresample=48000,apad=whole_dur={source["duration"]},'
                    f'atrim=duration={source["duration"]},afade=t=in:d=0.006,'
                    f'afade=t=out:st={source["duration"]-.006}:d=0.006',
                    '-ac', 2, '-ar', 48000, '-c:a', 'pcm_s16le', part)
                with wave.open(str(part), 'rb') as piece:
                    assert piece.getnframes() == round(source['duration'] * 48000)
                    output.writeframes(piece.readframes(piece.getnframes()))
                score_start += source['score_duration']
    filters = (
        '[1:a]asplit=2[native][trigger];'
        f'[2:a]atrim=duration={seconds},asetpts=PTS-STARTPTS,volume=0.48[music];'
        '[music][trigger]sidechaincompress=threshold=0.045:ratio=3.5:attack=12:release=180[ducked];'
        '[native][ducked]amix=inputs=2:duration=first:normalize=0,'
        f'loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st={seconds-.18}:d=0.18[mix]'
    )
    temporary = final.with_name(final.stem + '.partial.mp4')
    run('-i', picture, '-i', native, '-i', score, '-filter_complex', filters,
        '-map', '0:v:0', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'aac',
        '-b:a', '192k', '-ar', 48000, '-t', seconds, '-movflags', '+faststart', temporary)
    proof = media_proof(temporary, frames, audio=True, dimensions=dimensions)
    assert proof['decoded_frames'] == frames and abs(proof['duration'] - seconds) < .001
    temporary.replace(final)
    proof['path'] = str(final)
    final.with_name(final.stem + '_proof.json').write_text(json.dumps(proof, indent=2))
    result = dict(schema='assembly_result.v1', title=spec['title'], work_in_progress=bool(preview),
                  audio_policy='Preserve native generated nonverbal voices and effects; original instrumental underscore with ducking; completed intro audio retained.',
                  transitions='hard cuts', full_scenes=full_scenes,
                  picture_policy='Every decoded source frame at original speed; zero scene trims; fit without cropping' if full_scenes else 'Manifest trims',
                  source_evidence=evidence, proof=proof, sha256=digest(final))
    record = final.with_name(final.stem + '_assembly.json')
    record.write_text(json.dumps(result, indent=2), encoding='utf-8')
    if publish:
        bridge.OUT, bridge.JOURNAL, bridge.FINAL = OUT, record, final
        title = f'{spec["title"]} - WIP {seconds:g}s.mp4' if preview else f'{spec["title"]} - {seconds:g}s.mp4'
        if full_scenes:
            title = f'{spec["title"]} - Full scenes - {seconds:.2f}s' + (' - WIP' if preview else '') + '.mp4'
        bridge.publish(final, frames, title)
    print(json.dumps(dict(status='finished', **proof)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', type=int)
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--full-scenes', action='store_true', help='Keep every source frame and native audio at original speed')
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.out.resolve()
    lock_name = ('full-scenes-' if args.full_scenes else '') + (f'editor-preview-{args.preview}.lock' if args.preview else 'editor.lock')
    with (OUT / lock_name).open('a+b') as guard:
        guard.seek(0)
        if guard.read(1) == b'':
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        finish(args.preview, args.wait, args.publish, args.full_scenes)
