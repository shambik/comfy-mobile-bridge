"""Publish a clearly labeled 22-second work-in-progress while rendering continues."""
import json
import subprocess
import episode_runner as episode

spec = json.loads((episode.OUT/'manifest.json').read_text())
shots = spec['shots'][:4]
data = episode.read()
assert all(data['items'][s['id']]['status']=='verified' for s in shots)
path = episode.OUT/'PREVIEW_FIRST_22s_with_music.mp4'
inputs = sum((['-i',str(episode.OUT/s['clip'])] for s in shots),[])
filters = ';'.join(f'[{i}:v]trim=end_frame={s["edit_frames"]},setpts=PTS-STARTPTS[v{i}]' for i,s in enumerate(shots))
filters += ';'+''.join(f'[v{i}]' for i in range(4))+'concat=n=4:v=1:a=0[picture]'
subprocess.run(['ffmpeg','-v','error','-y',*inputs,'-i',str(episode.OUT/'episode_score_and_foley.wav'),
                '-filter_complex',filters,'-map','[picture]','-map','4:a:0','-t','22',
                '-r','24','-frames:v','528','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
                '-af','loudnorm=I=-17:TP=-1.5:LRA=9','-c:a','aac','-b:a','192k',
                '-ar','48000','-movflags','+faststart',str(path)],check=True)
proof = episode.probe(path,528,audio=True)
assert proof['decoded_frames']==528 and abs(proof['duration']-22)<.001
episode.publish(path,528,'Tumble Puffs - EP01 - First 22 seconds PREVIEW with music.mp4')
