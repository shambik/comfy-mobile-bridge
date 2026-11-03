"""Resumable single-producer LTX episode render, exact-frame edit and vault upload.

Never retries an uncertain submission or cancels an existing job. Opening stills
are delivered separately by built-in ImageGen. No app/runtime changes are made.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import msvcrt
import subprocess
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'state' / 'tumble_puffs_ep01'
JOURNAL = OUT / 'execution.json'
BASE = 'http://127.0.0.1:8787'
FINAL = OUT / 'The_Runaway_Berry_120s.mp4'


def read():
    return json.loads(JOURNAL.read_text()) if JOURNAL.exists() else {'items': {}, 'created': time.time()}


def write(data):
    temporary = JOURNAL.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(JOURNAL)


def say(**data):
    print(json.dumps(data), flush=True)


def session():
    client = requests.Session()
    response = client.get(BASE + '/api/session', timeout=30)
    response.raise_for_status()
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return client


def probe(path, frames=None, audio=False):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                             '-show_format', '-of', 'json', str(path)], check=True, capture_output=True)
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    sounds = [s for s in info['streams'] if s['codec_type'] == 'audio']
    assert (video['width'], video['height']) == (1600, 896), video
    assert video['r_frame_rate'] == '24/1', video
    count = int(video['nb_read_frames'])
    assert frames is None or count >= frames, (path, count, frames)
    assert bool(sounds) == audio, (path, 'audio stream mismatch')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = dict(path=str(path), width=1600, height=896, fps=24, decoded_frames=count,
                 duration=float(info['format']['duration']), audio=bool(sounds), full_decode='passed')
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2))
    return proof


def render():
    spec = json.loads((OUT / 'manifest.json').read_text())
    client = session()
    for shot in spec['shots']:
        key = shot['id']
        data = read()
        item = data['items'].get(key)
        if item and item.get('status') == 'verified':
            continue
        if item is None:
            while True:
                if (OUT / 'STOPPED.json').exists():
                    raise SystemExit('Stopped before new submission; existing jobs preserved.')
                if (OUT / shot['frame']).exists():
                    health = client.get(BASE + '/api/health', timeout=30)
                    health.raise_for_status()
                    if not health.json().get('active_job'):
                        break
                    say(shot=key, status='waiting_for_existing_bridge_job')
                else:
                    say(shot=key, status='waiting_for_opening_frame')
                time.sleep(20)
            payload = {**spec['settings'], 'prompt': shot['video_prompt'],
                       'duration': str(shot['duration']), 'seed': str(shot['seed'])}
            item = dict(status='submitting', submitted=time.time(), payload=payload)
            data['items'][key] = item
            write(data)  # Durable before POST; uncertain submissions require reconciliation.
            with ExitStack() as handles:
                parts = [(k, (None, v)) for k, v in payload.items()]
                uploads = [('first_frame', shot['frame']), ('last_frame', shot.get('closing_frame', shot['frame']))] if payload['mode']=='frames' else [('image', shot['frame'])]
                for field, filename in uploads:
                    handle = handles.enter_context((OUT / filename).open('rb'))
                    parts.append((field, (key + '-' + field + '.png', handle, 'image/png')))
                response = client.post(BASE + '/api/jobs', files=parts, timeout=180)
            item['http_status'] = response.status_code
            item['response'] = response.json()
            if response.ok:
                item.update(id=response.json()['created'][0], status='queued')
            else:
                item['status'] = 'submission_failed'
            write(data)
            response.raise_for_status()
            say(shot=key, id=item['id'], status=item['status'])
        if not item.get('id'):
            raise SystemExit(f'{key}: uncertain/failed submission; inspect journal before any retry.')
        while True:
            response = client.get(BASE + '/api/jobs?limit=200&include_library=false&include_sequences=false', timeout=30)
            response.raise_for_status()
            result = next(j for j in response.json()['jobs'] if j['id'] == item['id'])
            item.update(status=result['status'], response=result)
            write(data)
            say(shot=key, status=item['status'], step=result.get('step'),
                total_steps=result.get('total_steps'), elapsed=round(time.time() - item['submitted']))
            if item['status'] == 'completed':
                destination = OUT / shot['clip']
                if not destination.exists():
                    media = client.get(BASE + '/api/jobs/' + item['id'] + '/video', timeout=180)
                    media.raise_for_status()
                    temporary = destination.with_suffix('.download')
                    temporary.write_bytes(media.content)
                    temporary.replace(destination)
                item['proof'] = probe(destination, shot['edit_frames'],
                                      audio=spec['settings'].get('no_audio') == 'false')
                item.update(status='verified', path=str(destination), verified=time.time())
                write(data)
                say(shot=key, status='verified', path=str(destination))
                break
            if item['status'] not in {'queued', 'starting', 'running', 'verifying'}:
                raise SystemExit(f'{key}: {item["status"]}; no automatic retry.')
            time.sleep(20)
    say(status='all_manifest_clips_verified')


def assemble():
    spec = json.loads((OUT / 'manifest.json').read_text())
    data = read()
    normalized = OUT / 'edit'
    normalized.mkdir(exist_ok=True)
    pieces = []
    for shot in spec['shots']:
        assert data['items'][shot['id']]['status'] == 'verified', shot['id']
        source, target = OUT / shot['clip'], normalized / (shot['id'] + '.mp4')
        stamp = target.with_suffix('.source.json')
        fingerprint = dict(sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                           frames=shot['edit_frames'], trim_start=0)
        cached = json.loads(stamp.read_text()) if stamp.exists() else None
        if not target.exists() or cached != fingerprint:
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-an',
                            '-vf', f'trim=start_frame=0:end_frame={shot["edit_frames"]},setpts=PTS-STARTPTS',
                            '-frames:v', str(shot['edit_frames']), '-r', '24', '-c:v', 'libx264',
                            '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p',
                            '-video_track_timescale', '12288', str(target)], check=True)
            stamp.write_text(json.dumps(fingerprint, indent=2))
        proof = probe(target, shot['edit_frames'])
        assert proof['decoded_frames'] == shot['edit_frames']
        pieces.append(target)
    playlist = normalized / 'concat.txt'
    playlist.write_text(''.join("file '" + p.as_posix() + "'\n" for p in pieces), encoding='utf-8')
    silent = OUT / 'episode_picture_silent.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(playlist),
                    '-c', 'copy', '-an', '-movflags', '+faststart', str(silent)], check=True)
    total_frames, seconds = spec['total_frames'], spec['total_seconds']
    picture = probe(silent, total_frames)
    assert picture['decoded_frames'] == total_frames and abs(picture['duration'] - seconds) < .001
    score = OUT / 'episode_score_and_foley.wav'
    assert score.exists(), 'Create episode_score.py output before assembly.'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(silent), '-i', str(score),
                    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                    '-af', f'loudnorm=I=-17:TP=-1.5:LRA=9,afade=t=out:st={seconds-0.6}:d=0.6', '-c:a', 'aac', '-b:a', '192k',
                    '-ar', '48000', '-t', str(seconds), '-movflags', '+faststart', str(FINAL)], check=True)
    proof = probe(FINAL, total_frames, audio=True)
    assert proof['decoded_frames'] == total_frames and abs(proof['duration'] - seconds) < .001
    data['master'] = proof
    write(data)
    say(**proof)


def publish(path=FINAL, expected_frames=2880, title=None):
    proof = json.loads(path.with_name(path.stem + '_proof.json').read_text())
    assert proof['full_decode'] == 'passed' and proof['decoded_frames'] == expected_frames
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    client = session()
    response = client.get(BASE + '/api/video-vault', timeout=30)
    response.raise_for_status()
    existing = next((i for i in response.json()['items'] if i.get('sha256') == digest and i.get('available')), None)
    record = path.with_name(path.stem + '_published.json')
    previous = json.loads(record.read_text()) if record.exists() else {}
    if existing is None:
        if previous.get('status') == 'submitting':
            raise SystemExit('Upload result uncertain; inspect vault before retrying.')
        record.write_text(json.dumps(dict(status='submitting', sha256=digest), indent=2))
        with path.open('rb') as handle:
            response = client.post(BASE + '/api/video-vault', data={'name': title or 'Tumble Puffs - Episode 01 - The Runaway Berry - 2 minutes.mp4'},
                                   files={'video': (path.name, handle, 'video/mp4')}, timeout=180)
        response.raise_for_status()
        existing = response.json()
    assert existing.get('sha256') == digest and existing.get('available'), existing
    publication = dict(status='completed', item=existing, sha256=digest)
    record.write_text(json.dumps(publication, indent=2))
    # Previews use their own record; the renderer owns the execution journal.
    if path == FINAL:
        data = read()
        data['publish'] = publication
        write(data)
    say(published=existing)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['render', 'assemble', 'publish', 'all'])
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    OUT = args.out.resolve()
    JOURNAL = OUT / 'execution.json'
    spec = json.loads((OUT/'manifest.json').read_text())
    FINAL = OUT / spec.get('master_filename', 'The_Runaway_Berry_120s.mp4')
    # Windows releases this byte-range lock if the process exits, even on a crash.
    with (OUT / 'producer.lock').open('a+b') as guard:
        guard.seek(0)
        if guard.read(1) == b'':
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        if args.action in {'render', 'all'}:
            render()
        if args.action in {'assemble', 'all'}:
            assemble()
        if args.action in {'publish', 'all'}:
            publish(FINAL, spec['total_frames'], spec.get('vault_title'))
