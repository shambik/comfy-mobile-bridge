"""Build a local, readable storyboard from the frozen episode manifest."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state/fluffies_ep02_carnival'
spec=json.loads((OUT/'manifest.json').read_text(encoding='utf-8'))
esc=html.escape
cards=[]
for shot in spec['shots']:
    cards.append(f'<article><a href="{shot["frame"]}"><img src="{shot["frame"]}" alt="{esc(shot["title"])}"></a>'
                 f'<h2>{shot["id"]} · {esc(shot["title"])}</h2>'
                 f'<p class="meta">{shot["start"]:g}–{shot["end"]:g}s · {shot["edit_seconds"]:g}s · {esc(", ".join(shot["cast"]))}</p>'
                 f'<p>{esc(shot["action"])}</p><details><summary>Camera, sound and exact prompt</summary>'
                 f'<p>{esc(shot["camera"])}</p><p>{esc(shot["sound"])}</p><p>{esc(shot["video_prompt"])}</p></details></article>')
document='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fluffies — The Wobbly Surprise storyboard</title><style>
body{margin:0;background:#faf4ed;color:#303348;font:16px/1.55 system-ui}header{max-width:1250px;margin:auto;padding:32px}
h1{margin:0 0 10px}header p{max-width:1000px}.opener{max-width:640px;width:100%;border-radius:14px}
main{max-width:1600px;margin:auto;padding:24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}
article{background:white;padding:16px;border-radius:18px;box-shadow:0 5px 18px #44302414}img{width:100%;aspect-ratio:1672/941;object-fit:contain;border-radius:10px}
h2{font-size:20px}.meta{color:#66586e;font-size:14px}details p{font-size:13px}a{color:#3855a1}
</style><header><h1>Fluffies — The Wobbly Surprise</h1>
<p>Lulu distracts Bobo while six friends prepare a party. A wobbling cake, tangled ribbon and uncooperative balloons turn a perfect surprise into a wonderfully messy celebration.</p>
<p>Selected opener: <strong>1002475080.mp4</strong>, used in full with its original soundtrack. Then twenty story cuts with real movement, native nonverbal reactions and original instrumental music. Total two minutes at 24 fps, 1080p. The user reviews visual and listening quality.</p>
<video class="opener" controls preload="metadata" src="refs/1002475080.mp4"></video>
<p><a href="../../docs/ltx25_test/FLUFFIES_WOBBLY_SURPRISE_PLAN.md">Production plan</a> · <a href="manifest.json">Frozen manifest</a></p>
</header><main>'''+''.join(cards)+'</main></html>'
(OUT/'storyboard.html').write_text(document,encoding='utf-8')
print(OUT/'storyboard.html')
