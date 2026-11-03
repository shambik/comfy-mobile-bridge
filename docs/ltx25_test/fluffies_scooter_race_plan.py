"""Fluffies — The Big Scooter Race: High-energy story-driven racing episode.

13 tightly storyboarded physical comedy scenes + 10s selected opener:
- Opener: 00:00 - 00:10 (10s, 240 frames, 1920x1080)
- S01: The Starting Line (6s, 144 frames)
- S02: The Countdown & Whistle (5s, 120 frames)
- S03: The Launch (6s, 144 frames)
- S04: Bobo's Red Scooter Coast (6s, 144 frames)
- S05: Lulu's Mint Balance Bike Sprint (6s, 144 frames)
- S06: Zuzu's Wild Cornering (6s, 144 frames)
- S07: Pebble's Steady Chug (6s, 144 frames)
- S08: The Wooden Bridge Hop (6s, 144 frames)
- S09: Zuzu's Daisy Drift (6s, 144 frames)
- S10: Pebble's Polite Overtake (6s, 144 frames)
- S11: The Downhill Final Sprint (7s, 168 frames)
- S12: The Finish Line Ribbon Snap (6s, 144 frames)
- S13: The Victory Group Bounce (7s, 168 frames)
Total story: 79s (1896 frames). Full episode: 89s (2136 frames).
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state' / 'fluffies_ep04_scooter_race'
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'prompts').mkdir(exist_ok=True)
(OUT / 'frames').mkdir(exist_ok=True)
(OUT / 'clips').mkdir(exist_ok=True)
(OUT / 'qc').mkdir(exist_ok=True)

CAST = {
    'Bobo': 'Bobo: rounded sapphire/sky-blue bean-shaped Fluffie with icy-blue cheeks and belly, big expressive teal eyes, one swept fluffy crown tuft, soft tiny mitten paws and broad feet.',
    'Lulu': 'Lulu: petite rounded rose-pink Fluffie with soft blush face and belly, big teal eyes with delicate lashes, split soft crown tuft, cute energetic expression.',
    'Zuzu': 'Zuzu: tall soft pear-shaped violet Fluffie with lavender fur, hazel eyes, tall spiky violet crown tufts, goofy cheerful personality.',
    'Pebble': 'Pebble: squat rounded-square charcoal/soft-black Fluffie with silver-grey face and belly, warm amber eyes, broad shaggy crest, calm unhurried demeanor.',
    'Numi': 'Numi: small upright pearl-white oval Fluffie with ivory fur, ice-blue eyes, forward-curling crown tuft, wearing a tiny red referee cap and holding a checkered flag.',
}

VEHICLES = {
    'Bobo_scooter': 'Bobo\'s bright cherry-red vintage enamel kick-scooter with chunky cream solid rubber disc wheels, polished oak foot deck, curved chrome handlebars with a shiny brass thumb-bell, and a tiny red pennant flag on the rear wheel guard.',
    'Lulu_bike': 'Lulu\'s pastel mint-green low wooden balance bicycle with chunky cream solid disc wheels, a woven wicker front basket with yellow buttercup flowers, and pink rubber hand grips.',
    'Zuzu_scooter': 'Zuzu\'s tall sunny-yellow kick-scooter with an extra-tall handlebar stem, bright turquoise solid disc wheels, and vibrant striped rainbow ribbon streamers fluttering from both handlebar grips.',
    'Pebble_trike': 'Pebble\'s sturdy sky-blue wooden three-wheel trike with wide cream solid wheels, low wooden seat, and a small open wooden cargo box on the back with a tiny checkered flag.',
}

STYLE = (
    'Original premium 3D animated family film in the spirit of a high-energy nonverbal preschool comedy (like Sunny Bunnies). '
    'Tactile groomed fur with soft secondary bounce, appealing expressive eyes, tiny mitten paws and broad soft feet, '
    'grounded physical body weight, toy-like storybook world with rounded cobbles, pastel cottages, and lush green lawns, '
    'bright sunny morning lighting, warm rim light, realistic contact shadows, clear readable silhouettes. '
)

SHOT_SPECS = [
    {
        'id': 'S01',
        'title': 'The Starting Line',
        'duration': 6,
        'cast': ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi'],
        'emotion': 'High anticipation and excitement',
        'image_prompt': (
            f'{STYLE} Wide establishing shot of the starting line on a sunlit cobbled storybook village lane under a festive pastel pennant banner. '
            'Across the white chalk line are lined up side-by-side with clear spacing: '
            'on the left, blue Bobo on his red kick-scooter with one foot on the wooden deck and one foot on the ground; '
            'beside him, pink Lulu on her mint-green balance bike with wicker flower basket, feet on the ground; '
            'center-right, tall purple Zuzu on his tall yellow scooter with rainbow streamers; '
            'on the far right, squat charcoal Pebble seated calmly on his sky-blue 3-wheel trike. '
            'At the far left on a small wooden step-podium, pearl-white Numi holds a checkered pastel flag high and points forward. '
            'Bright morning sunshine, colorful cottages with flower boxes in the background, crisp 16:9 framing, clean composition.'
        ),
        'video_prompt': (
            'Wide shot: the racers at the chalk starting line bounce with anticipation. Blue Bobo taps his foot on the cobblestones and rings his brass bell; '
            'pink Lulu wiggles her handlebars eagerly; tall purple Zuzu tests his rainbow streamers; charcoal Pebble smiles calmly on his trike; '
            'pearl-white Numi on the wooden step raises the checkered flag high. Continuous camera, no cuts, no extra characters.'
        ),
        'sound': 'Excited chattering chirps, soft foot taps on cobbles, a brass bell ping "ding!", fluttering streamers, cheering crowd murmur.',
        'seed': 4001,
    },
    {
        'id': 'S02',
        'title': 'The Countdown & Whistle',
        'duration': 5,
        'cast': ['Numi'],
        'emotion': 'Determined referee focus',
        'image_prompt': (
            f'{STYLE} Low-angle medium close-up of pearl-white Numi standing on the wooden step-podium. '
            'Numi holds a shiny golden metal whistle to lips with one tiny mitten paw, puffy rounded cheeks ready to blow, '
            'and holds the pastel checkered flag high overhead in the other paw, eyes focused forward with serious cute determination. '
            'Sunlit cobbled street and cheering village backdrop softly blurred, shallow depth of field, crisp 16:9 cinematic still.'
        ),
        'video_prompt': (
            'Medium close-up: pearl-white Numi on the step-podium puffs up round cheeks, gives three sharp whistle blasts with head bobs, '
            'then sharply snaps the checkered flag downward in an energetic sweep to start the race, cheering enthusiastically! '
            'Smooth slow push in, no cuts, no extra characters.'
        ),
        'sound': 'Three sharp whistle blasts ("pip pip pip!"), a whoosh of the checkered flag snapping down, Numi\'s loud cheerful squeak "Wheee!".',
        'seed': 4002,
    },
    {
        'id': 'S03',
        'title': 'The Launch',
        'duration': 6,
        'cast': ['Bobo', 'Lulu'],
        'emotion': 'Explosive start and joyful speed',
        'image_prompt': (
            f'{STYLE} Dynamic low tracking shot right at the starting line: blue Bobo on his red kick-scooter and pink Lulu on her mint-green balance bike '
            'surging across the white chalk line side-by-side mid-stride! Bobo is kicking hard off the cobblestones with one foot, leaning forward with an ecstatic grin; '
            'Lulu is pumping her little feet rapidly, ears fluttering back in the wind. Tiny puffs of dust kick up behind their chunky solid cream wheels. '
            'Low camera looking up at them from the sunny roadway ahead, beautiful motion blur in background, crisp 16:9 composition.'
        ),
        'video_prompt': (
            'Low tracking shot moving backwards down the lane: blue Bobo on the red scooter and pink Lulu on the mint balance bike burst forward side-by-side, '
            'kicking their feet and accelerating rapidly across the cobblestones, laughing nonverbally with joy as they pull away. '
            'Continuous smooth backwards camera tracking, no internal cuts, exactly Bobo and Lulu only.'
        ),
        'sound': 'Rapid foot scrambles, whirring wheels on smooth stone, twin joyful yelps of excitement, rushing wind.',
        'seed': 4003,
    },
    {
        'id': 'S04',
        'title': 'Bobo\'s Red Scooter Coast',
        'duration': 6,
        'cast': ['Bobo'],
        'emotion': 'Thrill of speed and pride',
        'image_prompt': (
            f'{STYLE} Dynamic three-quarter front tracking shot of blue Bobo speeding down a gentle sunlit cobbled slope on his cherry-red kick-scooter! '
            'Bobo has both feet planted neatly on the polished oak foot deck in an aerodynamic tuck, tiny paws gripping the chrome handlebars, '
            'reaching one thumb to ring the brass bell. His sky-blue fur ripples in the breeze, one fluffy crown tuft swept back, big teal eyes gleaming. '
            'Cream wheels spinning smoothly, pastel cottages and blooming flower gardens gliding past in background, cinematic 16:9 framing.'
        ),
        'video_prompt': (
            'Tracking shot alongside: blue Bobo coasts down the cobbled slope in a speed tuck on the red scooter, then pops upright with a proud grin '
            'and thumbs the brass bell twice ("ding-ding!"), waving one paw playfully toward the camera. Smooth continuous camera tracking, '
            'no cuts, no duplicate characters.'
        ),
        'sound': 'Smooth wheel whirr on stone, double brass bell chime ("ding-ding!"), wind rush, Bobo\'s happy humming giggle.',
        'seed': 4004,
    },
    {
        'id': 'S05',
        'title': 'Lulu\'s Mint Balance Bike Sprint',
        'duration': 6,
        'cast': ['Lulu'],
        'emotion': 'Playful determination and grace',
        'image_prompt': (
            f'{STYLE} Low side-tracking action shot of pink Lulu on her pastel mint-green balance bike gliding fast down the sunlit stone promenade. '
            'Lulu has lifted both tiny feet into the air to coast, balancing playfully, yellow buttercup flowers in the wicker front basket fluttering back, '
            'her rosy fur catching warm sunlight, split crown tufts bouncing with momentum. Solid cream disc wheels spinning cleanly on the cobblestones, '
            'cinematic depth of field, crisp 16:9 framing.'
        ),
        'video_prompt': (
            'Low tracking shot: pink Lulu glides down the promenade on her mint balance bike with both feet lifted high, leaning gracefully side to side '
            'to steer, grinning with pure delight as the basket flowers flutter. Lulu puts her feet down to give two quick kicks, speeding up further. '
            'Continuous smooth side tracking, no cuts, exactly Lulu only.'
        ),
        'sound': 'Whirring cream wheels, fluttering flower petals, Lulu\'s cheerful squeak and happy little humming giggle.',
        'seed': 4005,
    },
    {
        'id': 'S06',
        'title': 'Zuzu\'s Wild Cornering',
        'duration': 6,
        'cast': ['Zuzu'],
        'emotion': 'Over-enthusiastic goofy cornering',
        'image_prompt': (
            f'{STYLE} Dynamic street-corner shot looking past a pastel rounded bakery cottage: tall purple Zuzu on his tall sunny-yellow kick-scooter '
            'banking sharply into a 90-degree curve around the corner! Zuzu is leaning heavily into the turn at a 45-degree angle, eyes wide and tongue poking out playfully, '
            'rainbow ribbon streamers fluttering horizontally in the wind from both handlebars, turquoise wheels gripping the curved curb. '
            'Sunlight illuminating his lavender fur, flower pots on window sills, crisp 16:9 action still.'
        ),
        'video_prompt': (
            'Street corner view: tall purple Zuzu swoops into frame around the sharp bakery corner on the yellow scooter, banking steeply into the turn. '
            'The rainbow streamers flutter wildly as Zuzu wobbles comically for a beat, corrects balance with an exaggerated leg kick, and zooms straight ahead. '
            'Smooth continuous camera, no cuts, exactly Zuzu only.'
        ),
        'sound': 'Tire scrub squeak on cobbles, fluttering ribbon whoosh, Zuzu\'s comical startled gasp turning into an eager laugh "Wooo-whoa!".',
        'seed': 4006,
    },
    {
        'id': 'S07',
        'title': 'Pebble\'s Steady Chug',
        'duration': 6,
        'cast': ['Pebble'],
        'emotion': 'Unbothered, steady, serene confidence',
        'image_prompt': (
            f'{STYLE} Low-angle front tracking shot of squat charcoal Pebble seated calmly on his sky-blue three-wheel cargo trike, rolling down the wide garden path. '
            'Pebble holds the handlebars with both paws, silver-grey face beaming with a gentle relaxed smile, amber eyes twinkling calmly. '
            'The wooden cargo box on the back holds a tiny checkered flag standing straight. Three wide cream wheels roll smoothly over the flat flagstones. '
            'Sunlit park greenery, flower beds, and butterflies in background, peaceful and adorable, crisp 16:9 framing.'
        ),
        'video_prompt': (
            'Slow tracking shot ahead of Pebble: charcoal Pebble rolls steadily along the path in his blue trike at a calm, deliberate pace, '
            'bobbing his head in gentle rhythm, completely relaxed while the race rages ahead, giving a gentle contented hum. '
            'Continuous forward camera move, no cuts, exactly Pebble only.'
        ),
        'sound': 'Rhythmic gentle wooden rattle and wheel hum, soft summer birdsong, Pebble\'s low contented hum and peaceful snuffle.',
        'seed': 4007,
    },
    {
        'id': 'S08',
        'title': 'The Wooden Bridge Hop',
        'duration': 6,
        'cast': ['Bobo', 'Lulu'],
        'emotion': 'Thrilling synchronized jump and bounce',
        'image_prompt': (
            f'{STYLE} Side-view wide shot of a charming arched wooden footbridge crossing a gentle park brook with water lilies. '
            'Blue Bobo on his red scooter and pink Lulu on her mint balance bike are caught mid-crest at the top of the wooden arch! '
            'Their cream wheels have lifted two inches off the wooden planks in a gentle graceful hop, both characters with arms raised slightly, '
            'expressions of exhilarating surprise and joy, warm golden sunlight glinting off the water below. Crisp 16:9 storybook composition.'
        ),
        'video_prompt': (
            'Wide side shot: Bobo and Lulu ride up the arched wooden bridge side-by-side, hop smoothly over the crest with a gentle float in the air, '
            'and land softly on the downslope with bouncy plush suspension, continuing down the park trail with synchronized joyful cheers! '
            'Smooth tracking shot, no cuts, exactly Bobo and Lulu.'
        ),
        'sound': 'Rumbling wooden planks, a soft airy whoosh, a twin soft landing "thump-thump", water splashing gently below, excited squeals.',
        'seed': 4008,
    },
    {
        'id': 'S09',
        'title': 'Zuzu\'s Daisy Drift',
        'duration': 6,
        'cast': ['Zuzu'],
        'emotion': 'Harmless slapstick and surprised relief',
        'image_prompt': (
            f'{STYLE} Park trail corner where the cobblestone path bends around a lush border of giant soft white daisies. '
            'Tall purple Zuzu on his yellow scooter is mid-skid over a colorful scatter of fallen rose and daisy petals on the path! '
            'Zuzu has both feet off the scooter deck, arms flailing gently for balance, sliding toward the soft cushion of giant daisy flowers. '
            'Petals swirling in the air around the turquoise wheels, comical wide eyes, warm morning park lighting, crisp 16:9 framing.'
        ),
        'video_prompt': (
            'Action shot: Zuzu skids gently across the flower petals, swerves off the stone path onto the soft lawn, and comes to a cushioned, '
            'harmless stop right into the giant daisy hedge. Daisy blossoms shower down softly onto Zuzu\'s head as Zuzu blinks sheepishly. '
            'Smooth camera following the slide, no cuts, exactly Zuzu only.'
        ),
        'sound': 'Tire slide on loose petals, rustling soft flower bushes, a gentle soft "flump!", Zuzu\'s goofy sheepish grunt "Oof!".',
        'seed': 4009,
    },
    {
        'id': 'S10',
        'title': 'Pebble\'s Polite Overtake',
        'duration': 6,
        'cast': ['Pebble', 'Zuzu'],
        'emotion': 'Warm comedic irony and friendship',
        'image_prompt': (
            f'{STYLE} Wide shot along the edge of the stone path: on the right in the grassy border, tall purple Zuzu is sitting comfortably '
            'in the daisy bush with several white daisies stuck in his lavender fur, next to his upright parked yellow scooter. '
            'On the main stone path, squat charcoal Pebble rolls steadily past in his sky-blue trike, raising one tiny paw in a polite, friendly wave. '
            'Zuzu smiles sheepishly and waves back with a mitten paw. Gentle sunbeams through park trees, crisp 16:9 storybook framing.'
        ),
        'video_prompt': (
            'Wide shot: Pebble in his blue trike rolls steadily down the path past the daisy bush where Zuzu sits. Pebble raises a paw and gives '
            'a polite little wave; Zuzu shakes petals off his ears and waves back with a funny sheepish smile. Pebble continues chugging along smoothly. '
            'Static wide camera, no cuts, exactly Pebble and Zuzu.'
        ),
        'sound': 'Steady trike wheel rattle, a tiny polite bell ring ("ding!"), Pebble\'s cheerful chirp, Zuzu\'s sheepish chuckle.',
        'seed': 4010,
    },
    {
        'id': 'S11',
        'title': 'The Downhill Final Sprint',
        'duration': 7,
        'cast': ['Bobo', 'Lulu', 'Pebble'],
        'emotion': 'Ultimate peak excitement, full throttle sprint',
        'image_prompt': (
            f'{STYLE} Dynamic low-angle tracking shot moving down the wide sunlit promenade toward the finish line: '
            'racing three-wide neck-and-neck are blue Bobo on his red scooter (left), pink Lulu on her mint balance bike (center), '
            'and charcoal Pebble on his blue trike (right)! Bobo is kicking with full enthusiastic speed, Lulu is pedaling her feet furiously, '
            'and Pebble has his cheeks puffed out in determined exertion. Their wheels spin fast, fur ruffled by the headwind, '
            'all three faces beaming with exhilarating competitive fun! Crisp 16:9 cinematic action still.'
        ),
        'video_prompt': (
            'Low tracking shot moving backwards ahead of the three racers: Bobo, Lulu, and Pebble charge down the promenade side-by-side, '
            'trading leads by inches as they kick and pedal with all their might, cheering and giggling nonverbally in a thrilling sprint! '
            'Continuous backwards tracking camera, no cuts, exactly the three characters.'
        ),
        'sound': 'Fast whirring wheels on smooth stone, energetic kicking sounds, excited breathless panting and eager chirps, rushing air.',
        'seed': 4011,
    },
    {
        'id': 'S12',
        'title': 'The Finish Line Ribbon Snap',
        'duration': 6,
        'cast': ['Bobo', 'Lulu', 'Numi'],
        'emotion': 'Triumphant climax and celebratory joy',
        'image_prompt': (
            f'{STYLE} Three-quarter view of the finish line on the sunny park terrace: a bright pink crepe-paper ribbon is stretched across the path '
            'between two flower-wrapped wooden posts. Pearl-white Numi stands on the finish podium jumping in the air, waving the checkered flag frantically! '
            'Blue Bobo on his red scooter and pink Lulu on her mint balance bike burst through the pink ribbon simultaneously, breaking it in half with '
            'a burst of fluttering confetti and flower petals in the air! Ecstatic smiles, glittering morning sunlight, crisp 16:9 composition.'
        ),
        'video_prompt': (
            'Finish line shot: Bobo and Lulu burst through the pink ribbon together, snapping it into fluttering ribbons as colorful confetti shoots up. '
            'Numi jumps up and down on the podium waving the checkered flag with wild excitement, cheering enthusiastically! '
            'Smooth slow-motion finish effect into regular speed, no cuts, no extra characters.'
        ),
        'sound': 'Paper ribbon tearing snap, confetti pop, ecstatic crowd cheering squeaks, Numi\'s loud celebratory whistle and cheering hum!',
        'seed': 4012,
    },
    {
        'id': 'S13',
        'title': 'The Victory Group Bounce',
        'duration': 7,
        'cast': ['Bobo', 'Lulu', 'Zuzu', 'Pebble', 'Numi'],
        'emotion': 'Complete shared happiness and friendship',
        'image_prompt': (
            f'{STYLE} Warm medium-wide group shot on the lush green park terrace under a blooming cherry blossom tree. '
            'In the background, all four vehicles (Bobo\'s red scooter, Lulu\'s mint bike, Zuzu\'s yellow scooter, Pebble\'s blue trike) are parked neatly in a row. '
            'In the foreground, all five Fluffies (blue Bobo, pink Lulu, tall purple Zuzu with a daisy on his ear, squat charcoal Pebble, and pearl-white Numi holding the flag) '
            'are leaping together in a synchronized group victory bounce, paws raised high, beaming with ear-to-ear joy as flower petals drift down around them! '
            'Golden morning sunbeams, cinematic 16:9 masterpiece.'
        ),
        'video_prompt': (
            'Warm medium-wide shot: all five Fluffies jump and bounce together on the grass in celebration, hugging and high-pawing with pure joy, '
            'laughing nonverbally as gentle flower petals flutter down around them. Smooth slow push in, no cuts, all 5 characters together.'
        ),
        'sound': 'Joyful group giggles and cheerful squeaks, soft fluffy jumping thumps on grass, celebratory bell dings, warm finishing chime.',
        'seed': 4013,
    },
]


def build():
    shots = []
    current_time = 10.0  # 10s opener

    for spec in SHOT_SPECS:
        dur = spec['duration']
        shot_id = spec['id']
        shot = {
            'id': shot_id,
            'title': spec['title'],
            'start': current_time,
            'end': current_time + dur,
            'duration': dur,
            'edit_seconds': dur,
            'edit_frames': dur * 24,
            'trim_start_frame': 0,
            'mode': 'opening',
            'frame': f'frames/{shot_id}.png',
            'clip': f'clips/{shot_id}.mp4',
            'cast': spec['cast'],
            'emotion': spec['emotion'],
            'image_prompt': spec['image_prompt'],
            'video_prompt': spec['video_prompt'],
            'sound': spec['sound'],
            'seed': spec['seed'],
            'settings': {
                'engine': 'ltx',
                'mode': 'opening',
                'steps': '8',
                'ltx_quality': 'balanced',
                'aspect_ratio': '16:9',
                'ltx_sharp_decode': 'true',
                'ltx_calm_sampler': 'true',
                'no_audio': 'false',
            }
        }
        shots.append(shot)
        # Write individual prompt files for transparency and reproducibility
        (OUT / 'prompts' / f'{shot_id}-image.txt').write_text(shot['image_prompt'], encoding='utf-8')
        (OUT / 'prompts' / f'{shot_id}-video.txt').write_text(shot['video_prompt'], encoding='utf-8')
        current_time += dur

    story_seconds = int(current_time - 10.0)
    full_seconds = story_seconds + 10

    manifest = {
        'schema': 'execution_manifest.v1',
        'title': 'Fluffies — The Big Scooter Race',
        'fps': 24,
        'total_seconds': story_seconds,
        'total_frames': story_seconds * 24,
        'full_episode_seconds': full_seconds,
        'full_episode_frames': full_seconds * 24,
        'intro_seconds': 10,
        'intro_frames': 240,
        'intro': 'state/fluffies_ep04_scooter_race/refs/1002475080.mp4',
        'intro_vault_id': 'abaee350db914237bbd563fd49afde89',
        'intro_sha256': '3cf3973f41294e8a301b442817a3dff72b438c21f8b21d6cf675651d9583e7b5',
        'output_width': 1920,
        'output_height': 1080,
        'score_file': 'scooter_race_original_score.wav',
        'full_scenes_stem': 'Fluffies_The_Big_Scooter_Race',
        'master_filename': 'Fluffies_The_Big_Scooter_Race.mp4',
        'audio_policy': 'Selected opener in full with original audio; every story scene whole with native nonverbal sounds; original energetic racing score ducked underneath.',
        'cast': CAST,
        'vehicles': VEHICLES,
        'shots': shots,
    }

    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')

    # Build Markdown production plan
    def tc(t):
        return f'{int(t)//60:02d}:{int(t)%60:02d}'

    md_lines = [
        '# Fluffies — The Big Scooter & Bike Race', '',
        '## Creative Direction & Execution Rules', '',
        '- **Pacing & Energy**: High-energy, fast-paced slapstick preschool comedy (*Sunny Bunnies* style). 100% nonverbal, zero spoken dialogue.',
        '- **Vehicle Design Rules**: Chunky solid cream disc wheels, vintage enamel/wood frames. No thin wire spokes, no chain sprockets, no pedals (kick scooters, balance bikes, low 3-wheel trikes).',
        '- **Zero Video Mistakes Policy**: Feature 1–2 characters per action shot to prevent character merging or limb hallucination in LTX-2.5. Low camera tracking, single continuous moves, no internal cuts.',
        '- **Original Soundtrack**: 138 BPM energetic driving racing score synthesized with `fluffies_scooter_race_score.py` (punchy kick, snare, 16th hats, funk bass, flute/brass racing leads, whistle countdown, victory fanfare).',
        '- **Selected Opener**: Vault `1002475080.mp4`, 10.0s, 1920×1080, 24 fps, original audio preserved.', '',
        '## Shot Breakdown', '',
        '| Shot | Timeline | Len | Cast | Emotion | Action & Sound |',
        '| --- | --- | --- | --- | --- | --- |',
        '| Opener | 00:00–00:10 | 10s | Bobo, Lulu | Series Intro | Selected vault `1002475080.mp4` with original soundtrack |',
    ]

    for s in shots:
        md_lines.append(f'| {s["id"]} · {s["title"]} | {tc(s["start"])}–{tc(s["end"])} | {s["duration"]}s | {", ".join(s["cast"])} | {s["emotion"]} | {s["video_prompt"]} |')

    (OUT / 'FLUFFIES_SCOOTER_RACE_PLAN.md').write_text('\n'.join(md_lines), encoding='utf-8')

    # Build interactive HTML Storyboard
    esc = html.escape
    cards = []
    for s in shots:
        cards.append(
            f'<article id="{s["id"]}"><a href="{s["frame"]}"><img src="{s["frame"]}" alt="{esc(s["title"])}" onerror="this.src=\'refs/vehicles-sheet.png\'"></a>'
            f'<h2>{s["id"]} · {esc(s["title"])}</h2>'
            f'<p class="meta">{s["start"]:g}–{s["end"]:g}s · {s["duration"]}s · {esc(", ".join(s["cast"]))} · <em>{esc(s["emotion"])}</em></p>'
            f'<p><strong>Action:</strong> {esc(s["video_prompt"])}</p>'
            f'<p><strong>Sound:</strong> {esc(s["sound"])}</p>'
            f'<details><summary>Prompt details</summary><p>{esc(s["image_prompt"])}</p></details>'
            f'</article>'
        )

    storyboard_html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<title>Fluffies — The Big Scooter Race Storyboard</title>'
        '<style>'
        'body{margin:0;background:#0d1117;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;line-height:1.5}'
        'header{max-width:1400px;margin:auto;padding:32px 24px;border-bottom:1px solid #30363d}'
        'h1{margin:0 0 8px;color:#58a6ff;font-size:32px}p.lead{font-size:18px;color:#8b949e;margin:0 0 20px}'
        '.media-grid{display:flex;gap:20px;flex-wrap:wrap;margin-top:20px}'
        'video, .ref-img{max-width:480px;width:100%;border-radius:12px;border:1px solid #30363d;background:#000}'
        'main{max-width:1600px;margin:auto;padding:32px 24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:24px}'
        'article{background:#161b22;border:1px solid #30363d;border-radius:14px;padding:18px;display:flex;flex-direction:column}'
        'img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:#21262d;margin-bottom:12px}'
        'h2{margin:0 0 6px;color:#f0f6fc;font-size:20px}'
        '.meta{color:#58a6ff;font-size:13px;font-weight:600;margin:0 0 10px}'
        'details{margin-top:auto;padding-top:10px;border-top:1px solid #21262d;font-size:12px;color:#8b949e}'
        '</style></head><body><header>'
        '<h1>Fluffies — The Big Scooter Race</h1>'
        '<p class="lead">High-energy slapstick racing episode featuring Bobo, Lulu, Zuzu, Pebble, and referee Numi on custom scooters, balance bikes, and trikes.</p>'
        '<div class="media-grid">'
        '<div><h3>Selected Opener (10s)</h3><video controls preload="metadata" src="refs/1002475080.mp4"></video></div>'
        '<div><h3>Vehicle Reference Sheet</h3><img class="ref-img" src="refs/vehicles-sheet.png" alt="Vehicles"></div>'
        '</div></header><main>'
        + ''.join(cards) +
        '</main></body></html>'
    )

    (OUT / 'storyboard.html').write_text(storyboard_html, encoding='utf-8')
    print(json.dumps({'status': 'plan_ready', 'shots': len(shots), 'story_seconds': story_seconds, 'full_seconds': full_seconds}))


if __name__ == '__main__':
    build()
