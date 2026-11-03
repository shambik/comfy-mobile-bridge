import { spawnSync, execFileSync } from 'child_process';
import { readFileSync, writeFileSync, existsSync, mkdirSync, copyFileSync } from 'fs';
import { join } from 'path';

const MORPHEUS_DIR = 'C:/Users/David Shambik/Downloads/chatcut-standalone-complete/chatcut-standalone-complete';
const IMG_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'image-generate.mjs');
const TTS_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'gemini-tts.mjs');

const STATE_DIR = 'D:/repository/state/rift_runners_ep01';
const PILOT_DIR = join(STATE_DIR, 'v2_pilot');
const REFS_DIR = join(STATE_DIR, 'refs');
const V1_FRAMES_DIR = join(STATE_DIR, 'frames');
const FRAMES_DIR = join(PILOT_DIR, 'frames');
const VOICES_DIR = join(PILOT_DIR, 'voices');
const CLIPS_DIR = join(PILOT_DIR, 'clips');
const DIST_DIR = 'D:/repository/ui/dist/rift-runners';

for (const d of [PILOT_DIR, FRAMES_DIR, VOICES_DIR, CLIPS_DIR]) {
  mkdirSync(d, { recursive: true });
}

// Load CREDENTIALS.env
for (const line of readFileSync(join(MORPHEUS_DIR, 'CREDENTIALS.env'), 'utf-8').split('\n')) {
  const t = line.trim();
  if (!t || t.startsWith('#') || !t.includes('=')) continue;
  const idx = t.indexOf('=');
  const k = t.slice(0, idx).replace(/^export\s+/, '').trim();
  let v = t.slice(idx + 1).trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
  process.env[k] = v;
}

const kaelRef = join(REFS_DIR, 'kael_sheet.png');
const nyxRef = join(REFS_DIR, 'nyx_sheet.png');
const bramRef = join(REFS_DIR, 'bram_sheet.png');
const zaraRef = join(REFS_DIR, 'zara_sheet.png');
const jinxRef = join(REFS_DIR, 'jinx_sheet.png');
const vehRef = join(REFS_DIR, 'vehicles_sheet.png');
const worldRef = join(REFS_DIR, 'temple_world.png');

