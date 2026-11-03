"""Rift Runners — The Chrono-Core Heist (Ages 8–12 · 6-Character, Space-Vehicles, Lyria 3.5 Hip-Hop & Gemini 3.8 Voices Edition).

Implements the official LTX-2.5 Prompt Guide (https://ltx.io/blog/ltx-2-5-prompt-guide):
1. Flowing chronological present-tense paragraph structure following the 6-layer formula:
   [Camera & Lens] + [Subject] + [Action & Timeline] + [Environment & Lighting] + [Style & Fidelity] + [Audio].
2. Expanded 6-Character Crew (5 anthropomorphic animal heroes + Pip the clockwork relic) plus
   2 signature anti-gravity space vehicles (The Star-Skiff multi-crew hover-speeder & Jinx's Mag-Board).
3. Spoken Character Dialogue synthesized with Google Gemini 3.8 Flash TTS (`gemini-3.8-flash-tts`
   multi-speaker & voice cloning engine) and studio Hip-Hop soundtrack composed with Google Lyria 3.5 (`lyria-3.5`).
4. Native Multishot scenes (S03, S07, S09, S13) using explicit "Hard cut to..." prose while
   restating character, vehicle, lighting, and audio continuity across the cut.
5. First-and-Last-Frame interpolation flows (S04, S08, S11, S16) using `mode: "frames"` with
   dedicated `SXX.png` and `SXX_end.png` keyframes and smooth transition prompts.
6. Sequential Last-Frame Extraction flows (S02<-S01, S06<-S05, S12<-S11, S15<-S14) where the
   renderer extracts the verified final frame of the preceding clip (`extract_last_frame`)
   to continue motion and camera momentum seamlessly.
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'state/rift_runners_ep01'

CAST = {
    'Kael': (
        'Kael, an agile tween-proportioned cobalt-blue and slate-white lynx-fox scout with '
        'pointed tufted ears, sharp amber-gold eyes, expressive dark eyebrows, a weathered copper-brown '
        'leather vest, fingerless climbing gloves, and brass aviator goggles on his forehead'
    ),
    'Nyx': (
        'Nyx, a sleek charcoal-black and silver-grey marten gadgeteer with violet-tipped ear tufts, '
        'sharp emerald-green eyes, a tan canvas crossbody satchel, and a glowing cyan crystal '
        'wrist-grappler gauntlet on her left forearm'
    ),
    'Bram': (
        'Bram, a broad-shouldered stocky rust-red and cream-striped badger-bear heavy with thick '
        'groomed fur, expressive bushy eyebrows, warm hazel eyes, a riveted bronze shoulder pauldron, '
        'and a coiled climbing rope across his chest'
    ),
    'Zara': (
        'Zara, a high-energy sunburst-gold and warm-cream fennec-fox ace pilot with tall expressive '
        'black-tipped ears, a luminous turquoise holographic flight visor, a white-and-tangerine cropped '
        'flight jacket with brass buckles, and padded pilot gloves'
    ),
    'Jinx': (
        'Jinx, a nimble amethyst-violet and pearl-white ring-tailed lemur mechanic and hoverboarder with '
        'a long striped purple-and-white tail, bright golden eyes, oversized bronze magnifying goggles, '
        'and a teal tool-bandolier'
    ),
    'Pip': (
        'Pip, a fist-sized living clockwork-crystal relic shaped like a floating glowing amber-gold '
        'sunstone octahedron inside two spinning brass astrolabe rings, with two expressive luminous '
        'cyan shutter-eyes'
    ),
}

CHARACTER_VOICES = {
    'Kael': 'Puck',
    'Nyx': 'Kore',
    'Bram': 'Charon',
    'Zara': 'Zephyr',
    'Jinx': 'Fenrir',
}

VEHICLES = {
    'StarSkiff': (
        'the Star-Skiff (Aether-Runner), a sleek open-cockpit multi-crew anti-gravity space speeder '
        'built from brushed brass, cobalt-blue hull plates, and weathered steel, featuring twin side-mounted '
        'ion-thruster pods, glowing cyan repulsor rings underneath, a front pilot yoke, and a rear deck rail'
    ),
    'MagBoard': (
        'the Mag-Board, a compact brass-and-teal anti-gravity space hoverboard with glowing turquoise '
        'repulsor pads and twin neon-cyan plasma micro-jets at the tail'
    ),
}

STYLE_SENTENCE = (
    'Rendered as a premium 3D animated sci-fi adventure film for ages 8 to 12 with tactile groomed fur, '
    'subtle secondary motion, weathered leather, brushed brass and glowing ion-thruster textures, '
    'shallow depth of field, and natural motion blur.'
)

LIGHT = {
    'dusk': (
        'Warm golden-hour cosmic dusk sunlight rakes low across the mossy asteroid stone, fur, and metallic '
        'vehicle hulls with deep teal nebula chasm shadows and crisp amber rim light.'
    ),
    'sanctum': (
        'Bioluminescent cyan crystal sconces and warm golden sunstone light illuminate the carved '
        'stone sanctum with clear, readable contrast.'
    ),
    'hazard': (
        'Glowing crimson warning runes on the stone floor mix with cool cyan ion-thruster glow and crystal '
        'shafts overhead, casting dramatic high-contrast rim light.'
    ),
    'twilight': (
        'Luminous indigo starlight and glowing nebula clouds bathe the mossy asteroid cliff dock while the '
        'amber Chrono-Core and cyan vehicle repulsors cast warm golden and turquoise key light across the crew.'
    ),
}

SETS = {
    'cliff': (
        'ancient mossy asteroid cliffside landing dock overlooking a floating clockwork sky-temple with '
        'carved weathered pillars, embedded brass gears, and floating asteroid ruins across a starry nebula chasm'
    ),
    'bridge': (
        'ancient stone pressure-plate sky-bridge spanning a starry nebula chasm with square carved stone tiles, '
        'sunken brass mechanisms, and weathered stone side walls with recessed energy-dart ports'
    ),
    'sanctum': (
        'vaulted inner sanctum of the floating clockwork sky-temple with towering carved stone columns, '
        'inlaid brass astrolabe tracks, a central stepped stone altar, and glowing cyan floor channels'
    ),
}

SHOT_SPECS = [
    # ACT I — Space-Skiff Arrival & The Bridge Booby Trap
    dict(
        id='S01', title='Star-Skiff Touchdown', seconds=7, flow_mode='opening', prev_shot=None,
        cast=['Zara', 'Kael', 'Nyx', 'Bram', 'Jinx'], vehicles=['StarSkiff', 'MagBoard'],
        location='cliff', light='dusk',
        emotion='High-speed arrival and eager squad swagger',
        camera='A dynamic low-angle 35mm Steadicam tracking shot glides smoothly from left to right alongside the hovering vehicles',
        opening=(
            'Zara banks the hovering open-cockpit Star-Skiff in a low anti-gravity drift over the mossy asteroid dock '
            'with Kael, Nyx, and Bram braced on its deck, while Jinx surfs right alongside on his glowing cyan Mag-Board.'
        ),
        closing=None,
        action=(
            'Zara eases the twin ion-throttles back as the Star-Skiff settles into a steady low hover above the mossy '
            'stone dock with glowing cyan repulsor rings pulsing underneath; Jinx carves a tight arc on his Mag-Board '
            'and hops onto the stone beside Kael and Nyx as Zara calls out from the cockpit and Kael points eagerly '
            'toward the temple bridge and replies.'
        ),
        sound=(
            'Twin ion-thrusters purr and decelerate with a bassy anti-gravity hum, the Mag-Board whirs sharply, boots '
            'thud onto mossy stone, and Zara and Kael exchange excited banter.'
        ),
        dialogue=[
            dict(speaker='Zara', voice='Zephyr', text='[excited] Touchdown on the sky-dock! Keep the Star-Skiff warm, crew!'),
            dict(speaker='Kael', voice='Puck', text='[cheerfully] Chrono-Core, here we come! Follow my lead!'),
        ],
    ),
    dict(
        id='S02', title='Hoverboard Shortcut', seconds=7, flow_mode='sequential', prev_shot='S01',
        cast=['Kael', 'Jinx', 'Nyx', 'Zara', 'Bram'], vehicles=['MagBoard', 'StarSkiff'],
        location='bridge', light='dusk',
        emotion='Daredevil impatience ignoring a tactical warning',
        camera='A smooth medium-wide lateral tracking shot on a 35mm lens follows the movement from left to right toward the bridge',
        opening=(
            'At the stone sky-bridge threshold with Zara and Bram watching from the hovering Star-Skiff, Nyx points '
            'warningly at a cracked pressure-plate rune while Kael grins and steps one boot onto Jinx\'s hovering Mag-Board.'
        ),
        closing=None,
        action=(
            'Continuing the motion from the opening frame without pause, Nyx points warningly at the trapped bridge tile '
            'and calls out to Kael, but Kael waves her off with a cocky smirk as he and Jinx kick the glowing cyan '
            'Mag-Board forward across the bridge threshold.'
        ),
        sound=(
            'A crisp plasma-board ignition whoosh, Nyx\'s sharp warning, and Jinx and Kael\'s cocky reply over the '
            'idle hum of the Star-Skiff.'
        ),
        dialogue=[
            dict(speaker='Nyx', voice='Kore', text='[cautiously] Hold up, Kael! Those stone tiles are wired to an ancient pressure trap!'),
            dict(speaker='Jinx', voice='Fenrir', text='[mischievously] Good thing my Mag-Board floats two feet above the floor! Hop on!'),
        ],
    ),
    dict(
        id='S03', title='Pressure-Tile Ion Trap! (Multishot)', seconds=8, flow_mode='multishot', prev_shot=None,
        cast=['Kael', 'Jinx', 'Zara', 'Nyx'], vehicles=['MagBoard', 'StarSkiff'],
        location='bridge', light='dusk',
        emotion='Smugness snapping into instant wide-eyed panic',
        camera='A low-angle 35mm dolly-in starts on the bridge tile, followed by a hard cut to a 50mm close-up of the dodging riders',
        opening=(
            'On the stone sky-bridge, Kael hops off Jinx\'s hovering Mag-Board onto the first carved stone tile with '
            'a smug look back while Jinx hovers beside him.'
        ),
        closing=None,
        action=(
            'The carved stone tile beneath Kael\'s boots sinks into the bridge floor with a heavy mechanical click as '
            'brass wall-turrets unfold. Hard cut to a medium close-up of cobalt-blue Kael and violet lemur Jinx on '
            'his Mag-Board in the same golden dusk light as their grins freeze into wide-eyed panic, glowing cyan '
            'energy-darts streak past their ears, and Kael yelps while Zara banks the Star-Skiff in behind them.'
        ),
        sound=(
            'A heavy stone grinding click and rapid clockwork ratcheting echo across the chasm, followed across the '
            'cut by high-pitched energy-dart zips, roaring ion-engines, and Kael and Jinx\'s panicked shouts.'
        ),
        dialogue=[
            dict(speaker='Kael', voice='Puck', text='[surprised] Uh-oh! Okay, Nyx was right—the floor is definitely angry!'),
            dict(speaker='Jinx', voice='Fenrir', text='[excited] Duck! Ion-darts incoming at twelve o-clock!'),
        ],
    ),
    dict(
        id='S04', title='Skiff & Hoverboard Rescue (First+Last)', seconds=7, flow_mode='first_last', prev_shot=None,
        cast=['Kael', 'Nyx', 'Zara', 'Jinx', 'Bram'], vehicles=['StarSkiff', 'MagBoard'],
        location='bridge', light='dusk',
        emotion='Frantic aerial pickup and deadpan rescue',
        camera='Smooth continuous camera move from the first frame to the last frame via a steady 35mm tracking pull-back onto the Star-Skiff deck',
        opening=(
            'Above the trapped bridge, Zara holds the Star-Skiff in a tight hover as Nyx leans over the rail firing '
            'a taut glowing cyan energy-tether onto Kael\'s vest while Jinx boosts upward on his Mag-Board beside him.'
        ),
        closing=(
            'On the wide rear deck of the hovering Star-Skiff, Kael sits sprawled in a disheveled heap with goggles '
            'askew while Nyx retracts her glowing gauntlet with a deadpan eye-roll and Zara, Bram, and Jinx look on.'
        ),
        action=(
            'Smooth continuous camera move from the first frame to the last frame. Zara reverses the Star-Skiff\'s '
            'thrusters as Nyx and Bram reel the glowing cyan energy-tether backward, hoisting Kael off the dart-swept '
            'bridge right onto the skiff\'s rear deck while Jinx lands his Mag-Board beside them and Nyx delivers a '
            'deadpan quip. Steady, cinematic, no cut.'
        ),
        sound=(
            'An electric tether winch whir, roaring reverse ion-thrusters, a metallic thud onto the skiff deck, and '
            'Nyx and Kael\'s witty exchange.'
        ),
        dialogue=[
            dict(speaker='Nyx', voice='Kore', text='[sarcastic] You were saying about following your lead?'),
            dict(speaker='Kael', voice='Puck', text='[chuckles] I was just testing your grappler reflexes! Ten out of ten!'),
        ],
    ),
    dict(
        id='S05', title='Bram & Skiff Thruster Brace', seconds=7, flow_mode='opening', prev_shot=None,
        cast=['Bram', 'Zara', 'Kael', 'Nyx', 'Jinx'], vehicles=['StarSkiff', 'MagBoard'],
        location='cliff', light='dusk',
        emotion='Urgent brute strength combined with vehicle thrust',
        camera='A low-angle 24mm dolly-in pushes smoothly toward the descending temple gate',
        opening=(
            'At the carved stone temple archway, a massive stone gate slab slides downward; Bram braces his bronze-armored '
            'shoulder beneath the left side while Zara wedges the reinforced bow of the hovering Star-Skiff under the '
            'right side with upward repulsors flaring, as Kael, Nyx, and Jinx crouch ready.'
        ),
        closing=None,
        action=(
            'Bram plants his boots wide and strains against the heavy stone slab alongside the roaring upward repulsor '
            'thrusters of Zara\'s Star-Skiff, holding the gap open and shouting to the squad as Kael, Nyx, and Jinx '
            'on his Mag-Board dart forward under the gate.'
        ),
        sound=(
            'A deep rumbling stone grind, straining ion-repulsor whine, and Bram and Zara\'s urgent calls over the '
            'roaring thrusters.'
        ),
        dialogue=[
            dict(speaker='Bram', voice='Charon', text='[dramatically] This stone gate weighs a ton! Get inside, quick!'),
            dict(speaker='Zara', voice='Zephyr', text='[excited] Full upward repulsors! Go, go, go, I have got the right side!'),
        ],
    ),
    # ACT II — The Inner Sanctum & The Chrono-Core
    dict(
        id='S06', title='Mag-Board Gate Wedge', seconds=7, flow_mode='sequential', prev_shot='S05',
        cast=['Jinx', 'Nyx', 'Kael', 'Bram', 'Zara'], vehicles=['MagBoard'],
        location='sanctum', light='sanctum',
        emotion='Split-second five-hero coordination',
        camera='A low ground-level 35mm tracking shot pulls smoothly backward inside the glowing sanctum',
        opening=(
            'Inside the glowing bioluminescent sanctum looking back at the low doorway gap, Kael and Nyx kneel beside '
            'Jinx as they jam a heavy brass gear-wedge and Jinx\'s reinforced Mag-Board jack beneath the stone slab '
            'while Bram and Zara duck through.'
        ),
        closing=None,
        action=(
            'Continuing the motion smoothly, Nyx and Jinx lock the heavy brass wedge beneath the descending stone slab, '
            'allowing Zara and stocky Bram to roll safely through the gap into the sanctum right as the stone door '
            'crunches onto the wedge.'
        ),
        sound=(
            'Boots skidding on smooth stone, a sharp metallic clang as the brass wedge locks, and Jinx and Bram\'s '
            'relieved banter echoing in the sanctum.'
        ),
        dialogue=[
            dict(speaker='Jinx', voice='Fenrir', text='[cheerfully] Titanium gear-wedge locked! Nobody is trapping this crew!'),
            dict(speaker='Bram', voice='Charon', text='[sighs] Next temple we raid, we are taking the front elevator.'),
        ],
    ),
    dict(
        id='S07', title='The Awake Relic (Multishot)', seconds=8, flow_mode='multishot', prev_shot=None,
        cast=['Kael', 'Nyx', 'Bram', 'Zara', 'Jinx', 'Pip'], vehicles=['MagBoard'],
        location='sanctum', light='sanctum',
        emotion='Cocky curiosity turning into a comic static zap',
        camera='A medium 50mm dolly-in on the altar surrounded by the five heroes, followed by a hard cut to a macro close-up',
        opening=(
            'At the central stepped stone altar, glowing amber Pip hovers above the pedestal surrounded by all five '
            'heroes—Kael reaching his gloved paw forward while Nyx, Bram, Zara, and Jinx holding his Mag-Board watch closely.'
        ),
        closing=None,
        action=(
            'Kael reaches his gloved fingers toward floating amber Pip with a confident grin while Nyx, Bram, Zara, '
            'and Jinx lean in around the altar. Hard cut to a close-up of floating amber Pip and Kael\'s reaching hand '
            'with Jinx and Zara peeking over his shoulder in the same cyan-and-gold sanctum light as Pip\'s brass rings '
            'spin defensively and zap Kael\'s fingertip with a golden spark, making Kael yank his paw back while Jinx '
            'and Zara laugh.'
        ),
        sound=(
            'A harmonic crystal hum and rapid spinning brass rings build in pitch, followed across the cut by a crisp '
            'electric static zap, Kael\'s yelp, and Jinx\'s laugh.'
        ),
        dialogue=[
            dict(speaker='Kael', voice='Puck', text='[excited] Easy, little sunstone... ouch! Hey, this relic bites!'),
            dict(speaker='Jinx', voice='Fenrir', text='[laughs] Even the ancient clockwork knows you skipped the manual!'),
        ],
    ),
    dict(
        id='S08', title='Harmonic Resonance (First+Last)', seconds=7, flow_mode='first_last', prev_shot=None,
        cast=['Nyx', 'Jinx', 'Kael', 'Bram', 'Zara', 'Pip'], vehicles=['MagBoard'],
        location='sanctum', light='sanctum',
        emotion='Calm gadget teamwork earning the relic\'s trust',
        camera='Smooth continuous camera move from the first frame to the last frame via a slow 50mm dolly-in with shallow depth of field',
        opening=(
            'At the sanctum altar, Nyx holds up a resonant brass tuning fork while Jinx adjusts a harmonic dial on '
            'his glowing Mag-Board beside her, with Kael, Bram, and Zara watching hovering amber Pip.'
        ),
        closing=(
            'At the sanctum altar, glowing amber Pip rests peacefully just above Nyx\'s open palm with friendly cyan '
            'shutter-eyes while Jinx grins thumbs-up and Kael, Bram, and Zara lean in with impressed smiles.'
        ),
        action=(
            'Smooth continuous camera move from the first frame to the last frame. Nyx taps the brass tuning fork '
            'while Jinx pulses a gentle turquoise harmonic wave from his Mag-Board; floating amber Pip\'s cyan '
            'shutter-eyes widen happily, its brass rings slow into a gentle orbit, and Pip drifts down to hover over '
            'Nyx\'s open palm as Nyx and Zara speak warmly. Steady, cinematic, no cut.'
        ),
        sound=(
            'A pure resonant brass tuning-fork chime and soft hoverboard harmonic hum ring out, answered by Pip\'s '
            'melodic two-tone warble and gentle dialogue from Nyx and Zara.'
        ),
        dialogue=[
            dict(speaker='Nyx', voice='Kore', text='[warmly] It does not want force, Kael—it responds to a harmonic frequency. Hello there, Pip.'),
            dict(speaker='Zara', voice='Zephyr', text='[happy] Look at those cyan shutter-eyes! I think Pip likes us!'),
        ],
    ),
    dict(
        id='S09', title='Sanctum Lockdown & Skiff Ignition (Multishot)', seconds=8, flow_mode='multishot', prev_shot=None,
        cast=['Kael', 'Nyx', 'Bram', 'Zara', 'Jinx', 'Pip'], vehicles=['StarSkiff', 'MagBoard'],
        location='sanctum', light='hazard',
        emotion='Sudden temple collapse and scramble to the vehicles',
        camera='A high-angle 24mm crane tilt-down on the altar, followed by a hard cut to a low close-up at the Star-Skiff cockpit',
        opening=(
            'Around the central altar, Kael, Nyx, Bram, Zara, and Jinx brace in alarm as glowing crimson warning runes '
            'ignite along the stone floor channels and Pip hovers beside Nyx.'
        ),
        closing=None,
        action=(
            'The stone altar sinks downward as glowing crimson rune lines race across the sanctum floor and all five '
            'heroes bolt toward the exit arch. Hard cut to a low-angle close-up outside the archway in the same '
            'crimson-and-cyan hazard light as Zara vaults into the Star-Skiff pilot seat, slams the twin ion-throttles '
            'forward, and shouts to the crew as Bram, Kael, and Nyx leap aboard.'
        ),
        sound=(
            'A deep bass temple alarm horn rumbles and stone grinds downward, followed across the cut by the high-energy '
            'roar of twin ion-thrusters igniting and Bram and Zara\'s urgent commands.'
        ),
        dialogue=[
            dict(speaker='Bram', voice='Charon', text='[surprised] Crimson runes! The whole sky-temple is dropping into the rift!'),
            dict(speaker='Zara', voice='Zephyr', text='[excited] Everybody onto the Star-Skiff! Twin ion-thrusters at full burn!'),
        ],
    ),
    dict(
        id='S10', title='Full-Throttle Bridge Escape', seconds=7, flow_mode='opening', prev_shot=None,
        cast=['Zara', 'Bram', 'Kael', 'Nyx', 'Jinx', 'Pip'], vehicles=['StarSkiff', 'MagBoard'],
        location='bridge', light='hazard',
        emotion='High-speed vehicle chase across a collapsing bridge',
        camera='A fast parallel tracking shot on a 35mm lens races alongside the speeding Star-Skiff and Mag-Board',
        opening=(
            'Zara pilots the roaring Star-Skiff at full throttle across the crumbling stone sky-bridge with Bram, '
            'Kael, Nyx, and Pip aboard, while Jinx surfs tight along the skiff\'s flank on his glowing cyan Mag-Board.'
        ),
        closing=None,
        action=(
            'The Star-Skiff and Jinx\'s Mag-Board streak forward across the stone bridge with glowing cyan exhaust '
            'trails as massive stone bridge tiles crack and plunge into the nebula abyss right behind their tailfins, '
            'until Jinx points ahead at a wide chasm gap and Zara pulls back hard on the flight yoke.'
        ),
        sound=(
            'Roaring twin ion-engines, the high-pitched doppler whine of the Mag-Board, thunderous stone bridge plates '
            'crashing into the chasm, and high-speed cockpit callouts.'
        ),
        dialogue=[
            dict(speaker='Jinx', voice='Fenrir', text='[excited] Zara, the bridge center just vanished! We are out of road!'),
            dict(speaker='Zara', voice='Zephyr', text='[excited] Then we do not need roads—hang onto the deck rails, we are jumping it!'),
        ],
    ),
    dict(
        id='S11', title='Sky-Chasm Jump & Tether Catch (First+Last)', seconds=8, flow_mode='first_last', prev_shot=None,
        cast=['Zara', 'Bram', 'Kael', 'Nyx', 'Jinx'], vehicles=['StarSkiff', 'MagBoard'],
        location='bridge', light='hazard',
        emotion='White-knuckle aerial vehicle jump and cliffside catch',
        camera='Smooth continuous camera move from the first frame to the last frame via a wide 24mm side-profile pan across the chasm',
        opening=(
            'At the shattered bridge edge, Zara launches the Star-Skiff nose-up off the broken stone ramp with Bram, '
            'Kael, and Nyx aboard while Jinx boosts high alongside them on his glowing Mag-Board.'
        ),
        closing=(
            'At the far asteroid cliff lip, Kael, Nyx, and Jinx stand braced on the mossy dock with Nyx\'s taut cyan '
            'energy-tether and Jinx\'s Mag-Board tow-clamp anchored to the nose of the Star-Skiff dangling at the cliff edge '
            'with Zara and Bram inside.'
        ),
        action=(
            'Smooth continuous camera move from the first frame to the last frame. The Star-Skiff and Jinx\'s Mag-Board '
            'soar across the open chasm; Jinx, Kael, and Nyx touch down on the far asteroid ledge just as the heavy '
            'Star-Skiff\'s tail clips the cliff lip and begins sliding back, and Nyx fires her glowing cyan tether '
            'into the skiff\'s bow hook to catch Zara and Bram at the brink. Steady, cinematic, no cut.'
        ),
        sound=(
            'A full-throttle ion-booster roar across the gap, a heavy metallic hull scrape against stone, the crisp '
            'electric zip of Nyx\'s grappler tether locking onto the skiff bow, and urgent shouts.'
        ),
        dialogue=[
            dict(speaker='Kael', voice='Puck', text='[gasps] The tail thrusters clipped the ledge! Nyx, fire the grappler!'),
            dict(speaker='Nyx', voice='Kore', text='[dramatically] Tether locked onto the bow hook! Brace your boots!'),
        ],
    ),
    # ACT III — Reactor Boost & Blast-Off Finale
    dict(
        id='S12', title='Hauling the Star-Skiff', seconds=8, flow_mode='sequential', prev_shot='S11',
        cast=['Kael', 'Nyx', 'Jinx', 'Zara', 'Bram'], vehicles=['StarSkiff', 'MagBoard'],
        location='cliff', light='twilight',
        emotion='Straining five-hero effort to save the ship and crew',
        camera='A tense low-angle 35mm dolly-in pushes slowly toward the crew hauling the tethered Star-Skiff',
        opening=(
            'On the outer twilight asteroid dock, Kael, Nyx, and Jinx lean back at a steep angle gripping the taut '
            'glowing cyan tether anchored to the bow of the dangling Star-Skiff while Zara and Bram brace in the cockpit.'
        ),
        closing=None,
        action=(
            'Continuing the tense haul from the opening frame, Kael, Nyx, and Jinx dig their boots into the mossy stone '
            'with gritted teeth while Jinx\'s Mag-Board fires reverse thrusters to help anchor them, pulling against '
            'the heavy Star-Skiff as Zara\'s sputtering ion-pods struggle at the cliff edge.'
        ),
        sound=(
            'High-tension hum of the energy cable, sputtering ion-thrusters, boots scraping across gritty stone, and '
            'strained calls between Zara and Bram.'
        ),
        dialogue=[
            dict(speaker='Zara', voice='Zephyr', text='[dramatically] Main ion-pods are stalling! We need a power surge now!'),
            dict(speaker='Bram', voice='Charon', text='[excited] Hold the line, kids! Wait—look at Pip!'),
        ],
    ),
    dict(
        id='S13', title='Pip Overcharges the Ion-Core (Multishot)', seconds=8, flow_mode='multishot', prev_shot=None,
        cast=['Pip', 'Zara', 'Bram', 'Kael', 'Nyx', 'Jinx'], vehicles=['StarSkiff', 'MagBoard'],
        location='cliff', light='twilight',
        emotion='Magical chrono-reactor surge and triumphant save',
        camera='A 50mm close-up tracking Pip into the Star-Skiff reactor socket, followed by a hard cut to a wide 24mm low-angle on the landing pad',
        opening=(
            'At the twilight cliff edge, floating amber Pip darts down toward the glowing crystal reactor socket on '
            'the Star-Skiff\'s dashboard right in front of Zara and Bram.'
        ),
        closing=None,
        action=(
            'Floating amber Pip aligns its brass rings and locks into the Star-Skiff\'s dashboard reactor socket '
            'beside Zara, turning the ship\'s cyan power lines into blazing golden-amber light. Hard cut to a wide '
            'low-angle shot on the same moonlit asteroid dock as the Star-Skiff\'s twin ion-thrusters erupt with '
            'golden-amber exhaust and lift the entire ship smoothly up over the cliff lip to hover beside Kael, Nyx, '
            'and Jinx.'
        ),
        sound=(
            'A resonant crystal lock-in click and a rising golden turbine chord swell, followed across the cut by a '
            'thunderous golden ion-thruster roar and triumphant cheers from Jinx and Zara.'
        ),
        dialogue=[
            dict(speaker='Jinx', voice='Fenrir', text='[excited] Whoa! Pip just supercharged the Star-Skiff reactor to two hundred percent!'),
            dict(speaker='Zara', voice='Zephyr', text='[cheerfully] Golden ion-boost online! Up and over the ledge we go!'),
        ],
    ),
    dict(
        id='S14', title='Crew Breather on the Hull', seconds=7, flow_mode='opening', prev_shot=None,
        cast=['Bram', 'Zara', 'Jinx', 'Kael', 'Nyx', 'Pip'], vehicles=['StarSkiff', 'MagBoard'],
        location='cliff', light='twilight',
        emotion='Earned exhaustion and warm camaraderie around the ship',
        camera='A high-angle 35mm pedestal crane descends slowly and smoothly toward the five heroes resting on the Star-Skiff',
        opening=(
            'On the starry twilight asteroid dock, Bram leans back against the Star-Skiff\'s warm hull, Zara lifts her '
            'turquoise flight visor in the cockpit, Jinx sits on his Mag-Board spinning a wrench, and Kael and Nyx sit '
            'on the bow rail beside hovering Pip.'
        ),
        closing=None,
        action=(
            'Bram lets out a huge chest-falling exhale that ruffles his fur, Zara wipes her brow with a relieved grin, '
            'Jinx leans back on his hovering Mag-Board, Kael rolls his shoulder, and Nyx smiles warmly as the crew '
            'shares a relieved laugh.'
        ),
        sound=(
            'Cooling metallic hull ticks, soft idling repulsor hum, and warm relieved banter between Bram and Nyx.'
        ),
        dialogue=[
            dict(speaker='Bram', voice='Charon', text='[laughs] Remind me never to call the little clockwork rock a paperweight.'),
            dict(speaker='Nyx', voice='Kore', text='[cheerfully] Pip did not just power the skiff—it unlocked the ancient star-map.'),
        ],
    ),
    dict(
        id='S15', title='Five-Way Crew Fist Bump', seconds=7, flow_mode='sequential', prev_shot='S14',
        cast=['Kael', 'Nyx', 'Bram', 'Zara', 'Jinx', 'Pip'], vehicles=['StarSkiff'],
        location='cliff', light='twilight',
        emotion='Team unity and mutual respect',
        camera='A warm eye-level 50mm dolly-in pushes gently toward the circle of five heroes and Pip',
        opening=(
            'Gathered around the glowing bow of the Star-Skiff, Kael extends his gloved fist toward Nyx, Bram, Zara, '
            'and Jinx with a humble, grateful smile while golden Pip hovers in the center.'
        ),
        closing=None,
        action=(
            'Continuing smoothly from the opening frame, Kael gives Nyx and the crew a sincere nod; Nyx smiles warmly '
            'and brings her fist in, joined simultaneously by Bram\'s huge paw, Zara\'s pilot glove, and Jinx\'s fist '
            'in a solid five-way crew bump right beneath spinning golden Pip.'
        ),
        sound=(
            'Warm appreciative chuckles from the five friends, a solid leather-gloved five-way fist tap, Pip\'s '
            'bright harmonic fanfare chime, and Kael and Nyx\'s team pledge.'
        ),
        dialogue=[
            dict(speaker='Kael', voice='Puck', text='[warmly] Best crew in the Outer Rift. No more solo shortcuts—we fly together.'),
            dict(speaker='Nyx', voice='Kore', text='[happy] Deal. All five of us, plus Pip.'),
        ],
    ),
    dict(
        id='S16', title='Blast Off into the Star-Rift (First+Last)', seconds=8, flow_mode='first_last', prev_shot=None,
        cast=['Zara', 'Kael', 'Nyx', 'Bram', 'Jinx', 'Pip'], vehicles=['StarSkiff', 'MagBoard'],
        location='cliff', light='twilight',
        emotion='High-flying adventure launch toward the next world',
        camera='Smooth continuous camera move from the first frame to the last frame via a heroic low-angle 24mm crane-up into the starry sky',
        opening=(
            'Aboard the hovering Star-Skiff at the asteroid dock edge, Pip projects a glowing golden star-map from the '
            'dashboard while Zara grips the pilot yoke, Kael, Nyx, and Bram stand ready on deck, and Jinx hovers beside '
            'the wing on his Mag-Board.'
        ),
        closing=(
            'Heroic low-angle view as the Star-Skiff and Jinx on his Mag-Board bank upward into the starry nebula sky '
            'with blazing golden-and-cyan ion trails streaking toward a distant floating sky-citadel.'
        ),
        action=(
            'Smooth continuous camera move from the first frame to the last frame. Pip\'s golden star-map locks onto a '
            'distant floating sky-citadel; Kael and Zara pull their goggles and visor down, Zara punches the main '
            'ion-thrusters, and the Star-Skiff blasts off into the starry nebula sky with Jinx wing-surfing alongside '
            'on his Mag-Board, leaving blazing golden-and-cyan contrails. Steady, cinematic, no cut.'
        ),
        sound=(
            'A crystalline star-map lock chime, the crisp snap of goggles, and a soaring twin-engine ion-booster '
            'blast-off roar as Zara and Kael shout their launch call.'
        ),
        dialogue=[
            dict(speaker='Zara', voice='Zephyr', text='[excited] Coordinates locked on the Sky-Citadel! Hold onto your tails!'),
            dict(speaker='Kael', voice='Puck', text='[excited] Rift Runners—punch it!'),
        ],
    ),
]


def build():
    for folder in ['frames', 'clips', 'prompts', 'refs', 'voices']:
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    shots, at = [], 0.0
    for number, s in enumerate(SHOT_SPECS, 1):
        sid = s['id']
        seconds = s['seconds']
        cast = s['cast']
        vehicles = s.get('vehicles', [])
        dialogue = s.get('dialogue', [])
        location = s['location']
        light = s['light']
        flow_mode = s['flow_mode']
        identities = '; '.join(CAST[c] for c in cast)
        vehicle_desc = '; '.join(VEHICLES[v] for v in vehicles) if vehicles else 'None'
        env_sentence = f'Set on an {SETS[location]} {LIGHT[light]}'

        vehicle_clause = f' Visible space vehicles: {vehicle_desc}.' if vehicles else ''

        # Build opening still prompt
        image_prompt = (
            f'{STYLE_SENTENCE} {env_sentence} '
            f'Make ONE finished cinematic 16:9 landscape film still caught DURING movement, never a static lineup. '
            f'Visible characters ONLY: {identities}.{vehicle_clause} '
            f'Exact opening instant: {s["opening"]} Mood: {s["emotion"]}. '
            f'Accurate 8-12 adventure facial expressions, clear brow and muzzle acting, grounded athletic weight, '
            f'separated readable limbs. Camera framing: {s["camera"]}. '
            f'No lettering, subtitles, logo, watermark, collage, extra or duplicate characters.'
        )

        # Build closing still prompt if first_last mode
        closing_frame = None
        closing_image_prompt = None
        if flow_mode == 'first_last':
            closing_frame = f'frames/{sid}_end.png'
            closing_image_prompt = (
                f'{STYLE_SENTENCE} {env_sentence} '
                f'Make ONE finished cinematic 16:9 landscape film still showing the exact target ending state of the shot. '
                f'Visible characters ONLY: {identities}.{vehicle_clause} '
                f'Exact ending instant: {s["closing"]} Mood: {s["emotion"]}. '
                f'Accurate 8-12 adventure facial expressions, clear brow and muzzle acting, grounded athletic weight, '
                f'separated readable limbs. Camera framing: {s["camera"]}. '
                f'No lettering, subtitles, logo, watermark, collage, extra or duplicate characters.'
            )

        # Build spoken dialogue summary for LTX-2.5 audio layer
        spoken_clause = ''
        if dialogue:
            lines_str = ' '.join(f'{d["speaker"]} says "{d["text"]}"' for d in dialogue)
            spoken_clause = f' Spoken character dialogue: {lines_str}.'

        # Build LTX-2.5 video prompt following the official 6-layer flowing paragraph structure:
        # [Camera & Lens] + [Subject] + [Action & Timeline] + [Environment & Lighting] + [Style & Fidelity] + [Audio]
        subject_clause = f'In the frame: {identities}.'
        if vehicles:
            subject_clause += f' Vehicles in frame: {vehicle_desc}.'
        video_prompt = (
            f'{s["camera"]}. '
            f'{subject_clause} '
            f'{s["action"]} '
            f'{env_sentence} '
            f'{STYLE_SENTENCE} '
            f'Audio: {s["sound"]}{spoken_clause}'
        )

        bridge_mode = 'frames' if flow_mode == 'first_last' else 'opening'
        shot = dict(
            id=sid,
            number=number,
            title=s['title'],
            flow_mode=flow_mode,
            bridge_mode=bridge_mode,
            prev_shot=s['prev_shot'],
            extract_last_frame=bool(flow_mode == 'sequential' and s['prev_shot']),
            cast=cast,
            vehicles=vehicles,
            dialogue=dialogue,
            voice_file=f'voices/{sid}.wav',
            location=location,
            light=light,
            emotion=s['emotion'],
            duration=seconds,
            edit_seconds=seconds,
            edit_frames=seconds * 24,
            trim_start_frame=0,
            start=at,
            end=at + seconds,
            seed=2050000 + number,
            frame=f'frames/{sid}.png',
            closing_frame=closing_frame,
            clip=f'clips/{sid}.mp4',
            image_prompt=image_prompt,
            closing_image_prompt=closing_image_prompt,
            video_prompt=video_prompt,
            opening=s['opening'],
            closing=s['closing'],
            action=s['action'],
            camera=s['camera'],
            sound=s['sound'],
            audio_intent='voiced_dialogue',
            transition='one_frame_fade' if flow_mode == 'sequential' else 'hard cut',
        )
        assert 6 <= seconds <= 10
        shots.append(shot)
        (OUT / 'prompts' / f'{sid}-image.txt').write_text(image_prompt, encoding='utf-8')
        if closing_image_prompt:
            (OUT / 'prompts' / f'{sid}-end-image.txt').write_text(closing_image_prompt, encoding='utf-8')
        (OUT / 'prompts' / f'{sid}-video.txt').write_text(video_prompt, encoding='utf-8')
        at += seconds

    story = int(at)
    spec = dict(
        schema='execution_manifest.v1',
        title='Rift Runners — The Chrono-Core Heist (6-Character, Space-Vehicles, Lyria 3.5 Hip-Hop & Gemini 3.8 Voices Edition)',
        audience='8-12 years old (voiced 3D sci-fi action-adventure comedy with Lyria 3.5 hip-hop soundtrack)',
        prompt_guide='https://ltx.io/blog/ltx-2-5-prompt-guide',
        fps=24,
        total_seconds=story,
        total_frames=story * 24,
        full_episode_seconds=story,
        full_episode_frames=story * 24,
        output_width=1920,
        output_height=1080,
        score_file='rift_runners_original_score.wav',
        full_scenes_stem='Rift_Runners_Chrono_Core_Heist',
        settings=dict(
            engine='ltx',
            mode='opening',  # overridden per-shot by shot['bridge_mode'] ('opening' or 'frames')
            steps='8',
            ltx_quality='balanced',
            aspect_ratio='16:9',
            ltx_sharp_decode='true',
            ltx_calm_sampler='true',
            no_audio='false',
        ),
        cast=CAST,
        character_voices=CHARACTER_VOICES,
        vehicles=VEHICLES,
        shots=shots,
        master_filename='Rift_Runners_Chrono_Core_Heist.mp4',
        audio_policy='Every story scene whole with Gemini 3.8 TTS character dialogue, space-vehicle thruster foley, and Google Lyria 3.5 hip-hop instrumental score ducked underneath.',
        review='User visual/listening review',
    )
    (OUT / 'manifest.json').write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding='utf-8')

    def tc(t):
        return f'{int(t)//60:02d}:{int(t)%60:02d}'

    lines = [
        '# Rift Runners — The Chrono-Core Heist (6-Character, Space-Vehicles, Lyria 3.5 Hip-Hop & Gemini 3.8 Voices)', '',
        '## Expanded 6-Character Crew, Voices & Anti-Gravity Space Vehicles', '',
        f'- **Kael (Voice: `Puck`):** {CAST["Kael"]}',
        f'- **Nyx (Voice: `Kore`):** {CAST["Nyx"]}',
        f'- **Bram (Voice: `Charon`):** {CAST["Bram"]}',
        f'- **Zara (Voice: `Zephyr` — NEW):** {CAST["Zara"]}',
        f'- **Jinx (Voice: `Fenrir` — NEW):** {CAST["Jinx"]}',
        f'- **Pip (Harmonic Relic Chimes):** {CAST["Pip"]}', '',
        '### Space Vehicles & Mobility Fleet', '',
        f'- **Star-Skiff (`Aether-Runner`):** {VEHICLES["StarSkiff"]}',
        f'- **Mag-Board:** {VEHICLES["MagBoard"]}', '',
        '## Storyboard Breakdown (16 Shots · 119s)', '',
        '| Shot | Timeline | Len | Flow Mode | Cast & Vehicles | Dialogue (Gemini 3.8 TTS) | Action |',
        '| --- | --- | --- | --- | --- | --- | --- |',
    ]
    for s in shots:
        flow_badge = s['flow_mode']
        if s['extract_last_frame']:
            flow_badge = f'sequential (from {s["prev_shot"]} last frame)'
        elif s['flow_mode'] == 'first_last':
            flow_badge = f'first+last ({s["id"]}.png -> {s["id"]}_end.png)'
        cast_veh = ', '.join(s['cast'] + [f'[{v}]' for v in s.get('vehicles', [])])
        dlg_str = ' / '.join(f'**{d["speaker"]}** (`{d["voice"]}`): "{d["text"]}"' for d in s.get('dialogue', []))
        lines.append(
            f'| {s["id"]} · {s["title"]} | {tc(s["start"])}–{tc(s["end"])} | {s["duration"]}s | '
            f'`{flow_badge}` | {cast_veh} | {dlg_str} | {s["action"]} |'
        )
    Path(__file__).with_name('RIFT_RUNNERS_EP01_PLAN.md').write_text('\n'.join(lines), encoding='utf-8')

    esc = html.escape
    ref_cards = [
        ('refs/kael_sheet.png', 'Kael (Voice: Puck) — Cobalt Lynx-Fox Scout', CAST['Kael']),
        ('refs/nyx_sheet.png', 'Nyx (Voice: Kore) — Charcoal Marten Gadgeteer', CAST['Nyx']),
        ('refs/bram_sheet.png', 'Bram (Voice: Charon) — Rust Badger-Bear Heavy', CAST['Bram']),
        ('refs/zara_sheet.png', 'Zara (Voice: Zephyr · NEW) — Golden Fennec Ace Pilot', CAST['Zara']),
        ('refs/jinx_sheet.png', 'Jinx (Voice: Fenrir · NEW) — Violet Lemur Hoverboarder', CAST['Jinx']),
        ('refs/vehicles_sheet.png', 'Space Vehicles (NEW) — Star-Skiff & Mag-Board', VEHICLES['StarSkiff'] + ' | ' + VEHICLES['MagBoard']),
        ('refs/pip_and_cast_sheet.png', 'Full 6-Character Crew & Vehicles Lineup', CAST['Pip']),
        ('refs/temple_world.png', 'World Anchor — Floating Asteroid Clockwork Sky-Temple', SETS['cliff'] + '; ' + SETS['sanctum']),
    ]
    ref_html = ''.join(
        f'<article class="ref"><a href="{img}"><img src="{img}" alt="{esc(name)}"></a>'
        f'<h3>{esc(name)}</h3><p>{esc(desc)}</p></article>'
        for img, name, desc in ref_cards
    )
    cards = []
    for s in shots:
        end_img_html = ''
        if s['closing_frame']:
            end_img_html = (
                f'<div class="pair">'
                f'<div><span class="tag">First Frame ({s["id"]}.png)</span><a href="{s["frame"]}"><img src="{s["frame"]}" alt="{esc(s["title"])} start"></a></div>'
                f'<div><span class="tag">Last Frame ({s["id"]}_end.png)</span><a href="{s["closing_frame"]}"><img src="{s["closing_frame"]}" alt="{esc(s["title"])} end"></a></div>'
                f'</div>'
            )
        else:
            end_img_html = f'<a href="{s["frame"]}"><img src="{s["frame"]}" alt="{esc(s["title"])}"></a>'

        badge = s['flow_mode'].upper()
        if s['extract_last_frame']:
            badge = f'SEQUENTIAL (EXTRACT LAST FRAME FROM {s["prev_shot"]})'
        elif s['flow_mode'] == 'first_last':
            badge = 'FIRST + LAST FRAME FLOW'
        elif s['flow_mode'] == 'multishot':
            badge = 'NATIVE LTX-2.5 MULTISHOT (2 CUTS)'

        veh_str = f' · Vehicles: {", ".join(s["vehicles"])}' if s.get('vehicles') else ''
        dlg_html = ''
        if s.get('dialogue'):
            dlg_items = ''.join(
                f'<div style="margin:4px 0;font-size:13px"><strong style="color:#93c5fd">{esc(d["speaker"])} ({esc(d["voice"])}):</strong> {esc(d["text"])}</div>'
                for d in s['dialogue']
            )
            dlg_html = (
                f'<div style="margin:10px 0;padding:10px 12px;background:#0f172a;border-radius:10px;border:1px solid #1e293b">'
                f'<div style="font-size:11px;color:#38bdf8;font-weight:700;margin-bottom:4px">🎙️ GEMINI 3.8 FLASH TTS DIALOGUE ({s["id"]}.wav)</div>'
                f'{dlg_items}'
                f'<audio controls preload="none" src="{s["voice_file"]}" style="width:100%;height:32px;margin-top:6px"></audio>'
                f'</div>'
            )

        cards.append(
            f'<article>{end_img_html}'
            f'<div class="badge">{esc(badge)}</div>'
            f'<h2>{s["id"]} · {esc(s["title"])}</h2>'
            f'<p class="meta">{s["start"]:g}–{s["end"]:g}s · {s["duration"]}s · Cast: {esc(", ".join(s["cast"]))}{esc(veh_str)} · <em>{esc(s["emotion"])}</em></p>'
            f'{dlg_html}'
            f'<p>{esc(s["action"])}</p><details><summary>LTX-2.5 Camera, Sound & Full Prompt</summary>'
            f'<p><strong>Camera:</strong> {esc(s["camera"])}</p><p><strong>Sound:</strong> {esc(s["sound"])}</p>'
            f'<p><strong>LTX-2.5 Video Prompt:</strong> {esc(s["video_prompt"])}</p></details></article>'
        )
    doc = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Rift Runners — 6-Character, Space-Vehicles, Lyria 3.5 Hip-Hop & Gemini 3.8 Voices</title>'
        '<style>body{margin:0;background:#0b0f19;color:#eef2ff;font:15px/1.55 system-ui}header,section.refs{max-width:1680px;margin:auto;padding:24px}'
        '.ref-grid,main{max-width:1680px;margin:auto;padding:24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:24px}'
        'article{background:#151c2c;padding:16px;border-radius:18px;border:1px solid #26324d}'
        'article.ref{background:#1a2338;border-color:#3b4f78}'
        'img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;background:#090c14}'
        '.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}'
        '.tag{display:block;font-size:11px;color:#9fb0d9;margin-bottom:4px;font-weight:600}'
        '.badge{display:inline-block;margin-top:10px;padding:3px 9px;border-radius:99px;background:#253559;color:#8ec5ff;font-size:11px;font-weight:700;letter-spacing:.04em}'
        'h1{font-size:28px;margin:0 0 8px}h2,h3{font-size:19px;margin:8px 0 4px}'
        '.meta{color:#9fb0d9;font-size:13px}details p{font-size:13px}a{color:#7cc0ff}</style>'
        '<header><h1>Rift Runners — The Chrono-Core Heist (6-Character, Space-Vehicles, Lyria 3.5 Hip-Hop &amp; Gemini 3.8 Voices)</h1>'
        '<p>Expanded 5-hero + Pip squad (<strong>Kael [Puck], Nyx [Kore], Bram [Charon], Zara [Zephyr], Jinx [Fenrir], Pip</strong>) '
        'with high-speed anti-gravity space vehicles (<strong>The Star-Skiff</strong> &amp; <strong>Jinx\'s Mag-Board</strong>), '
        'studio <strong>Google Lyria 3.5 Hip-Hop Beat</strong>, and <strong>Google Gemini 3.8 Flash TTS</strong> multi-speaker character dialogue.</p>'
        '<div style="margin-top:14px;padding:12px 16px;background:#1a2338;border-radius:12px;display:flex;flex-wrap:wrap;gap:14px;align-items:center">'
        '<strong>🎤 Google Lyria 3.5 Hip-Hop Adventure Soundtrack:</strong>'
        '<audio controls preload="metadata" src="rift_runners_original_score.wav"></audio>'
        '<a href="storyboard.html" style="padding:8px 14px;border-radius:8px;background:#3b82f6;color:#fff;font-weight:700;text-decoration:none">Refresh Page</a>'
        '</div></header>'
        '<section class="refs"><h2>Character, Space-Vehicle & World Reference Sheets (8 Sheets)</h2><div class="ref-grid">' + ref_html + '</div></section>'
        '<main>' + ''.join(cards) + '</main></html>'
    )
    (OUT / 'storyboard.html').write_text(doc, encoding='utf-8')
    print(json.dumps(dict(shots=len(shots), story_seconds=story, cast=list(CAST.keys()), vehicles=list(VEHICLES.keys()))))


if __name__ == '__main__':
    build()
