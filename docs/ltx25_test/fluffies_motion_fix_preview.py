"""Show the user the existing story sources with their 2.5s opening holds removed."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'fluffies_ep01_shortcut'
sys.path.insert(0, str(Path(__file__).parent / 'tumble_puffs_ep01'))
import episode_runner as bridge

final = OUT / 'Fluffies_Motion_Start_Fix_9s.mp4'
filters = (
    '[0:v]trim=start_frame=60:end_frame=192,setpts=PTS-STARTPTS[v0];'
    '[1:v]trim=start_frame=60:end_frame=144,setpts=PTS-STARTPTS[v1];'
    '[v0][v1]concat=n=2:v=1:a=0[picture];'
    '[0:a]atrim=start=2.5:duration=5.5,asetpts=PTS-STARTPTS,aresample=48000[a0];'
    '[1:a]atrim=start=2.5:duration=3.5,asetpts=PTS-STARTPTS,aresample=48000[a1];'
    '[a0][a1]concat=n=2:v=0:a=1,asplit=2[native][trigger];'
    '[2:a]atrim=start=8:duration=9,asetpts=PTS-STARTPTS,volume=0.48[music];'
    '[music][trigger]sidechaincompress=threshold=0.045:ratio=3.5:attack=12:release=180[ducked];'
    '[native][ducked]amix=inputs=2:duration=first:normalize=0,'
    'loudnorm=I=-16:TP=-1.5:LRA=9,afade=t=out:st=8.85:d=0.15[mix]'
)
subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-y',
    '-i', str(OUT/'clips/E01.mp4'), '-i', str(OUT/'clips/E02.mp4'),
    '-i', str(OUT/'shortcut_original_score_120s.wav'), '-filter_complex', filters,
    '-map', '[picture]', '-map', '[mix]', '-frames:v', '216', '-r', '24', '-t', '9',
    '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', str(final)], check=True)
proof = bridge.probe(final, 216, audio=True)
assert proof['decoded_frames'] == 216 and abs(proof['duration']-9) < .001
record = dict(schema='assembly_result.v1', purpose='Immediate-motion cut demonstration; omit the superseded ident',
              sources=[dict(id='E01', trim_start_frame=60, edit_frames=132),
                       dict(id='E02', trim_start_frame=60, edit_frames=84)], proof=proof)
(OUT/'motion_fix_preview.json').write_text(json.dumps(record, indent=2))
bridge.OUT, bridge.JOURNAL, bridge.FINAL = OUT, OUT/'motion_fix_preview.json', final
bridge.publish(final, 216, 'Fluffies - Motion starts immediately - 9s cut demonstration.mp4')
