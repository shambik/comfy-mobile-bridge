"""Resumable LTX-2.5 runner supporting Opening, Multishot, First+Last Frame, and Sequential Last-Frame Extraction.

Supports per-shot `flow_mode` from `state/rift_runners_ep01/manifest.json`:
- `opening` / `multishot`: submits `mode='opening'` with `shot['frame']`.
- `first_last`: submits `mode='frames'` with `first_frame=shot['frame']` and `last_frame=shot['closing_frame']`.
- `sequential` (`extract_last_frame=True`): extracts the verified final frame of `clips/<prev_shot>.mp4`
  to `frames/<id>_from_<prev_shot>_last.png` via FFmpeg and submits `mode='opening'` with that extracted frame
  so the shot continues the exact action and camera state of the preceding shot.
"""
import argparse
from contextlib import ExitStack
import json
import msvcrt
import subprocess
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'rift_runners_ep01'
BASE = 'http://127.0.0.1:8787'


def say(**data):
    print(json.dumps(data), flush=True)


def session():
    client = requests.Session()
    response = client.get(BASE + '/api/session', timeout=30)
    response.raise_for_status()
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return client


def probe(path, frames=None, audio=False):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(path)],
        check=True, capture_output=True
    )
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    sounds = [s for s in info['streams'] if s['codec_type'] == 'audio']
    assert (video['width'], video['height']) == (1600, 896), video
    assert video['r_frame_rate'] == '24/1', video
    count = int(video['nb_read_frames'])
    assert frames is None or count >= frames, (path, count, frames)
    assert bool(sounds) == audio, (path, 'audio stream mismatch')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = dict(
        path=str(path), width=1600, height=896, fps=24, decoded_frames=count,
        duration=float(info['format']['duration']), audio=bool(sounds), full_decode='passed'
    )
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2))
    return proof


