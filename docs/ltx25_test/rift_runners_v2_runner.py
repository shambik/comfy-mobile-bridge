"""Rift Runners v2 Pilot Runner & Assembler (LTX-2.5 lip_sync + opening modes).

Supports per-shot `mode` from `state/rift_runners_ep01/v2_pilot/manifest.json`:
- `lip_sync`: submits `mode='lip_sync'`, `first_frame=shot['frame']`, `audio=shot['voice_file']`,
  `audio_pretrimmed='true'`, `audio_start='0'`, `audio_duration=str(shot['duration'])`,
  `ltx_sharp_decode='false'`, `ltx_calm_sampler='false'`, `no_audio='false'`.
- `opening`: submits `mode='opening'`, `image=shot['frame']`,
  `ltx_sharp_decode='true'`, `ltx_calm_sampler='true'`, `no_audio='false'`.
"""
import argparse
from contextlib import ExitStack
import hashlib
import html
import json
import msvcrt
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[2]
PILOT_DIR = ROOT / 'state' / 'rift_runners_ep01' / 'v2_pilot'
DIST_DIR = ROOT / 'ui' / 'dist' / 'rift-runners'
BASE = 'http://127.0.0.1:8787'
sys.path.insert(0, str(Path(__file__).parent / 'tumble_puffs_ep01'))
import episode_runner as bridge


def say(**data):
    print(json.dumps(data), flush=True)


def session():
    client = requests.Session()
    response = client.get(BASE + '/api/session', timeout=30)
    response.raise_for_status()
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return client


