"""Summarize real bridge render measurements and media proof; never invent results."""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT/'state'/'tumble_puffs_ep01'
spec = json.loads((OUT/'manifest.json').read_text())
journal = json.loads((OUT/'execution.json').read_text())
rows = []
for shot in spec['shots']:
    item = journal['items'].get(shot['id'],{})
    if item.get('status') != 'verified':
        continue
    metrics = item['response']['metrics']
    rows.append(dict(shot=shot['id'],title=shot['title'],edit_seconds=shot['duration'],
                     edit_frames=shot['edit_frames'],seed=shot['seed'],job_id=item['id'],
                     generation_seconds=metrics['generation_seconds'],
                     peak_gpu=metrics.get('peak_gpu'),source_proof=item['proof']))
by_duration = {}
for seconds in sorted({r['edit_seconds'] for r in rows}):
    values = [r['generation_seconds'] for r in rows if r['edit_seconds']==seconds]
    by_duration[str(seconds)] = dict(count=len(values),min=min(values),max=max(values),
                                    mean=round(statistics.mean(values),1))
report = dict(title=spec['title'],verified_shots=len(rows),total_shots=20,
              verified_edit_seconds=sum(r['edit_seconds'] for r in rows),
              generation_seconds=round(sum(r['generation_seconds'] for r in rows),1),
              by_duration=by_duration,shots=rows,master=journal.get('master'),
              publish=journal.get('publish'),
              review='User artistic review; technical proof does not imply artistic acceptance')
(OUT/'measured_results.json').write_text(json.dumps(report,indent=2))
lines = ['# Episode 01 measured results','',
         f"{len(rows)}/20 shots verified; {report['verified_edit_seconds']}/120 editorial seconds.",'',
         '| Shot | Clip | Render | Job | Source media |',
         '| --- | --- | --- | --- | --- |']
for row in rows:
    proof = row['source_proof']
    lines.append(f"| {row['shot']} | {row['edit_seconds']} s | {row['generation_seconds']} s | `{row['job_id']}` | {proof['decoded_frames']} frames; silent; full decode passed |")
if report['master']:
    lines += ['', '## Master','',json.dumps(report['master'],indent=2)]
if report['publish']:
    lines += ['', '## Main bridge Video Vault','',f"Item: `{report['publish']['item']['id']}`; SHA-256 `{report['publish']['sha256']}`."]
(Path(__file__).parent/'MEASURED_RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k not in {'shots','master','publish'}}))