const PILOT_SHOTS = [
  {
    id: 'A01',
    title: 'Star-Skiff Touchdown (Wide Action)',
    mode: 'opening',
    duration: 5,
    seed: 2200001,
    cast: ['Zara', 'Kael', 'Nyx', 'Bram', 'Jinx'],
    speaker: null,
    voice: null,
    dialogue_text: null,
    reuse_v1_frame: 'S01.png',
    refs: [],
    image_prompt: 'Reused verified S01.png wide opening frame.',
    video_prompt:
      'A steady low-angle 35mm tracking shot glides gently from left to right. The brass-and-cobalt Star-Skiff settles into a calm low hover above the mossy asteroid dock with glowing cyan repulsor rings underneath; golden fennec-fox Zara steers at the yoke while cobalt-blue lynx-fox Kael, charcoal-black marten Nyx, and rust-red badger-bear Bram brace on deck, and purple ring-tailed lemur Jinx glides smoothly alongside on his cyan Mag-Board. Starry teal-violet nebula sky and clockwork temple pillars behind them; warm golden dusk rim light. Same character designs as the first frame throughout; no new or duplicate characters; no cut. Nobody speaks; all mouths stay closed. Sound: deep anti-gravity thruster hum and gentle hoverboard whir; no voices, no speech, no music.',
  },
  {
    id: 'A02',
    title: 'Zara Cockpit Callout (OTS Lip-Sync)',
    mode: 'lip_sync',
    duration: 4,
    seed: 2200002,
    cast: ['Zara'],
    speaker: 'Zara',
    voice: 'Zephyr',
    style_prompt: 'Say cheerfully and energetically like an ace pilot:',
    dialogue_text: 'Touchdown on the sky-dock! Keep the skiff warm, crew!',
    reuse_v1_frame: null,
    refs: [zaraRef, vehRef, worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Medium close-up of golden fennec-fox pilot Zara sitting at the brass pilot yoke of the open-cockpit Star-Skiff, matching the Zara reference sheet: sunburst-gold and warm-cream fur, tall expressive black-tipped fennec ears, luminous turquoise holographic flight visor resting over her brow, and white-and-tangerine cropped flight jacket with brass buckles. She faces three-quarters toward the camera with a cheerful, confident smile, mouth naturally closed. In the lower-right foreground corner, show ONLY the out-of-focus back of rust-red badger-bear Bram\'s armored shoulder (over-the-shoulder framing, Bram\'s face completely unseen). Starry teal-violet nebula sky and clockwork temple pillars softly blurred in the background, warm golden-hour rim light. Only Zara\'s face is visible. No text, no watermarks.',
    video_prompt:
      'Static over-the-shoulder medium close-up, locked camera. Golden fennec-fox pilot Zara with tall black-tipped ears, turquoise holographic visor, and white-and-tangerine flight jacket fills the center frame at the Star-Skiff controls, with only the out-of-focus back of a shoulder in the corner and starry teal-violet nebula sky behind. Zara is the only visible face and the only one speaking: clear jaw, lip, and muzzle movement synced to the uploaded voice, cheerful grin, subtle natural ear and head movement. No other faces, no camera move, no cut, no text.',
  },
  {
    id: 'A03',
    title: 'Kael Leads the Charge (Solo CU Lip-Sync)',
    mode: 'lip_sync',
    duration: 4,
    seed: 2200003,
    cast: ['Kael'],
    speaker: 'Kael',
    voice: 'Puck',
    style_prompt: 'Say eagerly and confidently like a young adventure hero:',
    dialogue_text: 'Chrono-Core, here we come! Follow my lead!',
    reuse_v1_frame: null,
    refs: [kaelRef, worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Solo medium close-up of cobalt-blue and slate-white lynx-fox scout Kael matching the Kael reference sheet: pointed tufted ears, sharp amber-gold eyes, expressive dark eyebrows, brass aviator goggles resting on his forehead, weathered copper-brown leather vest, and fingerless climbing gloves. Kael stands alone on the mossy asteroid dock in warm golden dusk rim light, facing three-quarters toward the camera with an eager, confident grin (mouth naturally closed), one gloved thumb gesturing toward the ancient clockwork sky-temple softly blurred against the starry teal-violet nebula behind him. ONLY Kael is in the frame—no other characters anywhere. No text, no watermarks.',
    video_prompt:
      'Static medium close-up, locked camera. Cobalt-blue and slate-white lynx-fox Kael with pointed tufted ears, amber-gold eyes, brass goggles on his forehead, and brown leather vest fills the frame on the mossy asteroid dock, with the clockwork sky-temple softly out of focus against a starry teal-violet nebula sky. Kael is the only character in the shot and the only one speaking: clear jaw and lip movement synced to the uploaded voice, confident grin, expressive brow lift, and a small nod. No other characters, no camera move, no cut, no text.',
  },
  {
    id: 'A04',
    title: 'Bridge Threshold Inspection (Wide Action)',
    mode: 'opening',
    duration: 5,
    seed: 2200004,
    cast: ['Kael', 'Jinx', 'Nyx', 'Zara', 'Bram'],
    speaker: null,
    voice: null,
    dialogue_text: null,
    reuse_v1_frame: 'S02.png',
    refs: [],
    image_prompt: 'Reused verified S02.png wide frame at the bridge threshold.',
    video_prompt:
      'A slow, steady 35mm medium-wide shot at the ancient stone bridge threshold over a starry teal-violet nebula chasm. In the foreground, charcoal-black marten Nyx kneels and points one gloved hand toward a glowing cyan rune tile on the stone bridge while cobalt-blue lynx-fox Kael rests one boot on purple ring-tailed lemur Jinx\'s hovering cyan Mag-Board; behind them, golden fennec-fox Zara and rust-red badger-bear Bram watch calmly from the hovering Star-Skiff. Warm golden dusk light. Same character designs as the first frame throughout; no new or duplicate characters; no cut. Nobody speaks; all mouths stay closed. Sound: low stone bridge wind and soft cyan repulsor hum; no voices, no speech, no music.',
  },
  {
    id: 'A05',
    title: 'Nyx Pressure-Trap Warning (OTS CU Lip-Sync)',
    mode: 'lip_sync',
    duration: 4,
    seed: 2200005,
    cast: ['Nyx'],
    speaker: 'Nyx',
    voice: 'Kore',
    style_prompt: 'Say cautiously and urgently as a smart gadgeteer warning a friend:',
    dialogue_text: 'Hold up, Kael! Those stone tiles are a pressure trap!',
    reuse_v1_frame: null,
    refs: [nyxRef, worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Over-the-shoulder medium close-up of sleek charcoal-black and silver-grey marten gadgeteer Nyx matching the Nyx reference sheet: violet-tipped ear tufts, sharp emerald-green eyes, tan canvas crossbody satchel strap, and glowing cyan crystal wrist-grappler gauntlet on her raised left forearm. She looks urgently toward camera-right with furrowed brows and mouth naturally closed. On the far right edge in soft foreground blur is ONLY the back of Kael\'s cobalt-blue ear and brown vest shoulder (Kael\'s face is completely unseen, turned away). Ancient carved stone bridge pillars and starry teal-violet nebula sky softly blurred in the background. Only Nyx\'s face is visible. No text, no watermarks.',
    video_prompt:
      'Static over-the-shoulder medium close-up, locked camera. Sleek charcoal-black marten Nyx with violet-tipped ear tufts, emerald-green eyes, and a glowing cyan wrist-gauntlet fills the frame, seen past an out-of-focus shoulder on the right edge against carved stone bridge pillars and a starry nebula sky. Nyx is the only visible face and the only one speaking: clear jaw and lip movement synced to the uploaded voice, urgent furrowed brow, and subtle hand gesture. No other faces, no camera move, no cut, no text.',
  },
  {
    id: 'A06',
    title: 'Jinx Mag-Board Boast (Solo CU Lip-Sync)',
    mode: 'lip_sync',
    duration: 4,
    seed: 2200006,
    cast: ['Jinx'],
    speaker: 'Jinx',
    voice: 'Fenrir',
    style_prompt: 'Say mischievously and playfully:',
    dialogue_text: 'Good thing my Mag-Board floats! Hop on!',
    reuse_v1_frame: null,
    refs: [jinxRef, vehRef, worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Solo medium close-up of nimble amethyst-violet and pearl-white ring-tailed lemur Jinx matching the Jinx reference sheet: unmistakable ring-tailed lemur facial markings with white eye-rings and dark snout, bright golden eyes, oversized bronze magnifying goggles pushed up on his forehead, teal tool-bandolier across his chest, and his long purple-and-white striped lemur tail curving up behind him. Jinx crouches playfully on his glowing cyan Mag-Board hoverboard with a mischievous smirk (mouth naturally closed). Starry teal-violet nebula chasm and carved stone bridge softly blurred behind him. ONLY Jinx is in the frame—no other characters. No text, no watermarks.',
    video_prompt:
      'Static medium close-up, locked camera. Purple-and-white ring-tailed lemur Jinx with bright golden eyes, oversized bronze goggles on his forehead, teal tool-bandolier, and striped lemur tail fills the frame balanced on his glowing cyan Mag-Board against the stone sky-bridge and starry nebula chasm. Jinx is the only character in the shot and the only one speaking: clear jaw and lip movement synced to the uploaded voice, mischievous grin, and playful eyebrow raise. No other characters, no camera move, no cut, no text.',
  },
  {
    id: 'A07',
    title: 'The Sinking Pressure Tile (Insert Action)',
    mode: 'opening',
    duration: 3,
    seed: 2200007,
    cast: [],
    speaker: null,
    voice: null,
    dialogue_text: null,
    reuse_v1_frame: null,
    refs: [worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Low-angle macro insert close-up on the floor of an ancient stone sky-bridge: a weathered brown leather boot steps onto a square carved stone pressure-plate tile inlaid with concentric brass clockwork gears and glowing cyan circuit runes; the tile is depressing slightly into the stone floor while small recessed brass dart-ports begin sliding open in the stone side parapet wall. Warm golden dusk light and bright cyan rune glow. Show ONLY the boot and the stone pressure tile mechanism—NO faces and NO full characters in frame. No text, no watermarks.',
    video_prompt:
      'A steady low-angle 50mm insert close-up on the ancient stone bridge floor. A brown leather boot presses down on a carved stone pressure tile; the tile sinks half an inch with a bright pulse of cyan runes as inlaid brass clockwork gears turn and recessed brass turret ports slide open in the stone wall. Warm golden dusk light and cyan rune glow. No faces in frame, no camera cut. Nobody speaks. Sound: heavy stone click, metallic clockwork gears ratcheting, and an energy charge hum; no voices, no speech, no music.',
  },
  {
    id: 'A08',
    title: 'Dodging the Ion-Darts (Wide Action)',
    mode: 'opening',
    duration: 5,
    seed: 2200008,
    cast: ['Kael', 'Jinx', 'Zara', 'Nyx', 'Bram'],
    speaker: null,
    voice: null,
    dialogue_text: null,
    reuse_v1_frame: 'S03.png',
    refs: [],
    image_prompt: 'Reused verified S03.png wide bridge trap frame.',
    video_prompt:
      'A steady medium-wide 35mm tracking shot on the ancient stone sky-bridge over a starry nebula chasm. In the foreground, cobalt-blue lynx-fox Kael hops back from the glowing cyan floor tile while purple ring-tailed lemur Jinx banks gently beside him on his cyan Mag-Board as bright cyan energy-darts streak past; behind them, golden fennec-fox Zara, charcoal-black marten Nyx, and rust-red badger-bear Bram watch from the hovering Star-Skiff. Same character designs as the first frame throughout; no new or duplicate characters; no cut. Nobody speaks; all mouths stay closed. Sound: sharp laser-dart zaps, hoverboard bank whoosh, and deep thruster hum; no voices, no speech, no music.',
  },
  {
    id: 'A09',
    title: 'Kael Wide-Eyed Panic (Solo CU Lip-Sync)',
    mode: 'lip_sync',
    duration: 4,
    seed: 2200009,
    cast: ['Kael'],
    speaker: 'Kael',
    voice: 'Puck',
    style_prompt: 'Say with surprised comedic panic:',
    dialogue_text: 'Uh-oh! Okay, Nyx was right—the floor is angry!',
    reuse_v1_frame: null,
    refs: [kaelRef, worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Solo close-up of cobalt-blue and slate-white lynx-fox scout Kael matching the Kael reference sheet: pointed tufted ears pinned back in comedic alarm, wide amber-gold eyes, expressive raised dark eyebrows, brass aviator goggles slightly askew on his forehead, and copper-brown leather vest. Soft glowing cyan energy-dart streaks and the stone sky-bridge over a starry teal-violet nebula chasm are blurred in the background. Kael\'s mouth is closed in a startled gulp. ONLY Kael is in the frame—no other characters. No text, no watermarks.',
    video_prompt:
      'Static close-up, locked camera. Cobalt-blue and slate-white lynx-fox Kael with wide amber-gold eyes, tufted ears, and brass goggles on his forehead fills the frame on the stone bridge with soft cyan energy-glow and starry nebula sky behind him. Kael is the only character in the shot and the only one speaking: clear jaw and lip movement synced to the uploaded voice, wide-eyed alarmed expression, and expressive ear twitch. No other characters, no camera move, no cut, no text.',
  },
  {
    id: 'A10',
    title: 'Nyx Fires the Grappler (Solo CU Lip-Sync)',
    mode: 'lip_sync',
    duration: 4,
    seed: 2200010,
    cast: ['Nyx'],
    speaker: 'Nyx',
    voice: 'Kore',
    style_prompt: 'Say decisively and urgently like an action hero:',
    dialogue_text: 'Grappler locked! Grab the line, Kael!',
    reuse_v1_frame: null,
    refs: [nyxRef, worldRef],
    image_prompt:
      'High-end 3D animated sci-fi adventure film still in 16:9. Solo medium close-up of sleek charcoal-black and silver-grey marten gadgeteer Nyx matching the Nyx reference sheet: violet-tipped ear tufts, sharp emerald-green eyes, tan canvas crossbody satchel strap, leaning over the brushed-brass rail of the hovering Star-Skiff with her left forearm extended toward camera-left, her cyan crystal wrist-grappler gauntlet glowing brightly with an energy beam. Focused, determined expression with mouth naturally closed. Starry teal-violet nebula sky and golden dusk rim light behind her. ONLY Nyx is in the frame—no other characters. No text, no watermarks.',
    video_prompt:
      'Static medium close-up, locked camera. Sleek charcoal-black marten Nyx with violet-tipped ear tufts and sharp emerald-green eyes leans at the brass Star-Skiff rail with her glowing cyan crystal wrist-gauntlet raised in the foreground against a starry teal-violet nebula sky. Nyx is the only character in the shot and the only one speaking: clear jaw and lip movement synced to the uploaded voice, focused determined expression, gauntlet crystal pulsing softly. No other characters, no camera move, no cut, no text.',
  },
];

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
  console.log(`\n>>> Generating Frame ${outPath} (refs: ${validRefs.length}) <<<`);
  const res = spawnSync(process.execPath, args, {
    cwd: MORPHEUS_DIR,
    env: process.env,
    stdio: 'inherit',
  });
  return res.status === 0 && existsSync(outPath);
}

function probeDuration(filePath) {
  const out = execFileSync('ffprobe', [
    '-v', 'error',
    '-show_entries', 'format=duration',
    '-of', 'csv=p=0',
    filePath,
  ], { encoding: 'utf-8' }).trim();
  return parseFloat(out);
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

// Step 1: Prepare all 10 opening frames
console.log('=== Step 1: Preparing Act I Pilot Frames (A01-A10) ===');
for (const shot of PILOT_SHOTS) {
  const outPng = join(FRAMES_DIR, `${shot.id}.png`);
  if (shot.reuse_v1_frame) {
    const srcPng = join(V1_FRAMES_DIR, shot.reuse_v1_frame);
    copyFileSync(srcPng, outPng);
    console.log(`✓ Reused verified frame ${shot.reuse_v1_frame} -> ${outPng}`);
  } else if (!existsSync(outPng) || process.argv.includes('--regen-frames')) {
    const ok = genImage(shot.image_prompt, outPng, shot.refs);
    if (!ok) {
      console.error(`Retrying frame ${shot.id}...`);
      genImage(shot.image_prompt, outPng, shot.refs);
    }
  } else {
    console.log(`✓ Frame ${outPng} already exists`);
  }
}

// Step 2: Generate single-speaker TTS voices & pad/trim to exact shot duration
console.log('\n=== Step 2: Generating Single-Speaker Gemini TTS Voices (A02, A03, A05, A06, A09, A10) ===');
for (const shot of PILOT_SHOTS) {
  if (shot.mode !== 'lip_sync' || !shot.dialogue_text) continue;
  const rawWav = join(VOICES_DIR, `${shot.id}_raw.wav`);
  const finalWav = join(VOICES_DIR, `${shot.id}.wav`);

  if (!existsSync(rawWav) || process.argv.includes('--regen-voices')) {
    console.log(`\n>>> Synthesizing ${shot.id} (${shot.speaker} / ${shot.voice}): "${shot.dialogue_text}" <<<`);
    let ok = false;
    for (let attempt = 1; attempt <= 3; attempt++) {
      const res = spawnSync(process.execPath, [
        TTS_SCRIPT,
        shot.dialogue_text,
        '--voice', shot.voice,
        '--model', 'gemini-3.8-flash-tts',
        '--output', rawWav,
      ], {
        cwd: MORPHEUS_DIR,
        env: process.env,
        stdio: 'inherit',
      });
      if (res.status === 0 && existsSync(rawWav)) {
        ok = true;
        break;
      }
      console.warn(`Attempt ${attempt} failed for ${shot.id}, waiting 20s before retry...`);
      sleepSync(20000);
    }
    if (!ok) {
      throw new Error(`Failed to synthesize voice for ${shot.id}`);
    }
    sleepSync(6000);
  }

  const rawDur = probeDuration(rawWav);
  console.log(`Raw TTS duration for ${shot.id}: ${rawDur.toFixed(2)}s (target window: ${shot.duration}s)`);

  // If raw speech is slightly longer than (shot.duration - 0.35s), gently speed up via atempo so it fits with a 0.2s lead-in and 0.15s tail
  const maxSpeechDur = shot.duration - 0.35;
  let tempoFilter = '';
  if (rawDur > maxSpeechDur) {
    const factor = Math.min(1.35, Math.max(1.0, rawDur / maxSpeechDur));
    tempoFilter = `atempo=${factor.toFixed(3)},`;
    console.log(`Applying gentle atempo=${factor.toFixed(3)} to fit ${shot.id} cleanly inside ${shot.duration}s`);
  }

  // Build exact shot.duration 48kHz stereo PCM WAV with 200ms lead-in silence
  execFileSync('ffmpeg', [
    '-v', 'error', '-y',
    '-i', rawWav,
    '-af', `${tempoFilter}aresample=48000,pan=stereo|c0=c0|c1=c0,adelay=200|200,apad=pad_dur=3,atrim=duration=${shot.duration},afade=t=in:d=0.01,afade=t=out:st=${(shot.duration - 0.05).toFixed(2)}:d=0.05`,
    '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le',
    finalWav,
  ], { stdio: 'inherit' });

  const finalDur = probeDuration(finalWav);
  console.log(`✓ Final lip-sync WAV ${shot.id}.wav: ${finalDur.toFixed(3)}s`);
}

// Step 3: Write v2_pilot/manifest.json
let at = 0;
const manifestShots = PILOT_SHOTS.map((s, idx) => {
  const start = at;
  const end = at + s.duration;
  at = end;
  return {
    id: s.id,
    number: idx + 1,
    title: s.title,
    mode: s.mode,
    duration: s.duration,
    edit_seconds: s.duration,
    edit_frames: s.duration * 24,
    trim_start_frame: 0,
    start,
    end,
    seed: s.seed,
    cast: s.cast,
    speaker: s.speaker,
    voice: s.voice,
    dialogue_text: s.dialogue_text,
    frame: `frames/${s.id}.png`,
    voice_file: s.mode === 'lip_sync' ? `voices/${s.id}.wav` : null,
    clip: `clips/${s.id}.mp4`,
    image_prompt: s.image_prompt,
    video_prompt: s.video_prompt,
  };
});

const manifest = {
  schema: 'execution_manifest.v2_pilot',
  title: 'Rift Runners — Act I Pilot (v2 Lip-Sync Close-Ups & Accurate Prompts)',
  fps: 24,
  total_seconds: at,
  total_frames: at * 24,
  full_episode_seconds: at,
  full_episode_frames: at * 24,
  output_width: 1600,
  output_height: 896,
  score_file: '../rift_runners_original_score.wav',
  master_filename: 'Rift_Runners_Act1_Pilot_v2.mp4',
  settings: {
    engine: 'ltx',
    steps: '8',
    ltx_quality: 'balanced',
    aspect_ratio: '16:9',
  },
  shots: manifestShots,
};

writeFileSync(join(PILOT_DIR, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf-8');
console.log(`\n✓ Wrote v2_pilot/manifest.json (${manifestShots.length} shots, ${at}s total)`);
