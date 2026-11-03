"""Fluffies: The Great Shortcut. Motion, shared physical comedy, varied locations."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'state'/'fluffies_ep01_shortcut'
CAST={
 'Pip':'small coral-red pear-shaped fluffy Pip, curled top tuft, brown eyes, tiny mitten paws and broad little feet',
 'Momo':'broad lemon-yellow cushion-shaped fluffy Momo, swept-up tuft, gentle brown eyes, tiny mitten paws and broad feet',
 'Tiki':'tall slim mint-green fluffy Tiki, two side tufts, green eyes, thoughtful brows, tiny mitten paws and broad feet',
}
STYLE=('Original polished colourful 3D preschool comedy, exact selected Fluffies cast identities, short soft fur, expressive eyes and brows, '
 'warm sunlight, clear full-body silhouettes, grounded contact shadows, springy body weight and readable visual jokes. ')
PROP=('One small oval tan wicker picnic hamper with a single curved handle contains a folded yellow-and-white striped blanket, '
 'three blue cups and simple carrot sticks. Keep it consistent; it is luggage, not a chased object. No blueberries anywhere. ')
HOME=('The home is the intro reference\'s small round yellow cottage, domed straw-yellow roof, brown oval door, round window, '
 'pink flowers beside the doorstep. A sunny footpath curves away into rolling meadows; a big round oak shades a lawn nearby. ')
ROWS=[
 ('Off on an adventure',['Pip','Momo','Tiki'],
  'Wide low three-quarter view outside the distinctive round yellow cottage. Pip leads toward screen right with one foot raised; Momo follows holding the picnic hamper by its handle; Tiki walks beside Momo. Their whole bodies and feet are visible. The broad path curves toward a distant oak and grassy picnic hill. No stump or berry props.',
  'All three actually walk several steps away from the cottage toward screen right. Pip eagerly skips ahead, turns while still moving and beckons the other two. Momo waddles with the gently swinging hamper; Tiki catches up with a lively confident stride.',
  'Lateral tracking move following the group; the cottage moves behind them. Keep feet visible.',
  'Clear alternating footfalls, wicker creak, Pip\'s delighted short giggle and Momo\'s warm breathy pleased hum. No words.'),
 ('Pip knows a shortcut',['Pip','Momo','Tiki'],
  'At a fork in the meadow path, all three are shown full-body. Tiki stands left indicating the broad safe winding path; Pip at centre points excitedly toward a narrow opening between two low hedges at right. Momo waits behind holding the picnic hamper. A distant yellow playground slide is glimpsed beyond the hedge. No signs or text.',
  'Pip gently takes Tiki\'s paw and leads Tiki three quick steps toward the narrow shortcut. Tiki gives an uncertain head tilt, then follows. Momo shrugs with one free paw and walks after them, swinging the hamper. The group leaves the fork together.',
  'Start wide and pan right with their departure; show real steps and linked paws.',
  'Pip\'s eager squeaky chuckle, Tiki\'s short questioning nasal chirp, Momo\'s soft amused breath, quick light footsteps.'),
 ('The easy stones',['Pip','Tiki'],
  'Wide side view of a shallow sparkling meadow puddle with three broad flat stepping stones. Pip stands on the first stone at left, body coiled to hop toward the next. Tiki waits just behind on the bank. Clear visible feet and a safe tiny gap between stones. Reeds and a low willow replace the cottage background; Momo and the hamper are off camera.',
  'Pip makes two small energetic hops from stone to stone toward screen right, landing with clear squash and spring. Tiki follows with careful alternating steps and outstretched paws for balance. Pip reaches the dry bank and turns proudly toward Tiki.',
  'Wide lateral tracking at knee height, showing the water and both landings.',
  'Two soft stone taps, a little water plip, Pip\'s breathy excited squeak, Tiki\'s tiny balancing gasp.'),
 ('Momo takes one big step',['Pip','Momo','Tiki'],
  'Wide low view across the same shallow puddle. Momo stands on the near-left bank with one broad foot lifted toward the water, picnic hamper safely held high. Pip and Tiki stand close together on the dry far-right bank, looking back expectantly. The water is only ankle-deep, with soft mud and reeds.',
  'Momo takes one overconfident broad step into the shallow puddle. A rounded sheet of water splashes Pip and Tiki. They both recoil and blink with startled dripping faces; Momo looks at the wet foot, then at the friends, and gives a sheepish little shoulder shrug. One clear comic splash.',
  'Hold a broad readable composition through the splash, then a tiny push toward their reactions.',
  'A broad friendly splosh, two brief surprised nonverbal squeaks, dripping water and Momo\'s soft embarrassed chuckle. No spoken exclamations.'),
 ('A rather narrow shortcut',['Pip','Momo','Tiki'],
  'Full-body three-quarter view of a narrow opening between two springy rounded green hedges. Pip and Tiki have already passed through to the foreground left and look back. Momo stands partly wedged in the soft gap, shoulders gently compressed, face visible. The picnic hamper sits safely on the grass beside Pip. A meadow trail is visible beyond the hedge.',
  'Momo tries two tiny waddling steps through the narrow gap but the soft hedges hold the broad fluffy middle. Pip and Tiki exchange a look, walk back and each offer a paw to help. Momo reaches both paws forward with a hopeful expression.',
  'A gentle sideways dolly to show the gap and Momo\'s clear full silhouette; no extreme close-up.',
  'Soft leafy scrunches, two small rounded effort grunts from Momo, Pip\'s surprised chirp and Tiki\'s sympathetic breathy hum.'),
 ('One, two... pop!',['Pip','Momo','Tiki'],
  'Low wide view of the hedge gap. Momo faces toward the open grass in the foreground; Pip at left and Tiki at right each hold one of Momo\'s mitten paws. They lean back slightly with feet planted. The hamper is on the grass safely off to the left. Soft open grass gives them room to land.',
  'Pip and Tiki lean back together and pull gently. Momo squeezes free in one soft springy pop. The sudden release makes all three take two wobbly backwards steps and settle seated on the soft grass together. They look at one another and break into short happy giggles. No hard collision.',
  'Hold the full group and their feet in frame; one modest backward track with the release.',
  'Three short coordinated breathy effort sounds, leafy pop, soft grass thumps and distinct overlapping nonverbal giggles. No counting or words.'),
 ('A much better way down',['Pip','Momo','Tiki'],
  'Wide travelling view entering a bright meadow playground. A broad low yellow slide with three wooden steps and a soft blue landing mat dominates screen right; round play towers and wooden rails sit behind. Pip leads at left with one foot raised, pointing eagerly toward the slide. Momo carries the hamper again; Tiki walks alongside.',
  'The trio walks into the playground from left to right. Pip spots the slide, gives a delighted little hop and jogs toward its steps. Tiki follows at a quick trot while Momo continues a slower bouncing walk with the hamper. Make the change of location and visible travelling unmistakable.',
  'Smooth lateral tracking with strong foreground/background parallax; whole bodies stay visible.',
  'Changing footstep rhythms, Pip\'s delighted giggle, Tiki\'s airy curious chirp, Momo\'s friendly breathy chuckle and soft playground ambience.'),
]

ROWS += [
 ('Race you to the top',['Pip','Tiki'],
  'Wide side view of the playground\'s three low wooden steps leading to a broad yellow slide. Pip stands on the bottom step, leaning forward with one foot raised to climb; Tiki follows at ground level with paws spread for balance. A soft blue landing mat is visible below the slide. Momo and the hamper are off screen.',
  'Pip climbs the three steps in a quick alternating-foot trot, reaches the top and turns with a proud grin. Tiki climbs carefully after Pip, pausing for one exaggerated steadying breath. Keep actual stepping and changing height clearly visible.',
  'Track upward beside the steps, keeping both complete bodies in view.',
  'Quick wooden foot taps, Pip\'s excited breathy squeak, Tiki\'s short effort puffs and a relieved little giggle.'),
 ('Pip takes the fast way',['Pip','Tiki'],
  'Low wide three-quarter view along the complete yellow slide toward the soft blue mat. Pip sits at its upper lip with feet forward and paws slightly raised. Tiki waits beside the landing mat at screen right, looking up with amused anticipation. Open playground grass and round play towers fill the background.',
  'Pip slides smoothly all the way down, fur and tuft trailing naturally, then lands on the soft mat and skids a tiny distance on the feet. Tiki sidesteps the landing and gives a delighted little two-paw clap. Pip hops up and gestures proudly toward the slide.',
  'A smooth low pan follows Pip from slide to landing; show the full travel path.',
  'A light slide swish, one delighted nonverbal squeal from Pip, a soft mat thump and Tiki\'s airy chuckle. No words.'),
 ('The slide is a little snug',['Momo'],
  'Medium-wide full-body view of Momo seated at the top of the broad yellow slide, feet pointing down the chute. The fluffy yellow middle is just a little wider than the soft slide rails. Momo holds the rail edges lightly with both paws, looking eager and slightly uncertain. The hamper waits safely on a bench in the background; no other characters are on camera.',
  'Momo tries to slide but stays gently wedged. Momo rocks the hips left and right in two funny effortful wiggles, compressing the fluffy sides slightly, then pauses and looks down with a puzzled head tilt. The last wiggle starts Momo moving a little. No painful squeeze or violent motion.',
  'Hold the whole seated body and both rails clearly, with a modest slow push in.',
  'Two rounded comic effort grunts, soft fur-on-plastic squeaks and a short surprised breath when Momo starts to move. No spoken exclamation.'),
 ('A very soft landing',['Pip','Momo','Tiki'],
  'Wide side view of the full low yellow slide and the large blue soft mat. Momo is at the upper half of the chute ready to slide. Pip and Tiki stand on the far end of the mat with feet planted, paws open to help and plenty of safe landing space. The picnic hamper remains on the nearby bench.',
  'Momo finally slides down with a small springy release. Pip and Tiki reach forward to help at the bottom; Momo\'s soft arrival makes all three wobble together and settle seated in a fluffy little pile on the mat. They untangle their paws, look at one another and giggle. One gentle landing, no hard crash, no bodies merging.',
  'Track down the slide slightly, then hold wide on the shared landing and reaction.',
  'A growing slide swish, Momo\'s short rounded surprised grunt, a soft cushioned whump, Pip and Tiki\'s brief gasps and three distinct happy nonverbal giggles.'),
 ('Together is easier',['Pip','Momo','Tiki'],
  'Wide travelling view on a winding meadow trail leaving the playground. All three stand side by side facing screen right, ready to walk; Momo carries the single picnic hamper again. Pip looks a little sheepish, Tiki amused, Momo content. The yellow slide recedes far behind and the path curves toward a large round oak, with tall flowers hiding what lies beyond.',
  'They walk together along the curve with clear alternating steps. Pip starts to rush, notices the others, slows down and gently takes Tiki\'s free paw. Momo catches up alongside, and they continue at one shared easy pace toward the oak.',
  'Sideways tracking with a clear change of background and visible feet; no stationary talking poses.',
  'Three different footstep weights becoming one rhythm, relaxed breathing, Pip\'s small apologetic chirp and the others\' warm amused chuckles. No words.'),
 ('A blanket with ideas',['Pip','Momo','Tiki'],
  'Medium-wide low view on a grassy picnic patch beneath a huge round oak. Pip at left and Tiki at right hold two corners of the same yellow-and-white striped blanket; Momo stands behind it with one foot ready to pin the rear corner. The open hamper with three blue cups rests safely beside the tree. Tall flowers screen the distant background.',
  'As Pip and Tiki lower the blanket, a tiny breeze flips its near edge over Pip\'s head. Momo calmly places one broad foot on the rear corner to stop it. Tiki gently lifts the fabric away to reveal Pip\'s surprised fluffy face; Pip blinks, grins and joins their giggles. A single shared fabric gag.',
  'Hold the whole blanket and three characters, then a small push toward the reveal of Pip\'s face.',
  'A brief airy gust, soft cloth flutter, Pip\'s muffled surprised squeak, a little foot tap and three affectionate nonverbal giggles.'),
 ('The great shortcut',['Pip','Momo','Tiki'],
  'Begin medium-wide on the trio seated on the striped picnic blanket beneath the oak, hamper and three blue cups beside them. Pip holds one carrot stick, Tiki leans back happily and Momo looks beyond Pip with dawning recognition. Behind flowers at left, the same distinctive round yellow cottage from the departure is partly visible; no new buildings or text.',
  'The camera pulls back and rises enough to reveal that their picnic oak is right beside the very cottage they left. Momo points at the familiar cottage. Pip turns, pauses in sheepish disbelief, then gives a tiny open-paw shrug. Tiki leans against Pip with an amused shoulder nudge; all three share warm giggles and settle into their picnic. Hold the final clear wide tableau.',
  'One smooth substantial pull-back and slight rise reveals the cottage and the short distance from its doorstep to their picnic; finish steady.',
  'Momo\'s low surprised hum, Pip\'s small ascending questioning chirp, Tiki\'s light chuckle and three warm nonverbal giggles, quiet birds and gentle leaves. No speech.'),
]


def build():
    for folder in ['frames','clips','prompts']:
        (OUT/folder).mkdir(parents=True,exist_ok=True)
    shots=[]
    at=8
    for number,row in enumerate(ROWS,1):
        title,cast,opening,action,camera,sound=row
        duration=6 if number in [2,7] else 10 if number in [6,11] else 8
        identity='; '.join(CAST[name] for name in cast)
        context=HOME if number in [1,14] else ''
        image_prompt=(STYLE+context+PROP+'Create ONE finished landscape 16:9 animation opening frame. '
          'Use the supplied cast image for exact character identities and fur style. Show ONLY the specific location described here, not a repeated generic garden. '
          f'On camera: {identity}. '+opening+' '
          'This is the anticipation pose BEFORE the action: '+action+' '
          'Full bodies, feet and clear travel space matter. Keep paws simple and characters separate. '
          'No text, arrows, subtitles, signs, clothing, extra characters, blueberry, pinwheel or stump table. No panels or collage.')
        video_prompt=(STYLE+f'Preserve the exact opening-frame cast: {identity}. '+PROP+
          f'During this {duration}-second single shot, begin the physical action promptly: '+action+' Camera: '+camera+' '
          'Show real locomotion, clear foot placement, weight transfer and responsive contact between the friends; do not replace the action with stationary mouth movement. '
          'SOUND: '+sound+' Each character has short expressive cartoon vocalizations matched to the visible effort or reaction: '
          'Pip bright and squeaky, Momo warm and rounded, Tiki light and airy. No spoken words, no conversation, no gibberish language, no narration, singing or lyrics. '
          'Use outdoor ambience and action-matched effects, but no generated background music; an original score is mixed underneath later. '
          'One coherent shot, no internal cut, no lettered signs, no duplicated bodies, no fast spins, no unexplained prop changes.')
        shot=dict(id=f'E{number:02d}',number=number,title=title,cast=cast,duration=duration,
          start=at,end=at+duration,edit_frames=duration*24,seed=1024300+number,
          frame=f'frames/E{number:02d}.png',clip=f'clips/E{number:02d}.mp4',
          image_prompt=image_prompt,video_prompt=video_prompt,opening=opening,action=action,camera=camera,sound=sound)
        shots.append(shot)
        for kind in ['image','video']:
            (OUT/'prompts'/f'E{number:02d}-{kind}.txt').write_text(shot[f'{kind}_prompt'],encoding='utf-8')
        at+=duration
    assert len(shots)==14 and at==120 and sum(s['edit_frames'] for s in shots)==2688
    spec=dict(title='Fluffies — The Great Shortcut',fps=24,total_seconds=112,total_frames=2688,
      full_episode_seconds=120,full_episode_frames=2880,intro_seconds=8,
      intro='state/fluffies_brand_intro_app/Fluffies_App_Rainbow_Intro_8s.mp4',
      settings=dict(engine='ltx',mode='opening',steps='8',ltx_quality='balanced',aspect_ratio='16:9',ltx_sharp_decode='true',ltx_calm_sampler='false',no_audio='false'),
      shots=shots,review='User visual/listening review; no AGY, subagents or strict inspection gates',
      audio_policy='Preserve generated action sounds/nonverbal character vocalizations; mix original instrumental score underneath. No speech or narration.')
    (OUT/'manifest.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    lines=['# Fluffies — production plan','',
      '## Current user direction','',
      'The series is **Fluffies**. The user liked the character look but rejected the repetitive blueberry staging. '
      'The next episode must show walking, movement, shared physical comedy, changing locations and action-matched nonverbal character sounds. '
      'No spoken words or narration. The user is the visual/listening reviewer. No AGY, subagents or strict inspection gates.','',
      '## Completed pilot cut','',
      'The berry producer is stopped after S15. All 15 completed clips were hard-cut into an 89-second music cut. '
      'Vault item `bb99d3116db0475fbbf75a15bc1de80f`; local `state/fluffies_berry_pilot_cut/Fluffies_Berry_Pilot_89s_with_music.mp4`. '
      'S16–S20 remain unrendered and must not be resumed.','',
      '## Series intro','',
      'The walking-scene intro was rejected. The user selected huge fluffy three-dimensional letters and asked for a richer palette including blue, purple and pink. '
      'The rainbow logo asset is `state/fluffies_brand_intro/fluffies-logo-rainbow-v2.png`. '
      'A graphic intro was delivered as vault item `0660e90e09ed4d25a0e768fbb3143af4`. '
      'The user then requested a cooler version **using the app**. The completed LTX first+last-frame logo intro is vault item `0ea7464e987a4bf58e52d9007b91073a`. '
      'The eight-second master is `state/fluffies_brand_intro_app/Fluffies_App_Rainbow_Intro_8s.mp4`; it passed exact-frame and full audio/video decode checks. '
      'Its plan is `fluffies_app_intro_plan.py`, with identical opening/closing title anchors, native designed effects and original music mixed afterward.','',
      '## Additional cast','',
      'Five new character identities were created in blue, pink, purple, pearl-white and smoky-grey shades. '
      'See [FLUFFIES_CAST_EXPANSION.md](FLUFFIES_CAST_EXPANSION.md) for names, silhouettes, palettes and assets. '
      'The current episode keeps Pip, Momo and Tiki so completed shots remain consistent.','',
      '## New episode: The Great Shortcut','',
      'A picnic trip becomes an overconfident shortcut: stepping stones, a splash, a hedge squeeze and a playground slide. '
      'The trio learn to move together, set their picnic, then realize the long adventure has brought them back beside their cottage. '
      'The journey and friendships carry the comedy; the hamper is simply luggage.','',
      'The finished episode is exactly 120 seconds: the eight-second series intro plus 112 seconds of story, all at 24 fps. '
      'Every picture transition is a hard cut. Keep generated vocal reactions and effects, with an original instrumental score underneath.','',
      '| Shot | Full timeline | Length | Action / travel | Sound |','| --- | --- | --- | --- | --- |',
      '| Intro | 00:00–00:08 | 8 s | Rainbow furry 3D Fluffies wordmark, app-rendered bounce wave and hopping i-dot | Music signature and designed non-vocal effects |']
    tc=lambda t:f'{t//60:02d}:{t%60:02d}'
    for s in shots:
        lines.append(f"| {s['id']} · {s['title']} | {tc(s['start'])}–{tc(s['end'])} | {s['duration']} s | {s['action']} | {s['sound']} |")
    lines+=['','## Execution / resume','',
      '- Source: `docs/ltx25_test/fluffies_episode_plan.py`; frozen manifest/prompts: `state/fluffies_ep01_shortcut/`.',
      '- Still images: built-in ImageGen using the selected cast; preserve source images and vary the actual location by shot.',
      '- Video: `python docs/ltx25_test/tumble_puffs_ep01/episode_runner.py render --out state/fluffies_ep01_shortcut`.',
      '- Score: run `docs/ltx25_test/fluffies_shortcut_score.py` using the bundled media Python with numpy.',
      '- Native-audio editor: `python docs/ltx25_test/fluffies_shortcut_finish.py --wait --publish`. It waits for all verified clips, assembles exact hard cuts and publishes the 120-second master.',
      '- A 22-second opening preview is vault item `2d19761ddcda4042bc2bda972155c203`; this is work in progress, not the full episode.',
      '- All 14 opening frames, exact ImageGen provenance and `storyboard.html` are under the episode state folder.',
      '- One main bridge on 8787, one ComfyUI on 8190. No runtime, package, model or workflow changes in the app.',
      '- Existing Balanced landscape 1600×896, eight steps, sharp decode, calm sampler off; native audio enabled.',
      '- Poll journaled IDs on resume. Never blindly repeat an uncertain POST or cancel a running job without user direction.',
      '- `STOPPED.json` in a run folder prevents new submissions; it never cancels the current job.',
      '- Native sources require ffprobe plus full FFmpeg decode. Trim by frame count. Full episode: 2880 frames at 24 fps.',
      '- Finish with exact picture cuts, native audio trimmed to the same windows, and original instrumental music. Publish through the main Video Vault and verify SHA-256.',
      '- HyperFrames source for the earlier graphic intro is isolated in `.runtime/labs/fluffies-brand-intro/film`; snapshots must use `--describe false` to keep review here.',
      '- If subagents are later explicitly requested, use GPT-6.1 Sol / medium; none are used in this plan.',
      '- App build/preflight passed. Existing suite result: 301/302; user AGENTS.md length assertion remains unrelated and must not be fixed by rewriting user instructions.','']
    Path(__file__).with_name('FLUFFIES_PRODUCTION_PLAN.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(story_shots=len(shots),story_seconds=112,full_seconds=120,manifest=str(OUT/'manifest.json'))))


if __name__=='__main__':
    build()
