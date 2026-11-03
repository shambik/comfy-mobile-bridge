"""Protect the exact furry lettering above the bridge-generated eight-cast intro."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'fluffies_cast_intro_app_v4'
sys.path.insert(0, str(Path(__file__).parent / 'tumble_puffs_ep01'))
import episode_runner as bridge


def finish(wait=False):
    while True:
        state = json.loads((OUT/'execution.json').read_text())
        item = state.get('items', {}).get('I04', {})
        if item.get('status') == 'verified':
            break
        if not wait:
            raise SystemExit('I04 is not verified yet.')
        if (OUT/'STOPPED.json').exists() or item.get('status') in {'failed', 'canceled', 'submission_failed'}:
            raise SystemExit('Intro render requires attention; no cancellation or retry.')
        time.sleep(20)
    native = OUT/'clips/I04.mp4'
    final = OUT/'Fluffies_All_Cast_Intro_v4_8s.mp4'
    logo = ROOT/'state/fluffies_brand_intro/fluffies-logo-rainbow-v2.png'
    theme = ROOT/'state/fluffies_intro/fluffies_intro_theme.wav'
    bridge.probe(native, 240, audio=True)
    filters = (
        '[0:v]trim=start_frame=48:end_frame=240,setpts=PTS-STARTPTS[cast];'
        "[1:v]format=rgba,scale=w='1160*(1+0.025*sin(2*PI*t/1.15)*exp(-t/2.6))':h=-1:eval=frame[logo];"
        "[cast][logo]overlay=x='(W-w)/2':y='122+5*sin(2*PI*t/1.15)*exp(-t/2.6)':eval=frame:shortest=1:format=auto,format=yuv420p[picture];"
        '[0:a]atrim=start=2:duration=8,asetpts=PTS-STARTPTS,aresample=48000,asplit=2[native][trigger];'
        '[2:a]atrim=duration=8,asetpts=PTS-STARTPTS,volume=0.35[music];'
        '[music][trigger]sidechaincompress=threshold=0.045:ratio=3.5:attack=12:release=180[ducked];'
        '[native][ducked]amix=inputs=2:duration=first:normalize=0,'
        'loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st=7.86:d=0.14[mix]'
    )
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-y', '-i', str(native),
        '-loop', '1', '-framerate', '24', '-i', str(logo), '-i', str(theme),
        '-filter_complex', filters, '-map', '[picture]', '-map', '[mix]',
        '-frames:v', '192', '-r', '24', '-t', '8', '-c:v', 'libx264', '-preset', 'fast',
        '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
        '-movflags', '+faststart', str(final)], check=True)
    proof = bridge.probe(final, 192, audio=True)
    assert proof['decoded_frames'] == 192 and abs(proof['duration']-8) < .001
    record = dict(schema='assembly_result.v1', proof=proof, source_job=item['id'],
                  source_trim=dict(start_frame=48, end_frame=240),
                  lettering='Full exact selected RGBA furry wordmark, animated as a single foreground layer; all eight glyphs retained throughout.',
                  cast=['Bobo','Lulu','Zuzu','Numi','Pip','Momo','Tiki','Pebble'],
                  audio='Native nonverbal reactions/effects plus original signature music')
    record_path = OUT/'assembly.json'
    record_path.write_text(json.dumps(record, indent=2))
    bridge.OUT, bridge.JOURNAL, bridge.FINAL = OUT, record_path, final
    bridge.publish(final, 192, 'Fluffies - Eight-character intro - complete fluffy lettering - v4.mp4')


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--wait', action='store_true')
    finish(parser.parse_args().wait)
