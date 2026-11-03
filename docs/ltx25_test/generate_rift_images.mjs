import { spawnSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { homedir } from 'os';

const MORPHEUS_DIR = join(homedir(), 'Downloads', 'chatcut-standalone-complete', 'chatcut-standalone-complete');
const IMG_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'image-generate.mjs');
const STATE_DIR = 'D:/repository/state/rift_runners_ep01';
const DIST_DIR = 'D:/repository/dist/rift-runners';
const REFS_DIR = join(STATE_DIR, 'refs');
const FRAMES_DIR = join(STATE_DIR, 'frames');

// Load CREDENTIALS.env into process.env so child scripts inherit it
for (const line of readFileSync(join(MORPHEUS_DIR, 'CREDENTIALS.env'), 'utf-8').split('\n')) {
  const t = line.trim();
  if (!t || t.startsWith('#') || !t.includes('=')) continue;
  const idx = t.indexOf('=');
  const k = t.slice(0, idx).replace(/^export\s+/, '').trim();
  let v = t.slice(idx + 1).trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
  process.env[k] = v;
}

function syncDist() {
  try {
    spawnSync('robocopy', [STATE_DIR, DIST_DIR, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'], { stdio: 'ignore' });
  } catch {}
}

function genImage(prompt, outPath, refPaths = []) {
  const validRefs = refPaths.filter(p => p && existsSync(p));
  const args = [
    IMG_SCRIPT,
    prompt,
    '--model', 'nano-banana-2',
    '--aspect', '16:9',
    '--resolution', '1K',
    '--output', outPath,
  ];
  if (validRefs.length > 0) {
    args.push('--image', ...validRefs);
  }
  console.log(`\n>>> Generating ${outPath} (refs: ${validRefs.length}) <<<`);
  const res = spawnSync(process.execPath, args, {
    cwd: MORPHEUS_DIR,
    env: process.env,
    stdio: 'inherit',
  });
  if (res.status === 0 && existsSync(outPath)) {
    syncDist();
    return true;
  }
  console.error(`WARN: Failed on ${outPath}, retrying once...`);
  const retry = spawnSync(process.execPath, args, {
    cwd: MORPHEUS_DIR,
    env: process.env,
    stdio: 'inherit',
  });
  syncDist();
  return retry.status === 0;
}

const manifest = JSON.parse(readFileSync(join(STATE_DIR, 'manifest.json'), 'utf-8'));
const CAST = manifest.cast;
const VEHICLES = manifest.vehicles;

const kaelRef = join(REFS_DIR, 'kael_sheet.png');
const nyxRef = join(REFS_DIR, 'nyx_sheet.png');
const bramRef = join(REFS_DIR, 'bram_sheet.png');
const zaraRef = join(REFS_DIR, 'zara_sheet.png');
const jinxRef = join(REFS_DIR, 'jinx_sheet.png');
const vehRef = join(REFS_DIR, 'vehicles_sheet.png');
const castRef = join(REFS_DIR, 'pip_and_cast_sheet.png');
const worldRef = join(REFS_DIR, 'temple_world.png');

if (process.argv.includes('--fix-s03')) {
  genImage(
    `High-end 3D animated sci-fi adventure film still, dynamic low-angle medium tracking shot in 16:9 matching the reference cast sheet and temple bridge environment. On the ancient floating stone bridge, show EXACTLY FIVE characters total (NEVER duplicate Kael—Kael appears ONLY ONCE in the foreground and is NOT inside the Star-Skiff): in the foreground on the stone bridge, cobalt-blue lynx-fox Kael (in rusty-orange vest with his bushy blue white-tipped tail) leaps back off a sinking glowing cyan stone tile while purple ring-tailed lemur Jinx (with purple-and-white striped tail and bronze goggles) banks sharply beside him on his glowing cyan Mag-Board hoverboard as glowing cyan energy-darts fire across the bridge. Immediately behind them in the midground, the hovering Star-Skiff space speeder carries ONLY THREE characters inside its open cockpit: golden fennec-fox pilot Zara at the wheel, charcoal-black marten Nyx beside her, and large rust-red badger-bear Bram in the back seat. No duplicate characters, no text, no watermarks.`,
    join(FRAMES_DIR, 'S03.png'),
    [castRef, worldRef]
  );
  syncDist();
  process.exit(0);
}

if (process.argv.includes('--fix-defects')) {
  const s01 = join(FRAMES_DIR, 'S01.png');
  const s04 = join(FRAMES_DIR, 'S04.png');
  const s07 = join(FRAMES_DIR, 'S07.png');
  const s10 = join(FRAMES_DIR, 'S10.png');
  const s12 = join(FRAMES_DIR, 'S12.png');

  const fixes = [
    {
      out: join(FRAMES_DIR, 'S02.png'),
      refs: [castRef, s01, worldRef],
      prompt: `High-end 3D animated sci-fi adventure film still, wide 16:9 composition matching the reference cast sheet and S01 scene. At the mossy stone bridge threshold, show EXACTLY FIVE distinct anthropomorphic animal heroes (NEVER duplicate any character): on the left inside the hovering brass-and-cobalt Star-Skiff space speeder sit golden fennec-fox pilot Zara (with cyan holographic visor and white-and-tangerine jacket) and large rust-red badger-bear Bram (in olive armor vest). In the center foreground, purple ring-tailed lemur Jinx (with purple-and-white striped tail and bronze magnifying goggles) hovers low on his glowing cyan Mag-Board while cobalt-blue lynx-fox Kael (in rusty-orange flight vest) steps cautiously onto the front of Jinx's Mag-Board, and charcoal-black marten Nyx (in teal tech-vest with violet ear tufts) kneels beside them pointing warningly at a glowing cyan pressure-plate rune on the stone bridge. No duplicate characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S03.png'),
      refs: [castRef, s01, worldRef],
      prompt: `High-end 3D animated sci-fi adventure film still, dynamic low-angle medium tracking shot in 16:9 matching the reference cast sheet. On the ancient floating stone bridge, show EXACTLY FIVE distinct characters (NEVER duplicate any character): in the foreground, cobalt-blue lynx-fox Kael (in rusty-orange vest with his bushy blue white-tipped tail) leaps back off a sinking glowing cyan stone tile while purple ring-tailed lemur Jinx (with purple-and-white striped tail and bronze goggles) banks sharply beside him on his glowing cyan Mag-Board hoverboard as glowing cyan energy-darts fire across the bridge. Immediately behind them in the midground, golden fennec-fox Zara pilots the hovering Star-Skiff space speeder with charcoal-black marten Nyx and large rust-red badger-bear Bram bracing inside the open cockpit. No duplicate characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S04_end.png'),
      refs: [s04, castRef],
      prompt: `High-end 3D animated sci-fi adventure film still, wide 16:9 action shot matching the opening frame S04 and cast sheet. Show EXACTLY FIVE distinct animal heroes (ONLY ONE of each character—do NOT draw two Nyxes or two Kaels): the hovering brass-and-cobalt Star-Skiff space speeder banks smoothly above the crumbling stone bridge gap. Inside the Star-Skiff: golden fennec-fox Zara steers at the front pilot controls, large rust-red badger-bear Bram braces in the passenger bay, charcoal-black marten Nyx stands in the center retracting her glowing cyan wrist-gauntlet tether, and cobalt-blue lynx-fox Kael sits safely sprawled on the rear deck of the Star-Skiff grinning with relief. Flying right alongside the Star-Skiff on his glowing cyan Mag-Board is purple ring-tailed lemur Jinx. Nobody is left on the bridge. No duplicate characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S05.png'),
      refs: [castRef, worldRef],
      prompt: `High-end 3D animated sci-fi adventure film still, low-angle wide 16:9 shot at the towering stone temple entrance archway with glowing cyan circuitry. Show EXACTLY FIVE distinct animal heroes (ONLY ONE Kael, ONE Nyx, ONE Bram, ONE Zara, ONE Jinx—never duplicate any character and keep tails distinct): massive rust-red badger-bear Bram braces his armored shoulder and glowing brass gauntlet under the left side of the descending heavy stone temple gate to hold it open, while golden fennec-fox Zara wedges the reinforced prow of the hovering Star-Skiff under the right side of the gate. Darting through the narrowing gap under the stone door in the center are ONE cobalt-blue lynx-fox Kael (bushy blue tail), ONE charcoal-black marten Nyx (sleek black tail), and ONE purple ring-tailed lemur Jinx (purple-and-white striped ring-tail) riding his glowing cyan Mag-Board. No duplicate characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S06.png'),
      refs: [castRef, worldRef],
      prompt: `High-end 3D animated sci-fi adventure film still, medium close-up 16:9 inside the glowing cyan temple sanctum looking back toward the low narrow gap under the heavy stone door. Show EXACTLY FIVE distinct animal heroes with their proper heads and species (NEVER blend characters or add extra heads): in the foreground kneeling on the floor, ONE cobalt-blue lynx-fox Kael, ONE charcoal-black marten Nyx (sleek charcoal fur and violet ear tufts), and ONE purple ring-tailed lemur Jinx (amethyst-purple fur, bronze goggles, striped ring-tail) wedge a heavy brass gear-brace and the glowing Mag-Board under the stone slab, while large rust-red badger-bear Bram and golden fennec-fox Zara duck safely through the gap into the sanctum behind them. No duplicate characters, no mutated heads, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S08.png'),
      refs: [s07, castRef],
      prompt: `High-end 3D animated sci-fi adventure film still, medium 16:9 composition inside the glowing temple sanctum matching the exact 5-character arrangement of the reference frame S07. Around the stone altar pedestal where Pip (the small floating octahedral amber-gold clockwork-crystal relic with two glowing cyan shutter-eyes) hovers inside spinning golden rings, show EXACTLY FIVE animal heroes (no 6th animal on the left!): charcoal-black marten Nyx holds up a resonant brass tuning fork emitting soft cyan sound-waves toward Pip; purple ring-tailed lemur Jinx kneels on the right tuning his Mag-Board's repulsor frequency; and cobalt-blue lynx-fox Kael, large rust-red badger-bear Bram, and golden fennec-fox Zara watch in quiet awe. No extra characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S08_end.png'),
      refs: [s07, castRef],
      prompt: `High-end 3D animated sci-fi adventure film still, medium 16:9 composition inside the glowing temple sanctum matching the exact 5-character arrangement of the reference frame S07. The golden containment rings around the stone pedestal have dissolved, and Pip (the small floating octahedral amber-gold clockwork-crystal relic with two happy glowing cyan shutter-eyes) hovers peacefully just above charcoal-black marten Nyx's open palm. Around them stand ONLY the other four animal teammates (ONE cobalt-blue lynx-fox Kael, ONE large rust-red badger-bear Bram, ONE golden fennec-fox Zara, and ONE purple ring-tailed lemur Jinx giving an excited thumbs-up). Exactly 5 animal heroes + floating Pip total. No duplicate characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S11.png'),
      refs: [s10, castRef],
      prompt: `High-end 3D animated sci-fi adventure film still, dramatic wide side-profile 16:9 action shot across the chasm between the shattering stone bridge (left) and the mossy asteroid landing dock (right), matching reference S10 and the cast sheet. Show EXACTLY FIVE animal heroes + floating amber Pip (NEVER duplicate Kael or omit Nyx): golden fennec-fox Zara launches the Star-Skiff space speeder nose-up off the crumbling bridge edge with large rust-red badger-bear Bram, ONE cobalt-blue lynx-fox Kael, and ONE charcoal-black marten Nyx bracing aboard, while purple ring-tailed lemur Jinx boosts high alongside them on his glowing cyan Mag-Board and amber-gold octahedral Pip trails golden sparks above them. No duplicate characters, no text, no watermarks.`
    },
    {
      out: join(FRAMES_DIR, 'S11_end.png'),
      refs: [s12, castRef],
      prompt: `High-end 3D animated sci-fi adventure film still, dramatic 16:9 cliffhanger shot at the mossy asteroid cliff lip, matching reference frame S12 and the cast sheet. Show EXACTLY FIVE distinct animal heroes + floating amber Pip (keep Kael's blue tail and Jinx's purple-and-white striped lemur tail on their respective characters!): on the upper mossy stone cliff dock stand ONE cobalt-blue lynx-fox Kael, ONE charcoal-black marten Nyx, and ONE purple ring-tailed lemur Jinx (with his Mag-Board clamped to the stone), all gripping a taut glowing cyan grapple-tether anchored to the nose of the Star-Skiff space speeder hanging over the cliff edge below, where golden fennec-fox Zara and large rust-red badger-bear Bram brace inside the cockpit and glowing amber Pip hovers overhead. No duplicate characters, no text, no watermarks.`
    }
  ];

  for (const item of fixes) {
    genImage(item.prompt, item.out, item.refs);
  }
  console.log('\n=== 9 DEFECTIVE FRAMES REGENERATED & SYNCED! ===');
  syncDist();
  process.exit(0);
}

// 1. Generate the 4 new/updated reference sheets
genImage(
  `Character turnaround reference sheet in the exact same 3D animated sci-fi adventure film style as the reference image. Show ONLY ONE character in 3 full-body views (front view, 3/4 action pose, side profile) on a clean neutral studio backdrop: ${CAST.Zara}. Crisp groomed golden-and-cream fur, tall black-tipped fennec ears, glowing turquoise holographic flight visor, white-and-tangerine cropped flight jacket with brass buckles, padded pilot gloves. No text, no labels, no watermarks.`,
  zaraRef,
  [kaelRef]
);

genImage(
  `Character turnaround reference sheet in the exact same 3D animated sci-fi adventure film style as the reference image. Show ONLY ONE character in 3 full-body views (front view, 3/4 action pose, side profile) on a clean neutral studio backdrop: ${CAST.Jinx}. Tactile amethyst-violet and pearl-white fur, long striped purple-and-white ring tail, bright golden eyes, oversized bronze magnifying goggles, and a teal tool-bandolier. No text, no labels, no watermarks.`,
  jinxRef,
  [kaelRef]
);

genImage(
  `Sci-fi vehicle design reference sheet in the exact same 3D animated adventure film style as the reference environment. Show two distinct anti-gravity space vehicles side by side on a clean studio dock backdrop: on the left, ${VEHICLES.StarSkiff}; on the right, ${VEHICLES.MagBoard}. Brushed brass, cobalt-blue hull plates, weathered steel, glowing cyan repulsor rings and neon-cyan plasma jets. No characters, no text, no labels, no watermarks.`,
  vehRef,
  [worldRef]
);

genImage(
  `Full 6-character and space-vehicles ensemble lineup reference sheet in the exact same 3D animated sci-fi adventure film style as the reference sheets. Show all five anthropomorphic animal heroes (${CAST.Kael}; ${CAST.Nyx}; ${CAST.Bram}; ${CAST.Zara}; ${CAST.Jinx}) plus floating golden ${CAST.Pip}, posed heroically together around ${VEHICLES.StarSkiff} and ${VEHICLES.MagBoard} on the mossy asteroid landing dock. No text, no labels, no watermarks.`,
  castRef,
  [kaelRef, nyxRef, bramRef, zaraRef, jinxRef, vehRef, worldRef]
);

// 2. Generate all 16 storyboard opening frames + 4 closing frames
const charRefMap = {
  Kael: kaelRef,
  Nyx: nyxRef,
  Bram: bramRef,
  Zara: zaraRef,
  Jinx: jinxRef,
  Pip: castRef,
};

for (const shot of manifest.shots) {
  const sid = shot.id;
  const refs = [worldRef];
  for (const c of shot.cast) {
    if (charRefMap[c] && !refs.includes(charRefMap[c])) refs.push(charRefMap[c]);
  }
  if (shot.vehicles && shot.vehicles.length > 0) {
    refs.push(vehRef);
  }
  const startOut = join(STATE_DIR, shot.frame);
  genImage(
    `Match the exact character designs, fur colors, outfits, and space vehicle designs from the provided reference sheets. ${shot.image_prompt}`,
    startOut,
    refs
  );

  if (shot.closing_frame && shot.closing_image_prompt) {
    const endOut = join(STATE_DIR, shot.closing_frame);
    genImage(
      `Match the exact character designs, fur colors, outfits, space vehicle designs, and scene continuity from the provided reference sheets and opening frame. ${shot.closing_image_prompt}`,
      endOut,
      [startOut, ...refs]
    );
  }
}

console.log('\n=== ALL REFERENCE SHEETS & 16 STORYBOARD FRAMES GENERATED & SYNCED! ===');
syncDist();
