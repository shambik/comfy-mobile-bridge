"""Verify and publish the replacement rainbow furry-title intro to the bridge."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).parent/'tumble_puffs_ep01'))
import episode_runner as bridge
OUT=ROOT/'state'/'fluffies_brand_intro'
final=OUT/'Fluffies_Rainbow_3D_Intro_8s.mp4'
proof=bridge.probe(final,192,audio=True)
assert proof['decoded_frames']==192 and abs(proof['duration']-8)<.001
bridge.OUT,bridge.JOURNAL,bridge.FINAL=OUT,OUT/'execution.json',final
data=bridge.read()
data.update(master=proof,composition=str(ROOT/'.runtime'/'labs'/'fluffies-brand-intro'/'film'),
            title='Fluffies — rainbow furry 3D title intro',review='User visual/listening review',
            render=dict(framework='HyperFrames 0.8.188',seconds=16.9,capture='screenshot',gpu='hardware'),
            selected_logo=str(OUT/'fluffies-logo-rainbow-v2.png'))
bridge.write(data)
bridge.publish(final,192,'Fluffies - Rainbow furry 3D title intro - v2.mp4')
