"""Enhanced furry typography intro rendered by the main bridge's LTX workflow."""
import json
import shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'fluffies_brand_intro_app'
(OUT/'frames').mkdir(parents=True,exist_ok=True)
(OUT/'clips').mkdir(exist_ok=True)
source=ROOT/'.runtime'/'labs'/'fluffies-brand-intro'/'film'/'snapshots'/'frame-02-at-3.5s.png'
target=OUT/'frames'/'B01.png'
if not target.exists():
    shutil.copyfile(source,target)
prompt=('A premium cinematic 3D animated-series LOGO IDENT. The single exact word FLUFFIES is already formed as the eight original fluffy three-dimensional letter shapes in the supplied image, spelled Fluffies, capital F followed by lowercase l u f f i e s. '
 'Preserve those exact glyphs, spelling, spacing, rainbow colours and thick rounded furry volumes throughout the animation. This is tangible plush sculptural typography, not flat text and not a character scene. '
 'The coral-pink F, golden l, sky-blue turquoise u, violet first f, candy-pink second f, aqua i, blue-violet e and peach-gold s keep their identities. '
 'Animate a lively soft BOUNCE WAVE that travels from the F to the s: each fluffy letter compresses slightly, springs visibly upward and lands with a soft squishy squash-and-stretch. '
 'Fine fur follows the motion naturally. The round fluffy dot on the i makes ONE playful higher hop and lands securely back above its stem. '
 'A small burst of tiny pastel fluff motes puffs out behind the letters on the strongest landing and disperses in the air. '
 'The camera makes one short smooth swooping arc from slightly low-left toward a frontal hero angle, with a small pull-back on the landing and a confident push to the final centred title. '
 'Keep the entire word clearly readable and inside frame. The pale icy-blue abstract studio background and soft floating contact shadow stay clean and minimal. '
 'In the last two seconds, the letters settle into the exact beautiful fully readable closing-image pose and hold. The final word fills most of the frame width. '
 'This is a polished playful eight-second brand intro with substantial visible three-dimensional movement, tactile fur and comic timing. '
 'SOUND: airy camera whoosh, a short sequence of warm plush boings and soft puffy impacts exactly with the bouncing letters, a tiny bright pop on the hopping dot and a gentle sparkling finish. '
 'Non-vocal designed effects only; no person, character voice, spoken word, language, singing or narration. Do not generate background music; an original musical signature is added afterward. '
 'No other text, no extra copies of the logo, no changing letters, no flat font overlay, no garden, no landscape, no characters, no hard cuts or transitions.')
spec=dict(title='Fluffies — app-rendered rainbow 3D furry logo ident',fps=24,total_seconds=8,total_frames=192,
 master_filename='Fluffies_App_Rainbow_Intro_8s.mp4',
 settings=dict(engine='ltx',mode='frames',steps='8',ltx_quality='balanced',aspect_ratio='16:9',ltx_sharp_decode='true',ltx_calm_sampler='false',no_audio='false'),
 shots=[dict(id='B01',title='Rainbow furry logo bounce',duration=8,edit_frames=192,seed=1024251,
 frame='frames/B01.png',closing_frame='frames/B01.png',clip='clips/B01.mp4',video_prompt=prompt)],
 review='User visual/listening review; no AGY, delegated agents or strict inspection gates',
 source='User-selected rainbow furry wordmark; same exact opening/closing anchor; main bridge 8787, ComfyUI 8190')
(OUT/'manifest.json').write_text(json.dumps(spec,indent=2))
(OUT/'B01-video-prompt.txt').write_text(prompt)
print(OUT/'manifest.json')