def extract_verified_last_frame(prev_clip_path: Path, target_png_path: Path) -> Path:
    info_res = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(prev_clip_path)],
        check=True, capture_output=True
    )
    info = json.loads(info_res.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    last_idx = max(0, int(video['nb_read_frames']) - 1)
    subprocess.run(
        [
            'ffmpeg', '-v', 'error', '-y', '-i', str(prev_clip_path),
            '-vf', f'select=eq(n\\,{last_idx}),scale=1920:1080:flags=lanczos',
            '-frames:v', '1', str(target_png_path)
        ],
        check=True
    )
    return target_png_path


def render(out_dir: Path):
    journal_path = out_dir / 'execution.json'

    def read_journal():
        return json.loads(journal_path.read_text(encoding='utf-8')) if journal_path.exists() else {'items': {}, 'created': time.time()}

    def write_journal(data):
        tmp = journal_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
        tmp.replace(journal_path)

    spec = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))
    client = session()

    for shot in spec['shots']:
        key = shot['id']
        data = read_journal()
        item = data['items'].get(key)
        if item and item.get('status') == 'verified':
            continue

        if item is None:
            flow_mode = shot.get('flow_mode', 'opening')
            bridge_mode = shot.get('bridge_mode', 'opening')
            prev_shot = shot.get('prev_shot')

            while True:
                if (out_dir / 'STOPPED.json').exists():
                    raise SystemExit('Stopped before new submission; existing jobs preserved.')

                # Determine required frame files
                ready = False
                if shot.get('extract_last_frame') and prev_shot:
                    prev_state = read_journal()['items'].get(prev_shot, {})
                    prev_clip = out_dir / 'clips' / f'{prev_shot}.mp4'
                    if prev_state.get('status') == 'verified' and prev_clip.exists():
                        extracted_path = out_dir / 'frames' / f'{key}_from_{prev_shot}_last.png'
                        if not extracted_path.exists():
                            extract_verified_last_frame(prev_clip, extracted_path)
                            say(shot=key, status='extracted_last_frame', source=str(prev_clip), frame=str(extracted_path))
                        opening_file = f'frames/{key}_from_{prev_shot}_last.png'
                        ready = True
                    else:
                        say(shot=key, status='waiting_for_prev_shot_last_frame', prev_shot=prev_shot)
                elif bridge_mode == 'frames':
                    opening_file = shot['frame']
                    closing_file = shot['closing_frame']
                    if (out_dir / opening_file).exists() and (out_dir / closing_file).exists():
                        ready = True
                    else:
                        say(shot=key, status='waiting_for_first_and_last_frames')
                else:
                    opening_file = shot['frame']
                    if (out_dir / opening_file).exists():
                        ready = True
                    else:
                        say(shot=key, status='waiting_for_opening_frame')

                if ready:
                    health = client.get(BASE + '/api/health', timeout=30)
                    health.raise_for_status()
                    if not health.json().get('active_job'):
                        break
                    say(shot=key, status='waiting_for_existing_bridge_job')
                time.sleep(20)

            payload = {
                **spec['settings'],
                'mode': bridge_mode,
                'prompt': shot['video_prompt'],
                'duration': str(shot['duration']),
                'seed': str(shot['seed']),
            }
            item = dict(
                status='submitting', submitted=time.time(), flow_mode=flow_mode,
                opening_file=opening_file, closing_file=shot.get('closing_frame'), payload=payload
            )
            data['items'][key] = item
            write_journal(data)

            with ExitStack() as handles:
                parts = [(k, (None, v)) for k, v in payload.items()]
                if bridge_mode == 'frames':
                    uploads = [('first_frame', opening_file), ('last_frame', shot['closing_frame'])]
                else:
                    uploads = [('image', opening_file)]
                for field, filename in uploads:
                    handle = handles.enter_context((out_dir / filename).open('rb'))
                    parts.append((field, (f'{key}-{field}.png', handle, 'image/png')))
                response = client.post(BASE + '/api/jobs', files=parts, timeout=180)

            item['http_status'] = response.status_code
            item['response'] = response.json()
            if response.ok:
                item.update(id=response.json()['created'][0], status='queued')
            else:
                item['status'] = 'submission_failed'
            write_journal(data)
            response.raise_for_status()
            say(shot=key, id=item['id'], flow_mode=flow_mode, status=item['status'])

        if not item.get('id'):
            raise SystemExit(f'{key}: uncertain/failed submission; inspect journal before any retry.')

        while True:
            response = client.get(BASE + '/api/jobs?limit=200&include_library=false&include_sequences=false', timeout=30)
            response.raise_for_status()
            result = next(j for j in response.json()['jobs'] if j['id'] == item['id'])
            item.update(status=result['status'], response=result)
            write_journal(data)
            say(
                shot=key, status=item['status'], step=result.get('step'),
                total_steps=result.get('total_steps'), elapsed=round(time.time() - item['submitted'])
            )
            if item['status'] == 'completed':
                destination = out_dir / shot['clip']
                if not destination.exists():
                    media = client.get(BASE + '/api/jobs/' + item['id'] + '/video', timeout=180)
                    media.raise_for_status()
                    temporary = destination.with_suffix('.download')
                    temporary.write_bytes(media.content)
                    temporary.replace(destination)
                item['proof'] = probe(destination, shot['edit_frames'], audio=spec['settings'].get('no_audio') == 'false')
                item.update(status='verified', path=str(destination), verified=time.time())
                write_journal(data)
                say(shot=key, status='verified', path=str(destination))
                break
            if item['status'] not in {'queued', 'starting', 'running', 'verifying'}:
                raise SystemExit(f'{key}: {item["status"]}; no automatic retry.')
            time.sleep(20)
    say(status='all_manifest_clips_verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['render'])
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    out_resolved = args.out.resolve()
    with (out_resolved / 'producer.lock').open('a+b') as guard:
        guard.seek(0)
        if guard.read(1) == b'':
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        render(out_resolved)