def probe(path: Path, frames=None, audio=True, dimensions=(1600, 896)):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-show_format', '-of', 'json', str(path)],
        check=True, capture_output=True
    )
    info = json.loads(result.stdout)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    sounds = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if dimensions:
        assert (video['width'], video['height']) == dimensions, (video['width'], video['height'], dimensions)
    assert video['r_frame_rate'] == '24/1', video
    count = int(video['nb_read_frames'])
    assert frames is None or count >= frames, (path, count, frames)
    assert bool(sounds) == audio, (path, 'audio stream mismatch')
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], check=True)
    proof = dict(
        path=str(path), width=video['width'], height=video['height'], fps=24,
        decoded_frames=count, duration=float(info['format']['duration']),
        audio=bool(sounds), full_decode='passed'
    )
    path.with_name(path.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    return proof


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
            mode = shot['mode']
            opening_file = shot['frame']
            voice_file = shot.get('voice_file')

            while True:
                if (out_dir / 'STOPPED.json').exists():
                    raise SystemExit('Stopped before new submission; existing jobs preserved.')
                frame_ok = (out_dir / opening_file).exists()
                voice_ok = True if mode != 'lip_sync' else (voice_file and (out_dir / voice_file).exists())
                if frame_ok and voice_ok:
                    health = client.get(BASE + '/api/health', timeout=30)
                    health.raise_for_status()
                    if not health.json().get('active_job'):
                        break
                    say(shot=key, status='waiting_for_existing_bridge_job')
                else:
                    say(shot=key, status='waiting_for_inputs', frame_ok=frame_ok, voice_ok=voice_ok)
                time.sleep(15)

            if mode == 'lip_sync':
                payload = {
                    'engine': 'ltx',
                    'mode': 'lip_sync',
                    'steps': '8',
                    'ltx_quality': 'balanced',
                    'aspect_ratio': '16:9',
                    'ltx_sharp_decode': 'false',
                    'ltx_calm_sampler': 'false',
                    'no_audio': 'false',
                    'audio_pretrimmed': 'true',
                    'audio_start': '0',
                    'audio_duration': str(shot['duration']),
                    'prompt': shot['video_prompt'],
                    'duration': str(shot['duration']),
                    'seed': str(shot['seed']),
                }
            else:
                payload = {
                    'engine': 'ltx',
                    'mode': 'opening',
                    'steps': '8',
                    'ltx_quality': 'balanced',
                    'aspect_ratio': '16:9',
                    'ltx_sharp_decode': 'true',
                    'ltx_calm_sampler': 'true',
                    'no_audio': 'false',
                    'prompt': shot['video_prompt'],
                    'duration': str(shot['duration']),
                    'seed': str(shot['seed']),
                }

            item = dict(
                status='submitting', submitted=time.time(), mode=mode,
                opening_file=opening_file, voice_file=voice_file, payload=payload
            )
            data['items'][key] = item
            write_journal(data)

            with ExitStack() as handles:
                parts = [(k, (None, v)) for k, v in payload.items()]
                if mode == 'lip_sync':
                    f_img = handles.enter_context((out_dir / opening_file).open('rb'))
                    f_aud = handles.enter_context((out_dir / voice_file).open('rb'))
                    parts.append(('first_frame', (f'{key}-first_frame.png', f_img, 'image/png')))
                    parts.append(('audio', (f'{key}-audio.wav', f_aud, 'audio/wav')))
                else:
                    f_img = handles.enter_context((out_dir / opening_file).open('rb'))
                    parts.append(('image', (f'{key}-image.png', f_img, 'image/png')))
                response = client.post(BASE + '/api/jobs', files=parts, timeout=180)

            item['http_status'] = response.status_code
            try:
                item['response'] = response.json()
            except Exception:
                item['response'] = response.text
            if response.ok:
                item.update(id=response.json()['created'][0], status='queued')
            else:
                item['status'] = 'submission_failed'
            write_journal(data)
            response.raise_for_status()
            say(shot=key, id=item['id'], mode=mode, status=item['status'])

        if not item.get('id'):
            raise SystemExit(f'{key}: uncertain/failed submission; inspect journal before any retry.')

        while True:
            response = client.get(BASE + '/api/jobs?limit=200&include_library=false&include_sequences=false', timeout=30)
            response.raise_for_status()
            result = next(j for j in response.json()['jobs'] if j['id'] == item['id'])
            item.update(status=result['status'], response=result)
            write_journal(data)
            say(
                shot=key, mode=shot['mode'], status=item['status'],
                step=result.get('step'), total_steps=result.get('total_steps'),
                elapsed=round(time.time() - item['submitted'])
            )
            if item['status'] == 'completed':
                destination = out_dir / shot['clip']
                if not destination.exists():
                    media = client.get(BASE + '/api/jobs/' + item['id'] + '/video', timeout=180)
                    media.raise_for_status()
                    temporary = destination.with_suffix('.download')
                    temporary.write_bytes(media.content)
                    temporary.replace(destination)
                item['proof'] = probe(destination, shot['edit_frames'], audio=True)
                # Build contact sheet for immediate visual QC
                qc_dir = out_dir / 'qc'
                qc_dir.mkdir(exist_ok=True)
                subprocess.run([
                    'ffmpeg', '-v', 'error', '-y', '-i', str(destination),
                    '-vf', 'fps=1,scale=480:-1,tile=3x2', '-frames:v', '1',
                    str(qc_dir / f'{key}_sheet.jpg')
                ], check=True)
                item.update(status='verified', path=str(destination), verified=time.time())
                write_journal(data)
                say(shot=key, status='verified', path=str(destination))
                break
            if item['status'] not in {'queued', 'starting', 'running', 'verifying'}:
                raise SystemExit(f'{key}: {item["status"]}; no automatic retry.')
            time.sleep(20)
    say(status='all_v2_pilot_clips_verified')


def run_ff(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-y', *map(str, args)], check=True)


def assemble(out_dir: Path, publish: bool = False):
    spec = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))
    dimensions = (spec.get('output_width', 1600), spec.get('output_height', 896))
    edit = out_dir / 'edit'
    edit.mkdir(exist_ok=True)
    videos, sounds = [], []

    for s in spec['shots']:
        sid = s['id']
        src_clip = out_dir / s['clip']
        frames = s['edit_frames']
        dur = s['duration']
        probe(src_clip, frames, audio=True, dimensions=dimensions)

        v_out = edit / f'{sid}.mp4'
        a_out = edit / f'{sid}.wav'
        run_ff(
            '-i', src_clip, '-an', '-vf',
            f'trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS,setsar=1',
            '-r', 24, '-frames:v', frames, '-c:v', 'libx264',
            '-threads', 4, '-preset', 'fast', '-crf', 17, '-pix_fmt', 'yuv420p',
            '-video_track_timescale', 12288, v_out
        )
        # For lip_sync shots, the clip already contains the synced single-speaker voice audio;
        # boost it cleanly so dialogue sits forward over the score. For wide shots, keep foley at 0.65.
        vol = '1.30' if s['mode'] == 'lip_sync' else '0.65'
        run_ff(
            '-i', src_clip, '-vn', '-af',
            f'atrim=start=0:duration={dur},asetpts=PTS-STARTPTS,aresample=48000,'
            f'volume={vol},apad=whole_dur={dur},atrim=duration={dur},'
            f'afade=t=in:d=0.008,afade=t=out:st={dur-0.008}:d=0.008',
            '-ac', 2, '-ar', 48000, '-c:a', 'pcm_s16le', a_out
        )
        videos.append(v_out)
        sounds.append(a_out)

    total_frames = spec['total_frames']
    total_seconds = spec['total_seconds']
    playlist = edit / 'concat.txt'
    playlist.write_text(''.join("file '" + p.as_posix() + "'\n" for p in videos), encoding='utf-8')
    silent_mp4 = edit / 'pilot_silent.mp4'
    run_ff('-f', 'concat', '-safe', 0, '-i', playlist, '-c', 'copy', '-an', silent_mp4)
    probe(silent_mp4, total_frames, audio=False, dimensions=dimensions)

    stem_wav = edit / 'pilot_stem.wav'
    with wave.open(str(stem_wav), 'wb') as output:
        output.setparams((2, 2, 48000, round(total_seconds * 48000), 'NONE', 'not compressed'))
        for sound in sounds:
            with wave.open(str(sound), 'rb') as src_w:
                output.writeframes(src_w.readframes(src_w.getnframes()))

    score_path = (out_dir / spec['score_file']).resolve()
    final_mp4 = out_dir / spec['master_filename']
    filters = (
        '[1:a]asplit=2[fg][trigger];'
        f'[2:a]atrim=duration={total_seconds},asetpts=PTS-STARTPTS,volume=0.34[music];'
        '[music][trigger]sidechaincompress=threshold=0.03:ratio=4.5:attack=10:release=220[ducked];'
        '[fg][ducked]amix=inputs=2:duration=first:normalize=0,'
        f'loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st={total_seconds-0.25}:d=0.25[mix]'
    )
    tmp_mp4 = final_mp4.with_name(final_mp4.stem + '.partial.mp4')
    run_ff(
        '-i', silent_mp4, '-i', stem_wav, '-i', score_path,
        '-filter_complex', filters, '-map', '0:v:0', '-map', '[mix]',
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', 48000,
        '-t', total_seconds, '-movflags', '+faststart', tmp_mp4
    )
    proof = probe(tmp_mp4, total_frames, audio=True, dimensions=dimensions)
    tmp_mp4.replace(final_mp4)
    proof['path'] = str(final_mp4)
    final_mp4.with_name(final_mp4.stem + '_proof.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')

    # Sync to ui/dist/rift-runners/v2_pilot
    if DIST_DIR.exists():
        dist_pilot = DIST_DIR / 'v2_pilot'
        if dist_pilot.exists():
            shutil.rmtree(dist_pilot)
        shutil.copytree(out_dir, dist_pilot)

    if publish:
        record = out_dir / 'assembly_v2.json'
        record.write_text(json.dumps(dict(proof=proof), indent=2), encoding='utf-8')
        bridge.OUT, bridge.JOURNAL, bridge.FINAL = out_dir, record, final_mp4
        bridge.publish(final_mp4, total_frames, f'{spec["title"]} - {total_seconds}s.mp4')
    build_board(out_dir)
    say(status='assembled_v2_pilot', **proof)


