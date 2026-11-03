"""Create a portable local storyboard from the frozen episode manifest."""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'state' / 'tumble_puffs_ep01'
spec = json.loads((OUT/'manifest.json').read_text())
cards = []
for shot in spec['shots']:
    tc = lambda t: f'{t//60:02d}:{t%60:02d}'
    esc = html.escape
    cards.append(f'''<article><img src="{esc(shot['frame'])}" alt="Opening frame for {shot['id']}">
    <div class="meta">{shot['id']} · {tc(shot['start'])}–{tc(shot['end'])} · {shot['duration']}s</div>
    <h2>{esc(shot['title'])}</h2><p>{esc(shot['action'])}</p>
    <small>{esc(shot['camera'])}</small></article>''')
page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tumble Puffs — The Runaway Berry</title><style>
*{box-sizing:border-box}body{margin:0;background:#f7f3e8;color:#17382c;font:17px/1.5 system-ui,sans-serif}
header,main{max-width:1440px;margin:auto;padding:30px}header{padding-bottom:8px}h1{font-size:42px;line-height:1.1;margin:10px 0}
.eyebrow{letter-spacing:.13em;text-transform:uppercase;color:#567467;font-size:13px;font-weight:700}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:24px}
article{background:white;border-radius:16px;overflow:hidden;box-shadow:0 3px 16px #163c2812;padding-bottom:22px}
img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#dbe9d5}
h2,p,small,.meta{margin-left:22px;margin-right:22px}h2{font-size:22px;margin-top:6px;margin-bottom:8px}
.meta{font-size:13px;font-weight:700;color:#668471;margin-top:16px}p{font-size:15px}small{display:block;color:#6d7a70}
@media print{main{grid-template-columns:1fr 1fr}article{break-inside:avoid}header{padding-top:0}h1{font-size:28px}}
</style><header><div class="eyebrow">Tumble Puffs · Episode 01</div><h1>The Runaway Berry</h1>
<p>120 seconds · 20 LTX clips · hard cuts · silent pantomime · original instrumental score</p>
<p>One oversized blueberry defeats three separate plans. A leaf hammock finally brings the friends together.</p></header><main>'''+''.join(cards)+'</main></html>'
(OUT/'STORYBOARD.html').write_text(page,encoding='utf-8')
print(OUT/'STORYBOARD.html')
