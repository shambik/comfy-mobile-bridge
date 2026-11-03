"""Frozen creative/editorial source for the 120-second pantomime episode."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'state' / 'tumble_puffs_ep01'
FPS = 24
CAST = {
    'Pip': 'the small coral-red pear-shaped fluffy creature, curled top tuft, warm brown eyes, tiny mitten paws and broad feet',
    'Momo': 'the much wider lemon-yellow cushion-shaped fluffy creature, little swept-up tuft, gentle brown eyes, tiny mitten paws and broad feet',
    'Tiki': 'the tall slim mint-green fluffy jellybean creature, two side tufts, green eyes, thoughtful brows, tiny mitten paws and broad feet',
}
STYLE = ('Polished colourful 3D preschool cartoon with the exact original fluffy character designs of the supplied cast reference. '
         'Short soft fur, rounded bodies, expressive eyes and brows, simple mitten paws, warm sunny side-light, soft shadows, vivid natural colours. ')
WORLD = ('Bounce Patch is an oversized sunny flower garden: short grass, pink flowers and white daisies, a winding stepping-stone path, '
         'large rounded leaves, a leafy arch and blue sky. A low round wooden stump is the picnic table; three round green leaf plates '
         'and a small shallow tan wicker basket belong there. A gently sloping patch of grass leads rightward toward a large broad-leaf bush. ')
BERRY = ('The story prop is one oversized, firm, round dusty-indigo blueberry, with a small dark five-point star-shaped crown, '
         'about half the height of Pip\'s head. It looks the same in every shot and behaves like a soft, slowly rolling ball. ')
SILENT = ('Pure silent pantomime: tell the joke with eye direction, eyebrows, head tilts, pauses, body poses and paw gestures. '
          'No speaking, lip-sync, conversational lip flapping, singing, narration, words, gibberish, subtitles, symbols or visible text. ')

# duration, beat, on-camera cast, opening composition, one dominant action, camera, exit state
ROWS = [
 (6, 'A picnic for three', ['Pip','Momo','Tiki'],
  'Eye-level wide view: Pip left, broad Momo centre-back and tall Tiki right stand around the low stump picnic table. The single blueberry rests on a leaf plate at the table centre, with the empty wicker basket behind it. All three look eagerly at the berry; paws lowered, distinct full silhouettes. No pinwheel or cushion is present.',
  'Pip leans forward eagerly; Momo calmly rubs the belly once; Tiki straightens a leaf plate with one precise paw. They glance at one another and return their gaze to the single berry, each clearly expecting a share.',
  'A very small slow push toward the table; keep all three faces and the berry visible.', 'Their attention converges on the berry.'),
 (5, 'Too eager', ['Pip'],
  'Close three-quarter view of Pip at the left of the stump. The blueberry sits on a shallow leaf plate near the right edge of the tabletop. Pip has one mitten paw raised just short of the berry, eyes bright with anticipation. The table edge and a little grass below are visible.',
  'Pip reaches too quickly and nudges the edge of the leaf plate. The berry rolls a few centimetres toward the table edge. Pip freezes with paw extended and eyes suddenly wide. Cut before a complicated fall.',
  'Static close view with clear paw/plate/berry spacing.', 'The berry is poised to leave the table; Pip has made a mistake.'),
 (6, 'Momo helps', ['Momo'],
  'Low medium view on the grass beside the picnic stump. The blueberry is already on the ground just in front of Momo\'s right foot; this is a hard-cut time jump after its fall. Momo bends carefully, one paw hovering beside the berry, an earnest helpful expression.',
  'Momo carefully brings the paw down to catch the berry but gently nudges it instead. The berry rolls one body-width to screen right. Momo looks at the empty paw, then slowly follows the berry with the eyes.',
  'Hold low and steady, with room at screen right for the roll.', 'The berry escapes rightward; Momo is puzzled.'),
 (5, 'Tiki has a system', ['Tiki'],
  'Medium three-quarter view further along the same rightward garden path. Tiki stands at screen right with a large broad leaf held upright like a simple barrier. The blueberry sits at screen left, just before the leaf. Tiki looks confidently down the path. No other creatures.',
  'The blueberry rolls slowly right and stops against the broad leaf. Tiki straightens proudly, raises the chin and makes a small satisfied closed-mouth smile while keeping the leaf planted.',
  'Static eye-level composition; barrier and berry readable in the lower half.', 'Tiki thinks the problem is solved.'),
 (6, 'The flexible solution', ['Tiki'],
  'Ground-level view of the same broad leaf barrier and Tiki\'s feet. The blueberry presses against the leaf\'s lower left edge. Tiki holds the stem above; the face is still visible in the upper third, confidently looking ahead.',
  'The soft leaf gradually bends under the berry. Its bottom edge lifts enough for the berry to roll gently past to screen right. Tiki looks down, pauses and blinks at the now useless leaf.',
  'A restrained upward tilt from leaf/feet to the disappointed face.', 'The berry has passed the leaf; Tiki\'s confidence collapses.'),
 (5, 'Pip has an idea', ['Pip'],
  'Medium close view of Pip crouched beside a thick round sky-blue squishy cushion lying flat on the grass. The blueberry rests a short distance to the cushion\'s right. Pip looks from the berry to the cushion, one mitten paw resting on the chin. No other creatures.',
  'Pip glances between berry and cushion, then raises one paw with an eager idea and gives a tiny confident nod. Pip places the raised paw over the cushion, ready to try the plan.',
  'Static low eye-level framing, cushion clearly visible.', 'Pip is about to try a bouncy solution.'),
 (7, 'A little too bouncy', ['Pip'],
  'Medium-wide low view of Pip at left beside the sky-blue cushion. The blueberry rests in the centre of the cushion. Pip\'s paw hovers above its near edge, feet firmly on the grass. There is free space above and to the right of the cushion.',
  'Pip slowly presses the cushion edge with one paw, visibly squashing it, then releases. The cushion returns to shape and gives the berry one small gentle hop. Pip\'s pleased face changes to alarm as the berry rolls off toward screen right. Keep the hop small and readable.',
  'Hold a clear three-quarter view; no fast spin or camera shake.', 'The berry has bounced out of Pip\'s control.'),
 (6, 'The missing berry', ['Momo'],
  'Medium front view of Momo seated on soft grass, both feet visible. After a hard-cut time jump, the blueberry is perched securely on Momo\'s swept-up tuft. Momo does not know it is there and looks down at the empty grass, paws open in confusion.',
  'Momo searches left and right with the eyes, then raises both little paws beside the head without reaching the blueberry. The berry remains balanced on the tuft as Momo tilts the head only slightly and looks puzzled.',
  'Static frontal view with comfortable headroom above the blueberry.', 'The audience can see the berry that Momo cannot.'),
 (6, 'Look up', ['Tiki','Momo'],
  'Medium two-shot: Tiki at left foreground, Momo seated at right. The blueberry is still perched on Momo\'s top tuft. Tiki looks directly at the berry and has one mitten paw ready to point upward. Momo looks at Tiki expectantly.',
  'Tiki slowly points upward at the berry. Momo mistakenly looks left instead. Tiki follows that wrong gaze for a beat, then looks back at Momo with one raised eyebrow and points upward more emphatically. No speech or talking-mouth movement.',
  'Hold both faces and Momo\'s tuft in the same frame.', 'The misunderstanding is clear from their eye lines.'),
 (7, 'A careful bow', ['Momo'],
  'Medium three-quarter view of Momo with the blueberry balanced on the top tuft. Clear grass is visible in front and at screen right. Momo looks cautiously downward, paws close to the belly, body ready to bend forward only slightly.',
  'Momo makes one slow shallow bow to look down. The blueberry loses its balance and rolls off the tuft toward the grass at screen right. Momo pauses, follows it with wide eyes and holds both paws out too late. Use a small fall and one soft settling bounce.',
  'Gentle tilt down to keep the berry\'s destination visible.', 'The berry is back on the ground and moving toward the slope.'),
 (5, 'Down the garden slope', [],
  'An insert at grass level: the one blueberry at the upper-left of a short gentle grassy slope, its star-shaped crown visible. The path and broad-leaf bush lie toward the lower-right background. No characters or other berries in frame.',
  'The blueberry rolls slowly down the gentle slope toward screen right, brushing a small grass blade aside. Let the foreground flowers pass softly out of focus. Keep it one solid berry, not a swarm or a magical object.',
  'A short smooth rightward tracking move at berry height.', 'The berry approaches the broad-leaf bush.'),
 (6, 'Pip goes sledding', ['Pip'],
  'Low wide view of Pip lying belly-down on a large green leaf on the gentle slope, paws stretched forward. The blueberry is on the grass a short distance ahead to screen right. Pip looks determined; the leaf lies flat like a little sled. No other creatures.',
  'The leaf slides gently a short distance down the slope with Pip aboard. Pip reaches forward with both paws but stops just short of the blueberry. Pip lifts the head and stares at the tiny remaining gap in exaggerated frustration. No fast tumble or collision.',
  'Low side-on framing with the leaf, Pip and berry always visible.', 'Pip has almost caught it, but still cannot reach.'),
 (6, 'Tiki lays a route', ['Tiki'],
  'Medium overhead-leaning three-quarter view of Tiki on flat grass, with a broad green leaf laid as a little ramp toward the empty shallow wicker basket at screen right. The blueberry rests at the ramp\'s left end. Tiki carefully aligns the leaf edge with one paw.',
  'Tiki precisely centres the leaf ramp and gives the blueberry one careful nudge. The leaf bends sideways and the berry rolls gently off its near side instead of into the basket. Tiki looks at the basket, then the misplaced berry, and lets the shoulders sag.',
  'Static composition that clearly shows leaf, basket opening and alternate berry path.', 'The tidy plan has failed in an untidy way.'),
 (7, 'Momo is the brake', ['Momo'],
  'Medium low front three-quarter view of Momo sitting on grass as a soft barrier, the blueberry resting against the lower left side of the yellow belly. The empty basket lies further right. Momo looks pleased, both paws slightly raised as if announcing success without words.',
  'Momo proudly holds still and the berry stays stopped. After a clear satisfied pause, Momo rises just a little to peek down. The berry rolls gently past the vacated spot to screen right. Momo immediately sinks back down, realizes the mistake and looks sheepish.',
  'Hold the low camera steady so the audience sees the gap appear.', 'Momo accidentally releases the very thing being guarded.'),
 (6, 'A better idea', ['Pip','Tiki'],
  'Medium two-shot on level grass: Pip at left and Tiki at right, both looking tired and slightly slumped. The blueberry sits safely between them in the foreground. Tiki raises one open mitten paw in a calm stop gesture; Pip is poised to rush again.',
  'Tiki\'s stop gesture makes Pip pause. They both look at the berry, then at each other. Tiki offers one paw; Pip considers for a beat, then gives a small nod and a gentle paw tap. Their expressions turn from frustration to teamwork.',
  'A slow small push in, giving the reaction a quiet beat.', 'They agree to cooperate.'),
 (5, 'Three sides of a plan', ['Pip','Momo','Tiki'],
  'High three-quarter wide view: Pip left, Momo centre-back and Tiki right form a loose semicircle around the blueberry on level grass. A single broad green leaf lies open just in front of the berry, ready to become a carrying sling. The three faces look inward; distinct silhouettes and colours.',
  'The three creatures each take one careful small step inward and lower their paws toward the leaf, following Tiki\'s measured nod. Momo stays behind the berry as a gentle backstop while Pip and Tiki take the leaf\'s opposite sides.',
  'Static high three-quarter view, not an extreme top-down shot.', 'Each friend now has a simple useful role.'),
 (7, 'The leaf hammock', ['Pip','Tiki'],
  'Medium frontal view: Pip at left and Tiki at right each hold one end of the same broad green leaf. The blueberry rests at the leaf\'s centre just above the grass. Both creatures have feet planted and eyes on the berry, focused rather than speaking.',
  'Pip and Tiki slowly lift their leaf ends together into a shallow hammock. The berry settles securely in the centre. They stop, glance at each other and smile with relieved eyes, carefully keeping the leaf level.',
  'A very small slow upward camera move with the lift.', 'The berry is finally caught and supported.'),
 (6, 'Special delivery', ['Pip','Tiki'],
  'Medium-wide at the picnic stump again. Pip left and Tiki right hold the leaf hammock level over the table centre, with the blueberry safely in it. The three leaf plates are arranged around the centre; the shallow empty wicker basket sits at the rear.',
  'Pip and Tiki lower the broad leaf onto the stump together, then gently release their ends. The blueberry remains in the centre. They take one small step back, lift their chins and admire their successful delivery with matching proud poses.',
  'Hold a stable frontal view to make the landing on the table clear.', 'The picnic has been restored through teamwork.'),
 (6, 'There were plenty', ['Pip','Momo','Tiki'],
  'Wide garden view: the picnic table with the rescued blueberry sits at left. Pip and Tiki stand proudly beside it facing the table. Momo stands at right next to a broad-leaf bush, lifting one large leaf; a small cluster of several matching blueberries is visible underneath. This is the final reveal, not a new species of fruit.',
  'Momo notices the cluster and makes one delighted silent open-paw presentation toward it. Pip and Tiki turn from their hard-won single berry toward the many berries, pause in disbelief, then their shoulders relax and faces brighten. Let the irony read before the shared joy.',
  'A modest slow pan right from the picnic toward Momo\'s discovery.', 'All three realize there is enough for everyone.'),
 (7, 'The tiniest picnic guest', ['Pip'],
  'Close view of the rescued blueberry on its broad green leaf at the picnic table. Pip\'s coral face and paws are visible behind the table, protective but relaxed. A tiny yellow butterfly is hovering just above the leaf rim. The sunny garden and a berry bush are softly blurred behind; no other creature in this close-up.',
  'The butterfly lands lightly on the leaf rim and the blueberry gives one tiny wobble. Pip instantly cups both paws protectively beside it and gives the butterfly an exaggerated suspicious look. After a beat, Pip sees the harmless visitor, relaxes the paws and gives a soft shoulder bounce of silent amusement. End with the berry safe and the butterfly resting.',
  'Static close-up; finish on a clean held expression without a fade.', 'Friendly comic button: the smallest guest causes the final biggest reaction.'),
]


def build():
    (OUT / 'frames').mkdir(parents=True, exist_ok=True)
    (OUT / 'clips').mkdir(exist_ok=True)
    (OUT / 'prompts').mkdir(exist_ok=True)
    shots = []
    at = 0
    for number, row in enumerate(ROWS, 1):
        duration, title, cast, opening, action, camera, exit_state = row
        identity = '; '.join(CAST[name] for name in cast) or 'No characters in this insert'
        image_prompt = (STYLE + WORLD + BERRY + 'Create one finished landscape 16:9 animation opening frame, not a sheet or collage. '
                        'Use the cast image only as exact character identity/style reference and the garden reference only for the established visual world. '
                        f'Only these characters are on camera: {identity}. ' + opening + ' '
                        'The opening is a held anticipation pose before the described movement, with clear staging for that movement. '
                        'All characters retain their reference colours, silhouettes, tufts and eye designs. No clothing, extra characters, text, letters, logos or watermarks. '
                        'Do not include the reference pinwheel. The main berry is dusty indigo, never coral, green or yellow. No motion blur.')
        video_prompt = (STYLE + f'Preserve the exact opening image and the following on-camera identities: {identity}. '
                        + BERRY + f'During this {duration}-second single shot: ' + action + ' Camera: ' + camera + ' '
                        'Use readable pauses, gentle springy weight shifts, grounded feet, squash-and-stretch confined to the soft bodies, '
                        'and modest natural secondary motion in fur and garden leaves. One dominant action; no internal scene change or camera cut. '
                        + SILENT + 'No generated soundtrack is needed; the final episode receives an instrumental score and non-vocal effects in post. '
                        'Keep the image clean and stable; no body duplication, prop duplication, added fingers or fast spinning.')
        shot = dict(id=f'S{number:02d}', number=number, title=title, cast=cast, duration=duration,
                    start=at, end=at + duration, edit_frames=duration * FPS, source_trim_start_frame=0,
                    transition='hard_cut', opening=opening, action=action, camera=camera, exit=exit_state,
                    image_prompt=image_prompt, video_prompt=video_prompt,
                    seed=1024100 + number, frame=f'frames/S{number:02d}.png', clip=f'clips/S{number:02d}.mp4',
                    audio_intent='no_audio; original non-vocal score and designed effects in final master')
        shots.append(shot)
        (OUT / 'prompts' / f'S{number:02d}-image.txt').write_text(image_prompt, encoding='utf-8')
        (OUT / 'prompts' / f'S{number:02d}-video.txt').write_text(video_prompt, encoding='utf-8')
        at += duration
    assert at == 120 and sum(s['edit_frames'] for s in shots) == 2880
    spec = dict(title='Tumble Puffs — The Runaway Berry', episode='01', fps=FPS, total_seconds=at,
                total_frames=2880, continuity='independent I2V shots joined exclusively by hard cuts',
                output_policy='exactly 120 seconds; 1600x896 landscape; no speech or human vocal audio',
                settings=dict(engine='ltx', mode='opening', steps='8', ltx_quality='balanced', aspect_ratio='16:9',
                              ltx_sharp_decode='true', ltx_calm_sampler='false', no_audio='true'),
                references=['state/tumble_puffs/cast-imagegen-v1.png', 'state/tumble_puffs/opening-02-pinwheel-imagegen-v1.png'],
                review='User is visual reviewer; basic media proof only; no AGY, no subagents, no approval gates',
                shots=shots)
    (OUT / 'manifest.json').write_text(json.dumps(spec, indent=2), encoding='utf-8')
    lines = ['# Tumble Puffs — Episode 01: The Runaway Berry', '',
             'A complete 120-second, 20-shot original pantomime episode, using the established Pip, Momo and Tiki designs.', '',
             '## Story', '',
             'Three friends prepare a picnic around one oversized blueberry. Each solitary solution sends it further away. '
             'Pip acts too quickly, Momo is gently overconfident, and Tiki tries to impose order. A shared leaf hammock finally '
             'catches the berry. They return it to the picnic, only to discover an entire berry patch nearby. A tiny butterfly '
             'gets the final reaction.', '',
             '## Production contract', '',
             '- LTX 2.5 opening-image clips through the main bridge on 8787; one ComfyUI on 8190.',
             '- Built-in ImageGen for all opening stills, anchored to the selected cast/garden.',
             '- Balanced landscape, 8 steps, sharp decode, calm sampler off. Existing runtime stays intact.',
             '- Independent shots with hard cuts only. No last-frame handoff or simulated continuous take.',
             '- Pure pantomime. Every source video is rendered without an audio stream. Final audio consists only of an original instrumental score and synthesized non-vocal effects.',
             '- No speech, gibberish, lip-sync, singing, narration, subtitles, text or title cards.',
             '- Trim each source by decoded frame count to its exact editorial duration. Final master: 2880 frames at 24 fps = exactly 120 seconds.',
             '- User supplies artistic feedback. No AGY, delegated review, strict inspection gates or automatic creative regeneration loop.', '',
             '## Storyboard', '', '| Shot | Timeline | Length | Framing / cast | Action and comic change |', '| --- | --- | --- | --- | --- |']
    for s in shots:
        tc = lambda t: f'{t//60:02d}:{t%60:02d}'
        lines.append(f"| {s['id']} · {s['title']} | {tc(s['start'])}–{tc(s['end'])} | {s['duration']} s | {', '.join(s['cast']) or 'Berry insert'}; {s['camera']} | {s['action']} |")
    lines += ['', '## Music and edit', '',
              'An original 120 BPM cartoon score uses mallet/plucked motifs for Pip, a warm round low-register motif for Momo, '
              'and precise short woodwind-like notes for Tiki. The arrangement develops through curiosity (0–28), bounce/misunderstanding '
              '(28–59), a light chase (59–89), teamwork (89–107), and reveal/cadence (107–120). Reaction beats receive brief musical space. '
              'Soft woodblocks, boings, leaf swishes and a tiny final flutter are synthesized; no voice samples are used. Music continues '
              'across picture cuts so the sequence feels like one episode.', '',
              '## Files / resume', '',
              '- Creative source: `episode_spec.py` beside this plan.',
              '- Frozen execution manifest and exact prompts: `state/tumble_puffs_ep01/manifest.json` and `prompts/`.',
              '- ImageGen opening frames: `state/tumble_puffs_ep01/frames/`.',
              '- Durable submission journal: `state/tumble_puffs_ep01/execution.json`.',
              '- Renderer/assembler: `episode_runner.py`; music: `episode_score.py`.',
              '- No POST is repeated after an uncertain submission. Resume by polling the journaled job.',
              '- `STOPPED.json` prevents any new submissions; it never cancels an already-running GPU job.',
              '- Final master and proof: `state/tumble_puffs_ep01/The_Runaway_Berry_120s.mp4` and matching `_proof.json`.',
              '- Publish the completed master through the existing main bridge Video Vault API; preserve all source clips.',
              '- If sub-agents are later explicitly requested, the user preference is GPT-6.1 Sol / medium. None are required here.', '']
    Path(__file__).with_name('EPISODE_PLAN.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'shots':len(shots), 'seconds':at, 'frames':2880, 'manifest':str(OUT/'manifest.json')}))


if __name__ == '__main__':
    build()