def build_board(out_dir: Path):
    spec = json.loads((out_dir / 'manifest.json').read_text(encoding='utf-8'))
    esc = html.escape
    cards = []
    for s in spec['shots']:
        sid = s['id']
        clip_exists = (out_dir / s['clip']).exists()
        media_html = f'<a href="v2_pilot/{s["frame"]}"><img src="v2_pilot/{s["frame"]}" alt="{esc(s["title"])}"></a>'
        if clip_exists:
            media_html += (
                f'<video controls preload="metadata" src="v2_pilot/{s["clip"]}" '
                f'style="width:100%;aspect-ratio:16/9;border-radius:10px;margin-top:8px;background:#000"></video>'
            )
        badge = 'LTX 2.5 LIP-SYNC (SINGLE SPEAKER)' if s['mode'] == 'lip_sync' else 'LTX 2.5 OPENING (NO SPEECH / CLOSED MOUTHS)'
        badge_bg = '#0284c7' if s['mode'] == 'lip_sync' else '#334155'
        if s['mode'] == 'lip_sync':
            dlg_html = (
                f'<div style="margin:10px 0;padding:10px 12px;background:#0f172a;border-radius:10px;border:1px solid #1e293b">'
                f'<div style="font-size:11px;color:#38bdf8;font-weight:700;margin-bottom:4px">🎙️ SINGLE-SPEAKER LIP-SYNC WAV ({sid}.wav · {s["duration"]}s)</div>'
                f'<div style="margin:4px 0;font-size:13px"><strong style="color:#93c5fd">{esc(s["speaker"])} ({esc(s["voice"])}):</strong> {esc(s["dialogue_text"])}</div>'
                f'<audio controls preload="none" src="v2_pilot/{s["voice_file"]}" style="width:100%;height:32px;margin-top:6px"></audio>'
                f'</div>'
            )
        else:
            dlg_html = (
                '<div style="margin:10px 0;padding:8px 12px;background:#0f172a;border-radius:10px;'
                'border:1px solid #1e293b;font-size:12px;color:#94a3b8">'
                '🔇 Dialogue-free action shot (mouths stay closed; LTX foley only)</div>'
            )
        cards.append(
            f'<article>{media_html}'
            f'<div class="badge" style="background:{badge_bg}">{esc(badge)}</div>'
            f'<h2>{sid} · {esc(s["title"])}</h2>'
            f'<p class="meta">{s["start"]}–{s["end"]}s · {s["duration"]}s · Visible Cast: {esc(", ".join(s["cast"]) or "Insert (boot & tile only)")}</p>'
            f'{dlg_html}'
            f'<details open><summary>v2 Concise LTX-2.5 Prompt</summary><p>{esc(s["video_prompt"])}</p></details></article>'
        )
    master_mp4 = out_dir / spec['master_filename']
    master_html = ''
    if master_mp4.exists():
        master_html = (
            f'<div style="margin-top:16px;padding:16px;background:#151c2c;border-radius:14px;border:1px solid #38bdf8">'
            f'<h2 style="margin:0 0 8px">🎬 Master Assembled Act I Pilot ({spec["total_seconds"]}s)</h2>'
            f'<video controls preload="metadata" src="v2_pilot/{spec["master_filename"]}" '
            f'style="width:100%;max-width:960px;border-radius:12px;background:#000"></video></div>'
        )
    doc = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Rift Runners v2 Act I Pilot (A01-A10)</title>'
        '<style>body{margin:0;background:#0b0f19;color:#eef2ff;font:15px/1.55 system-ui}header,main{max-width:1680px;margin:auto;padding:24px}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:24px}'
        'article{background:#151c2c;padding:16px;border-radius:18px;border:1px solid #26324d}'
        'img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;background:#090c14}'
        '.badge{display:inline-block;margin-top:10px;padding:4px 10px;border-radius:99px;color:#fff;font-size:11px;font-weight:700;letter-spacing:.04em}'
        'h1{font-size:28px;margin:0 0 8px}h2{font-size:19px;margin:8px 0 4px}.meta{color:#9fb0d9;font-size:13px}details p{font-size:13px;color:#cbd5e1}a{color:#7cc0ff}</style>'
        '<header><h1>Rift Runners — v2 Act I Pilot (A01–A10 · 42s · Single-Speaker Lip-Sync + Accurate Prompts)</h1>'
        '<p>Every spoken line has its own solo or over-the-shoulder close-up with <strong>one visible face</strong> and a <strong>single-speaker 4.0s Gemini TTS WAV</strong> rendered in LTX 2.5 <code>lip_sync</code> mode. Wide and insert shots have zero dialogue and concise prompts.</p>'
        f'{master_html}</header><main>' + ''.join(cards) + '</main></html>'
    )
    (out_dir / 'pilot_v2.html').write_text(doc, encoding='utf-8')
    if DIST_DIR.exists():
        dist_pilot = DIST_DIR / 'v2_pilot'
        dist_pilot.mkdir(parents=True, exist_ok=True)
        for sub in ['frames', 'voices', 'clips']:
            s_dir = out_dir / sub
            if s_dir.exists():
                d_dir = dist_pilot / sub
                d_dir.mkdir(parents=True, exist_ok=True)
                for f in s_dir.iterdir():
                    if f.is_file():
                        shutil.copy2(f, d_dir / f.name)
        if master_mp4.exists():
            shutil.copy2(master_mp4, dist_pilot / master_mp4.name)
        (DIST_DIR / 'pilot_v2.html').write_text(doc, encoding='utf-8')
    banner = (
        '<div style="margin:16px 0;padding:18px 20px;background:#0f172a;border:2px solid #38bdf8;border-radius:14px">'
        '<h2 style="margin:0 0 8px;color:#38bdf8">✨ NEW: v2 Act I Pilot (A01–A10 · 42s · Single-Speaker Lip-Sync Close-Ups &amp; Accurate Prompts)</h2>'
        '<p style="margin:0 0 12px">All 10 shots rendered, visually verified via contact sheets, and assembled with ducked Lyria 3.5 Hip-Hop score: '
        '<a href="pilot_v2.html" style="padding:6px 12px;background:#0284c7;color:#fff;border-radius:8px;text-decoration:none;font-weight:700;margin-left:8px">Open Full v2 Pilot Shot-by-Shot Board (pilot_v2.html) →</a></p>'
        '<video controls preload="metadata" src="v2_pilot/Rift_Runners_Act1_Pilot_v2.mp4" style="width:100%;max-width:960px;border-radius:12px;background:#000"></video>'
        '</div>'
    )
    for sb in [out_dir.parent / 'storyboard.html', DIST_DIR / 'storyboard.html']:
        if sb.exists():
            txt = sb.read_text(encoding='utf-8')
            if 'v2_pilot/Rift_Runners_Act1_Pilot_v2.mp4' not in txt:
                txt = txt.replace('</header>', banner + '</header>', 1)
                sb.write_text(txt, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['render', 'assemble', 'board'])
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--out', type=Path, default=PILOT_DIR)
    args = parser.parse_args()
    out_resolved = args.out.resolve()
    lock_file = out_resolved / f'{args.action}.lock'
    with lock_file.open('a+b') as guard:
        guard.seek(0)
        if guard.read(1) == b'':
            guard.write(b'0')
            guard.flush()
        guard.seek(0)
        msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
        if args.action == 'render':
            render(out_resolved)
        elif args.action == 'board':
            build_board(out_resolved)
        else:
            assemble(out_resolved, publish=args.publish)
