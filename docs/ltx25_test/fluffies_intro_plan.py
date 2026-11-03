"""Series intro brief and frozen LTX submission."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'fluffies_intro'
prompt=('An original cheerful polished 3D animated preschool series intro, preserving the exact three fluffy characters in the opening frame: '
 'small coral-red Pip at left with curled tuft, broad lemon-yellow Momo in the centre, tall mint-green Tiki at right with two side tufts. '
 'All three WALK FORWARD together along the meadow path, taking several clearly visible alternating steps with grounded feet, swinging little arms and lively body weight shifts. '
 'The camera smoothly tracks BACKWARD at their walking pace, keeping full bodies and feet visible. The cottage and playground recede naturally behind them. '
 'Pip gives one quick happy skip while looking at Momo; Momo answers with a friendly shoulder bump to Pip, and Tiki chuckles at them while continuing to walk. '
 'In the final two seconds they stop side by side, lean close together and look eagerly toward the viewer, with distinct playful poses. '
 'Keep all three identities, sizes, fur colours and silhouettes stable; actual walking and physical interaction are essential, not standing in one place and moving mouths. '
 'Keep the open sky above their heads clear for a title added in post. No generated letters or text. '
 'SOUND: rhythmic soft footfalls on the sandy path; Pip makes a brief bright nonverbal giggle on the skip; Momo makes one round friendly breathy chuckle on the shoulder bump; '
 'Tiki gives a tiny airy amused squeak. Short expressive cartoon character vocalizations that match these actions, with natural outdoor ambience. '
 'No spoken words in any language, no narration, no conversation, no gibberish speech, no singing or lyrics. Do not generate background music; an original instrumental theme is added in post. '
 'One continuous eight-second shot, no internal cut, no fast camera spin or morphing, no extra characters.')
spec=dict(title='Fluffies — Series Intro',fps=24,total_seconds=8,total_frames=192,
 master_filename='Fluffies_Intro_8s.mp4',vault_title='Fluffies - Series Intro - 8 seconds.mp4',
 settings=dict(engine='ltx',mode='opening',steps='8',ltx_quality='balanced',aspect_ratio='16:9',ltx_sharp_decode='true',ltx_calm_sampler='false',no_audio='false'),
 shots=[dict(id='I00',title='Meet the Fluffies',duration=8,edit_frames=192,seed=1024200,
             frame='frames/I00.png',clip='clips/I00.mp4',video_prompt=prompt)],
 review='User visual/listening review; no AGY or delegated agents; basic ffprobe and full decode checks')
(OUT/'manifest.json').write_text(json.dumps(spec,indent=2))
(OUT/'I00-video-prompt.txt').write_text(prompt)
print(OUT/'manifest.json')
