"""Use the already installed/cached Whisper model on CPU; install nothing."""
import argparse
import json
from pathlib import Path
import torch
import whisper

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'night_train'

def main(keys):
    name='large-v3-turbo'
    cached=Path.home()/'.cache'/'whisper'/(whisper._MODELS[name].split('/')[-1])
    if not cached.is_file():
        raise SystemExit('The documented Whisper cache is absent; no download or install attempted.')
    torch.set_num_threads(2)
    model=whisper.load_model(name,device='cpu',download_root=str(cached.parent))
    results={}
    report=OUT/'speech_results.json'
    if report.exists():results=json.loads(report.read_text())
    for key in keys:
        result=model.transcribe(str(OUT/f'{key}.wav'),fp16=False,language='en',temperature=0,condition_on_previous_text=False)
        results[key]={'text':result['text'].strip(),'segments':[{k:s.get(k) for k in ('start','end','text','avg_logprob','no_speech_prob')} for s in result['segments']],'device':'cpu','model':name,'note':'ASR output only; hallucinations on music and nonverbal sounds are possible. User performs listening review.'}
        report.write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(key,results[key]['text'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('keys',nargs='+');a=p.parse_args();main(a.keys)
