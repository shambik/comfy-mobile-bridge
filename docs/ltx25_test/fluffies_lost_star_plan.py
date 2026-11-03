"""Fluffies — The Little Lost Star: a story-driven episode with a real arc.

Lessons from the first two episodes: the berry pilot repeated one prop in every
scene, and The Wobbly Surprise had the cast laughing in nearly every shot. This
episode follows one problem through setup, failed attempts, an emotional low,
an idea, teamwork and a payoff. Each shot carries its own emotion; laughter is
reserved for two earned moments. Every scene is kept whole (no trims).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state/fluffies_ep03_lost_star'
CAST = {
 'Bobo': 'Bobo: blue rounded bean-shaped Fluffie, sapphire/sky-blue fur with icy-blue cheeks and belly, big teal eyes, one swept fluffy crown tuft; exactly as in the selected opener',
 'Lulu': 'Lulu: petite round pink Fluffie, rose/magenta fur with blush face and belly, big teal eyes with lashes, split soft crown tuft; exactly as in the selected opener',
 'Zuzu': 'Zuzu: tall soft pear-shaped purple Fluffie, violet/lavender fur, hazel eyes, tall spiky violet crown tufts',
 'Pebble': 'Pebble: squat rounded-square charcoal/soft-black Fluffie, graphite sides and a silver-grey face and belly, amber eyes, broad shaggy swept crest',
 'Numi': 'Numi: small upright pearl-white oval Fluffie, ivory highlights and silver shadows, ice-blue eyes, one forward-curling white crown tuft',
 'Twinkle': ('Twinkle: a tiny living star the size of a plum, a soft plump five-pointed star with rounded puffy points, '
             'warm golden-white inner glow and a gentle halo, two tiny dark dot eyes and a small mouth; uses two points like little arms'),
}
STYLE = ('Original premium 3D animated family film in the spirit of a gentle nonverbal preschool comedy, tactile groomed fur with soft '
         'secondary motion, appealing expressive eyes, tiny mitten paws and broad soft feet, springy grounded body weight, '
         'crafted storybook world, cinematic lighting, layered depth, foreground framing, realistic contact shadows, clear silhouettes. ')
LIGHT = {
 'sunset': 'Golden-hour sunset: a low warm sun near the horizon, peach and rose-pink sky, long soft shadows, warm rim light on the fur. ',
 'twilight': ('Blue-hour twilight: a luminous periwinkle and lilac sky with the first few stars, a thin pink glow on the horizon, '
              'warm windows glowing in the village below; characters clearly lit by soft cool skylight with warm bounce. '),
 'night': ('Luminous storybook night: deep indigo sky full of bright stars and a large soft full moon; silvery moonlight plus warm golden '
           'glow keep every fur colour rich, bright and readable. Never murky or underexposed. '),
}
SETS = {
 'hill': ('Round grassy hilltop meadow above a storybook village: soft clover grass with white daisies, one tall old oak tree with a broad '
          'canopy at screen left, a dense round daisy bush near its trunk, a cream-and-rose striped picnic blanket on the grass, '
          'village rooftops with tiny lit windows far below, lavender hills on the horizon. '),
 'lane': ('Cobbled storybook village lane: rounded grey cobbles, pastel plaster cottages with warm glowing windows, iron street lamps with '
          'golden light, flower boxes; at the end the round turquoise-green door of Zuzu\'s little round cottage workshop, brass knocker '
          'and a glowing porch lantern. No readable signs or lettering. '),
 'sky': 'High in the night sky among bright stars and soft luminous wisps of cloud, the moon to one side, the tiny hill and village far below. ',
}
PROPS = {
 'seesaw': 'A simple seesaw: one long pale wooden plank balanced on a short round log, with a small wooden cup fixed at one end. A big round golden haystack sits at the edge of the hilltop. ',
 'balloons': 'Five pastel balloons (pink, blue, lilac, mint, yellow) whose strings are tied to one tiny wicker basket. ',
 'lantern': ('One large cream paper sky lantern, taller than the Fluffies, with a bamboo ring at its open bottom and one big painted yellow star on its side; '
             'a tiny wicker basket hangs below it. '),
 'handlantern': 'Zuzu\'s small handheld round paper lantern glows warm orange. ',
}

# title, seconds, cast, set, light, props, emotion, opening instant, action, camera, sound
ROWS = [
 # ACT 1 — wonder and discovery
 ('Up the hill', 7, ['Bobo', 'Lulu'], 'hill', 'sunset', [], 'Cheerful anticipation of a quiet evening.',
  'Bobo and Lulu are mid-stride walking up the last grassy slope toward screen right. Lulu hugs a rolled striped blanket; Bobo, one foot lifted, looks up at the glowing sky. Full bodies, room to travel.',
  'They walk up the slope with clear alternating steps. Lulu nudges Bobo and points up at the pink sky. Bobo hops up the final step onto the flat hilltop and spreads both paws wide, taking in the view.',
  'Low wide tracking shot moving alongside them left to right; grass blades sweep past in the foreground and the village drops away below.',
  'Soft footsteps on grass, evening birdsong, early crickets, Lulu\'s bright pleased hum and Bobo\'s eager little chirp. No laughing.'),
 ('The first star', 7, ['Bobo', 'Lulu'], 'hill', 'twilight', [], 'Calm, peaceful wonder.',
  'High angle looking down: Lulu is mid-flick spreading the striped blanket in the air; Bobo is already dropping backwards onto it, arms out.',
  'The blanket settles and Bobo flops onto it with a soft bounce; Lulu lies down beside Bobo. They settle on their backs, side by side. Bobo slowly lifts a paw to point at one twinkling star; Lulu follows the point and smiles softly.',
  'Top-down high camera slowly rising and rotating very slightly, keeping both full bodies on the blanket.',
  'A cloth flap, a soft fluffy flump, crickets, a long contented sigh from Lulu and Bobo\'s quiet wondering hum. No laughing.'),
 ('A shooting star', 7, ['Bobo', 'Lulu'], 'hill', 'twilight', [], 'Amazement turning to alarm.',
  'Low angle from behind Bobo and Lulu lying on the blanket, the big sky filling the frame. A bright golden shooting star already streaks across the upper sky with a glittering tail.',
  'The shooting star arcs across the sky, then curves downward and grows larger, heading straight toward the hill. Bobo and Lulu sit bolt upright together, eyes wide and mouths open, pointing at it.',
  'Low static wide from behind and slightly beside them, then a slight push in as they sit up.',
  'A rising sparkling magical shimmer and whoosh, two sharp surprised gasps, crickets falling silent. No laughing.'),
 ('Incoming!', 7, ['Bobo', 'Lulu'], 'hill', 'twilight', [], 'Fright, then nervous curiosity.',
  'Bobo and Lulu crouch together behind the striped blanket held up like a shield, eyes peeking over the top edge. A glowing golden light streaks down toward the daisy bush beside the oak.',
  'The glowing streak lands in the daisy bush with a soft sparkling thump and a puff of glittering sparks. Bobo and Lulu duck down, trembling, then slowly lower the blanket and peek over it at the softly pulsing glow in the bush.',
  'Medium-wide side view at grass level, the bush at screen right and the pair at left, the oak framing the top of the shot.',
  'A descending whistle, a soft sparkling thump, tinkling falling sparks, a nervous whimper from Lulu and Bobo\'s held breath. No laughing.'),
 ('Something in the bush', 7, ['Bobo', 'Lulu'], 'hill', 'twilight', [], 'Tense, careful curiosity.',
  'Bobo tiptoes toward the glowing daisy bush mid-step with arms out for balance; Lulu follows right behind holding Bobo\'s back tuft nervously. Golden light glows through the leaves.',
  'They creep closer with exaggerated careful tiptoe steps. Bobo slowly reaches out and gently parts the leaves with both paws; warm golden light spills across both faces and their eyes go wide.',
  'Low over-the-shoulder push in from behind the pair toward the glowing bush.',
  'Soft tiptoe rustles, crickets, a rising gentle shimmer, nervous breathing. No laughing.'),
 ('Twinkle', 7, ['Bobo', 'Lulu', 'Twinkle'], 'hill', 'twilight', [], 'Shy, tender first meeting.',
  'Close shot inside the parted daisy leaves: tiny glowing Twinkle is curled up shyly on the grass, peeking up; Bobo and Lulu lean in from the top edge of the frame, faces lit gold.',
  'Twinkle trembles and hides its face behind two soft points. Lulu slowly lowers one open paw beside it and waits. Twinkle peeks out, then hops timidly onto Lulu\'s paw, and its glow grows warmer and brighter.',
  'Intimate close framing at Twinkle\'s level, slight gentle push in, shallow depth of field.',
  'A tiny chime-like nervous whimper, a soft bell-like hop, Lulu\'s gentle cooing hum, crickets. No laughing.'),
 ('Where do you live?', 8, ['Bobo', 'Lulu', 'Twinkle'], 'hill', 'night', [], 'Concern; the problem becomes clear.',
  'Lulu holds glowing Twinkle at chest height while Bobo leans in close; Twinkle is already stretching one point upward toward the sky.',
  'Twinkle points up at a pattern of stars with one dark empty gap. Bobo and Lulu look up at the gap. Twinkle\'s glow flickers dimmer and it droops sadly in Lulu\'s paw. Bobo and Lulu look at each other with worried faces, then Bobo gives a small determined nod.',
  'Low angle beside the characters looking up past them to the starry sky, then a gentle tilt down to their faces.',
  'A small sad descending chime, a tiny sniffle, Lulu\'s soft concerned hum, a quiet breath of resolve from Bobo. No laughing.'),
 # ACT 2 — attempts
 ('One, two, up!', 7, ['Bobo', 'Lulu', 'Twinkle'], 'hill', 'night', [], 'Hopeful effort, then mild puzzlement.',
  'Bobo is crouched mid-swing with Twinkle cupped in both paws, already swinging upward to toss; Lulu stands beside with clasped paws, watching.',
  'Bobo tosses Twinkle gently upward. Twinkle floats up a little, hovers, then drifts slowly back down like a feather into Bobo\'s paws. Bobo blinks, tries once more with a bigger hop, and Twinkle floats straight back down again. Twinkle wiggles side to side: it cannot fly that high.',
  'Medium-wide low angle with plenty of headroom so the toss and float are clear.',
  'An effort huff, a soft whoosh, a tinkling float sound, a puzzled hum from Bobo and a tiny sad chime. No laughing.'),
 ('We need help', 8, ['Bobo', 'Lulu', 'Zuzu', 'Twinkle'], 'lane', 'night', ['handlantern'], 'Urgency, then astonishment.',
  'Lulu and Bobo are running down the cobbled lane toward the round turquoise-green door, Bobo carrying glowing Twinkle in cupped paws, both mid-stride.',
  'They hurry up to the round door. Lulu knocks three times. The door swings open and tall purple Zuzu appears holding a small glowing paper lantern; Zuzu leans down to see Twinkle and both eyebrows shoot up in astonishment.',
  'Tracking behind and beside the running pair, then settling into a three-quarter view of the doorway.',
  'Quick soft footsteps on cobbles, three wooden knocks, a door creak, Zuzu\'s astonished airy hum. No laughing, no words.'),
 ('Zuzu has a plan', 7, ['Zuzu', 'Pebble', 'Bobo'], 'hill', 'night', ['seesaw', 'handlantern'], 'Busy, confident problem-solving.',
  'On the hilltop, Zuzu is mid-stride dragging one end of a long pale wooden plank; charcoal Pebble behind is mid-push rolling a short log; Bobo carries Twinkle beside them. Zuzu\'s small lantern sits glowing on the grass.',
  'Pebble rolls the log into place and plants it. Zuzu swings the plank across the log to form a seesaw, taps it twice to test it, then dusts off both paws and presents it proudly. Bobo looks at it hopefully.',
  'Wide eye-level lateral tracking that comes to rest on the finished seesaw.',
  'Wood scraping on grass, a heavy log thump, a hollow plank clack, Pebble\'s low effort grunt and Zuzu\'s satisfied hum. No laughing.'),
 ('The launch', 7, ['Bobo', 'Pebble', 'Zuzu', 'Twinkle'], 'hill', 'night', ['seesaw'], 'Big physical comedy surprise.',
  'Twinkle sits in the little wooden cup on the low end of the seesaw; Bobo stands on that same low end bending over to check it; Pebble is already in mid-air jumping toward the high end; Zuzu watches from the side. The haystack is behind Bobo.',
  'Pebble lands on the high end with a heavy thump. Instead of Twinkle, Bobo is catapulted up into the air, arms and feet flailing, and lands softly face-first in the big golden haystack. Twinkle tumbles gently out of the cup onto the grass. Zuzu and Pebble cover their mouths in shock.',
  'Wide static side view showing the whole seesaw, the haystack and the arc of Bobo\'s flight.',
  'A heavy wooden thump, a springy boing, Bobo\'s rising startled squeal, a soft straw whumph, Zuzu and Pebble\'s shocked gasps. No words.'),
 ('Hay there', 6, ['Bobo', 'Lulu', 'Zuzu'], 'hill', 'night', ['seesaw'], 'Dizzy and sheepish; a little embarrassed.',
  'Bobo\'s head and arms are already popping out of the golden haystack, fur full of straw; Lulu and Zuzu are rushing in from the left mid-step.',
  'Bobo shakes like a wet dog, sending straw flying, wobbles in a dizzy little circle, then gives a sheepish embarrassed smile. Lulu picks a piece of straw off Bobo\'s crown tuft and pats Bobo\'s shoulder. Zuzu scratches her head, looking back at the seesaw.',
  'Medium close two-to-three shot at haystack height.',
  'Rustling straw, a dizzy warble from Bobo, Lulu\'s relieved sigh and one small sympathetic chuckle from Zuzu.'),
 ('Numi brings balloons', 6, ['Numi', 'Lulu', 'Pebble', 'Twinkle'], 'hill', 'night', ['balloons'], 'Fresh hope arriving.',
  'Small white Numi is skipping up the moonlit slope holding the strings of five pastel balloons; Lulu and Pebble, at the right edge, are turning toward her. Pebble holds Twinkle.',
  'Numi skips up to them, the balloons bobbing overhead. Lulu\'s face lights up with hope; Numi proudly holds out the bunch of balloon strings toward Pebble and Twinkle. Twinkle\'s glow brightens.',
  'Low wide angle from up the slope looking down at Numi arriving, then a slight pan to include Lulu and Pebble.',
  'Light skipping footsteps, soft rubbery balloon squeaks, Numi\'s delicate excited coo, Lulu\'s hopeful gasp. No laughing.'),
 ('Up, up, up', 8, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi', 'Twinkle'], 'hill', 'night', ['balloons'], 'Held-breath hope.',
  'Twinkle sits in the tiny wicker basket under the five pastel balloons, which has just left the grass; the five Fluffies stand around below with their paws still raised from letting go.',
  'The balloon basket rises slowly and steadily toward the stars. The five friends tilt their heads back to watch, clasping paws hopefully; Lulu takes Bobo\'s paw. Twinkle peers over the basket edge and its glow brightens.',
  'Camera starts at the friends and slowly cranes up following the rising basket, the oak canopy at the side of the frame.',
  'A soft rising airy sound, crickets, gentle balloon creaks, hopeful held breaths and a faint tinkling chime. No laughing.'),
 ('Pop!', 8, ['Pebble', 'Bobo', 'Lulu', 'Twinkle'], 'hill', 'night', ['balloons'], 'Sudden danger, then relief.',
  'The balloon basket drifts up against the upper twigs of the oak; one pink balloon is already touching a sharp twig; Pebble, Bobo and Lulu watch from below.',
  'The pink balloon pops, then the blue one. The basket tips and Twinkle drops. Pebble dashes forward and dives into a belly slide across the grass, catching Twinkle gently in both paws. Bobo and Lulu rush over and kneel beside Pebble.',
  'Starts high on the oak branches and tilts down fast to follow the fall, ending low and wide on Pebble\'s catch.',
  'Two sharp balloon pops, a chorus of gasps, a falling whoosh, a soft grassy slide and a long relieved exhale. No laughing.'),
 ('Fading', 9, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi', 'Twinkle'], 'hill', 'night', [], 'Quiet sadness: the emotional low point.',
  'The five friends sit huddled on the striped blanket under the moon; Pebble cups Twinkle, whose glow is dim and flickering. Lulu is mid-movement raising a paw to wipe her eye; Bobo is already beginning to stand.',
  'Twinkle\'s glow flickers weaker. Lulu wipes away a tear. Numi leans her head on Zuzu\'s shoulder. Bobo stands up slowly and walks a few heavy steps away to the edge of the hill, staring up at the empty gap among the stars, shoulders drooping.',
  'Slow gentle push in from a moonlit wide, cool silver light with Twinkle\'s faint warm glow at the centre.',
  'Quiet crickets, a faint fading chime, a soft sniffle and a long sad sigh. Silence between sounds. No laughing, no giggles.'),
 # ACT 3 — idea, teamwork and payoff
 ('Bobo gets an idea', 8, ['Bobo'], 'hill', 'night', ['handlantern'], 'A spark of inspiration and excitement.',
  'At the edge of the hill, Bobo is looking down at Zuzu\'s small glowing paper lantern on the grass; a white dandelion seed fluff is already floating just above its warm glow.',
  'The warm air above the lantern lifts the dandelion fluff up and up. Bobo\'s eyes follow it into the sky, then widen. Bobo gasps, spins round toward the friends offscreen and waves both arms excitedly, bouncing on the spot.',
  'Close low angle on the lantern and fluff, tilting up with the fluff to reveal Bobo\'s face, then a small pull back as Bobo turns.',
  'A soft lantern flutter, a light airy whoosh, Bobo\'s sudden bright gasp and two excited squeaks. No laughing.'),
 ('Everyone helps', 10, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi'], 'hill', 'night', ['lantern', 'handlantern'], 'Focused, joyful teamwork.',
  'On the moonlit blanket the five friends are already busy around a tall bamboo lantern frame: Zuzu bends the bamboo ring, Pebble holds the frame upright, Numi and Lulu smooth a big sheet of cream paper onto it, Bobo is mid-brushstroke painting a big yellow star.',
  'Everyone works together: Zuzu fixes the ring, Lulu and Numi press the last paper edge down, Bobo finishes the painted star with a final flourish. They step back and look up at the finished tall paper sky lantern, then at each other with determined smiles.',
  'Wide eye-level shot slowly circling a little around the group, the finished lantern rising into frame.',
  'Paper rustles, brush strokes, bamboo creaks, focused humming and a satisfied group exhale. No laughing.'),
 ('Ready', 7, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi', 'Twinkle'], 'hill', 'night', ['lantern', 'handlantern'], 'Nervous hope.',
  'The tall paper sky lantern stands on the hilltop. Zuzu is already reaching up with the small handheld lantern to light the burner inside; dim Twinkle sits in the tiny basket below; the others hold the bamboo rim all around.',
  'The burner catches and the big lantern glows warm amber from within, slowly filling and lifting until it tugs gently upward against their paws. The friends exchange hopeful glances; Twinkle looks up at the sky and its glow brightens a little.',
  'Medium-wide low angle looking up at the glowing lantern with the friends framing the bottom of the shot.',
  'A soft whump of a small flame, paper crinkling as it fills, gentle airy breathing and a hopeful hum. No laughing.'),
 ('Let go', 7, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi', 'Twinkle'], 'hill', 'night', ['lantern'], 'Bittersweet farewell.',
  'Wide on the hilltop: the five friends stand in a circle with their paws just opening from the glowing sky lantern rim, which has started to lift; Twinkle waves from the basket.',
  'The lantern rises slowly into the starry sky. The friends step back and wave. Twinkle waves back with one point. Lulu holds Bobo\'s paw as they watch it climb higher and higher.',
  'Wide shot that slowly tilts up to follow the rising lantern, keeping the friends small at the bottom of the frame.',
  'A gentle rising airy whoosh, crickets, a soft collective breath of wonder. No laughing.'),
 ('Home', 6, ['Twinkle'], 'sky', 'night', ['lantern'], 'Magical arrival.',
  'High in the sky the glowing sky lantern floats beside a pattern of stars with one dark empty gap; Twinkle is already climbing out of the basket toward the gap.',
  'Twinkle hops out into the gap and blazes into a big brilliant star, sending out gentle shimmering rings of light. The empty lantern drifts slowly away across the sky.',
  'Close-to-medium floating camera beside the lantern, a slow push toward Twinkle as it ignites.',
  'A rising magical chime and a shimmering sparkle burst. No voices.'),
 ('Thank you', 8, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi'], 'hill', 'night', [], 'Wonder, then the earned joy.',
  'The five friends stand close together on the hilltop, faces turned up and lit by a new bright starlight; tiny golden sparkles are just beginning to fall around them.',
  'A gentle shower of tiny golden sparkles drifts down around them. They gasp in wonder and reach out paws to catch the sparkles. Lulu throws her arms around Bobo and everyone bundles into a warm group hug, bouncing with happy giggles.',
  'Medium-wide slightly low angle, slow push in toward the group hug.',
  'A twinkling sparkle shower, soft wondering gasps, then warm happy giggles from the group. No words.'),
 ('Under the stars', 10, ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi'], 'hill', 'night', [], 'Peaceful contentment; ending.',
  'High angle: the five friends are settling down side by side on their backs on the striped blanket, Numi still wriggling into place, all looking up at the starry sky.',
  'They settle in and get comfortable. Bobo points up at the brightest star; it twinkles and sends a tiny wink of light back. The friends smile softly. The camera slowly rises away above them into the night sky until the brightest star fills the top of the frame.',
  'Top-down crane slowly rising and pulling away from the blanket into the starry sky.',
  'Crickets, contented sighs, a single soft twinkling chime, peaceful calm. No laughing.'),
]


def build():
    for folder in ['frames', 'clips', 'prompts', 'refs']:
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    shots, at = [], 10.0
    for number, row in enumerate(ROWS, 1):
        title, seconds, cast, location, light, props, emotion, opening, action, camera, sound = row
        identities = '; '.join(CAST[c] for c in cast)
        prop = ''.join(PROPS[p] for p in props)
        world = STYLE + LIGHT[light] + SETS[location] + prop
        image_prompt = (world + 'Make ONE finished cinematic 16:9 landscape film still caught DURING movement, never a lineup or posed portrait. '
                        'Visible characters ONLY: ' + identities + '. Exact opening instant: ' + opening + ' Mood: ' + emotion + ' '
                        'Off-camera eyelines, planted weight, separated readable limbs. No lettering, subtitles, logo, watermark, '
                        'collage, extra or duplicate characters. Camera: ' + camera)
        video_prompt = (world + 'Preserve the exact opening-frame characters: ' + identities + '. '
                        f'A {seconds}-second single continuous shot; the movement is already underway in the opening frame. '
                        'Continue it IMMEDIATELY with visibly changing body positions. No initial freeze or posed hold. '
                        'Emotion: ' + emotion + ' Action: ' + action + ' Camera: ' + camera + ' '
                        'Real steps, weight transfer, responsive paws, expressive faces that match the emotion. No slow motion. '
                        'SOUND: ' + sound + ' Vocal reactions are short nonverbal sounds that suit the emotion. '
                        'No speech, words, gibberish, narration, lyrics or singing. No generated music; music is added in the edit. '
                        'No internal cuts, new characters, disappearing cast, colour swaps or changing props.')
        shot = dict(id=f'S{number:02d}', number=number, title=title, cast=cast, location=location, light=light, props=props,
                    emotion=emotion, duration=seconds, edit_seconds=seconds, edit_frames=seconds * 24, trim_start_frame=0,
                    start=at, end=at + seconds, seed=1030000 + number, frame=f'frames/S{number:02d}.png',
                    clip=f'clips/S{number:02d}.mp4', image_prompt=image_prompt, video_prompt=video_prompt,
                    opening=opening, action=action, camera=camera, sound=sound, audio_intent='non_lipsync', transition='hard cut')
        assert 6 <= seconds <= 10
        shots.append(shot)
        for kind in ['image', 'video']:
            (OUT / 'prompts' / f'{shot["id"]}-{kind}.txt').write_text(shot[f'{kind}_prompt'], encoding='utf-8')
        at += seconds
    story = int(at - 10)
    spec = dict(schema='execution_manifest.v1', title='Fluffies — The Little Lost Star', fps=24,
                total_seconds=story, total_frames=story * 24, full_episode_seconds=story + 10, full_episode_frames=(story + 10) * 24,
                intro_seconds=10, intro_frames=240, intro='state/fluffies_ep03_lost_star/refs/1002475080.mp4',
                intro_vault_id='abaee350db914237bbd563fd49afde89',
                intro_sha256='3cf3973f41294e8a301b442817a3dff72b438c21f8b21d6cf675651d9583e7b5',
                output_width=1920, output_height=1080, score_file='lost_star_original_score.wav',
                full_scenes_stem='Fluffies_The_Little_Lost_Star',
                settings=dict(engine='ltx', mode='opening', steps='8', ltx_quality='balanced', aspect_ratio='16:9',
                              ltx_sharp_decode='true', ltx_calm_sampler='false', no_audio='false'),
                shots=shots, master_filename='Fluffies_The_Little_Lost_Star.mp4',
                audio_policy='Selected opener in full with its own sound; every story scene whole with native nonverbal sound; original instrumental score ducked underneath.',
                review='User visual/listening review')
    (OUT / 'manifest.json').write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding='utf-8')
    def tc(t):
        return f'{int(t)//60:02d}:{int(t)%60:02d}'
    lines = [
        '# Fluffies — The Little Lost Star', '',
        '## Story and creative direction', '',
        'Built in the spirit of *Sunny Bunnies*: one clear problem drives the whole episode from setup to attempts, '
        'an emotional low point, a spark of inspiration, teamwork and a heartfelt payoff. '
        'Each scene has its own emotion (wonder, startle, shy tenderness, concern, physical comedy, held-breath hope, '
        'quiet sadness, inspiration, focused teamwork, farewell, magic, joy and peaceful calm). '
        'Laughter is reserved for two earned moments (`S12` sheepish chuckle and `S22` celebration hug) rather than every shot.', '',
        '- **Selected opener:** vault `1002475080.mp4` (`abaee350db914237bbd563fd49afde89`), 10 s, 1920×1080, 24 fps, original audio preserved.',
        '- **Cast:** Blue **Bobo** and pink **Lulu** (from the opener) lead; joined by tall purple **Zuzu**, charcoal/silver **Pebble**, '
        'pearl-white **Numi**, and **Twinkle** (a tiny plum-sized glowing five-pointed star).',
        '- **Assembly policy:** Every source scene is kept whole (`--full-scenes`, zero lead-in or tail trims, 1× speed) '
        'with native nonverbal sound plus an original synthesized instrumental score (`lost_star_original_score.wav`) ducked underneath.', '',
        '## Shot breakdown', '',
        '| Shot | Timeline | Len | Cast | Emotion | Action | Sound |',
        '| --- | --- | --- | --- | --- | --- | --- |',
        '| Opener | 00:00–00:10 | 10s | Bobo, Lulu | Bright series intro | Selected vault `1002475080.mp4` | Original opener soundtrack |',
    ]
    for s in shots:
        lines.append(f'| {s["id"]} · {s["title"]} | {tc(s["start"])}–{tc(s["end"])} | {s["duration"]}s | {", ".join(s["cast"])} | {s["emotion"]} | {s["action"]} | {s["sound"]} |')
    lines += [
        '', '## Execution and resume', '',
        '- Plan & manifest generator: `python docs/ltx25_test/fluffies_lost_star_plan.py` → `state/fluffies_ep03_lost_star/manifest.json`.',
        '- Original score: `python docs/ltx25_test/fluffies_lost_star_score.py` → `state/fluffies_ep03_lost_star/lost_star_original_score.wav`.',
        '- Video producer: `python -u docs/ltx25_test/tumble_puffs_ep01/episode_runner.py render --out state/fluffies_ep03_lost_star`.',
        '- Full-scene editor / publisher: `python docs/ltx25_test/fluffies_shortcut_finish.py --out state/fluffies_ep03_lost_star --full-scenes --wait --publish` (or `--preview N` for a WIP prefix).',
        ''
    ]
    Path(__file__).with_name('FLUFFIES_LOST_STAR_PLAN.md').write_text('\n'.join(lines), encoding='utf-8')
    import html
    esc = html.escape
    cards = []
    for s in shots:
        cards.append(f'<article><a href="{s["frame"]}"><img src="{s["frame"]}" alt="{esc(s["title"])}"></a>'
                     f'<h2>{s["id"]} · {esc(s["title"])}</h2>'
                     f'<p class="meta">{s["start"]:g}–{s["end"]:g}s · {s["duration"]}s · {esc(", ".join(s["cast"]))} · <em>{esc(s["emotion"])}</em></p>'
                     f'<p>{esc(s["action"])}</p><details><summary>Camera, sound and prompts</summary>'
                     f'<p><strong>Camera:</strong> {esc(s["camera"])}</p><p><strong>Sound:</strong> {esc(s["sound"])}</p>'
                     f'<p>{esc(s["video_prompt"])}</p></details></article>')
    doc = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Fluffies — The Little Lost Star storyboard</title>'
           '<style>body{margin:0;background:#0f1326;color:#eef1ff;font:16px/1.55 system-ui}header{max-width:1250px;margin:auto;padding:32px}'
           '.opener{max-width:640px;width:100%;border-radius:14px}main{max-width:1600px;margin:auto;padding:24px;display:grid;'
           'grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}article{background:#1b2140;padding:16px;border-radius:18px}'
           'img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;background:#0a0d1a}h2{font-size:20px;margin:10px 0 4px}'
           '.meta{color:#a8b2df;font-size:14px}details p{font-size:13px}a{color:#8ab4ff}</style><header>'
           '<h1>Fluffies — The Little Lost Star</h1>'
           '<p>Bobo and Lulu watch a shooting star tumble into a daisy bush on their hilltop. Inside is Twinkle, a tiny lost star who cannot jump high enough to get home. '
           'After a seesaw catapult mishap and a popped balloon basket leave everyone heartbroken, a floating dandelion seed above a warm lantern gives Bobo an idea: '
           'all five friends build a giant paper sky lantern to lift Twinkle back into the night sky.</p>'
           '<video class="opener" controls preload="metadata" src="refs/1002475080.mp4"></video></header><main>'
           + ''.join(cards) + '</main></html>')
    (OUT / 'storyboard.html').write_text(doc, encoding='utf-8')
    print(json.dumps(dict(shots=len(shots), story_seconds=story, full_seconds=story + 10)))


if __name__ == '__main__':
    build()
