import { spawnSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const MORPHEUS_DIR = 'C:/Users/David Shambik/Downloads/chatcut-standalone-complete/chatcut-standalone-complete';
const IMG_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'image-generate.mjs');
const EP_DIR = 'D:/repository/state/fluffies_ep04_scooter_race';
const REFS_DIR = join(EP_DIR, 'refs');

for (const line of readFileSync(join(MORPHEUS_DIR, 'CREDENTIALS.env'), 'utf-8').split('\n')) {
  const t = line.trim();
  if (!t || t.startsWith('#') || !t.includes('=')) continue;
  const idx = t.indexOf('=');
  const k = t.slice(0, idx).replace(/^export\s+/, '').trim();
  let v = t.slice(idx + 1).trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
  process.env[k] = v;
}

const prompt = `Model sheet showing four cute chunky storybook children's racing vehicles in a clean lineup on a neutral pastel background, 3D clay-render Pixar style matching the Fluffies world:
1. Bobo's Red Kick-Scooter: a bright cherry-red vintage enamel two-wheel kick scooter with thick cream solid rubber disc wheels (no thin wire spokes), polished wooden foot deck, chrome curved handlebars with a small shiny brass thumb-bell, and a tiny red pennant flag on the rear wheel guard.
2. Lulu's Mint Balance Bicycle: a soft pastel mint-green wooden low balance bike (foot-stride bicycle without pedals or chain), chunky cream solid disc wheels, a small woven wicker front handlebar basket filled with tiny yellow buttercup flowers, and pink rubber hand grips.
3. Zuzu's Yellow Kick-Scooter: an extra-tall sunny-yellow metal kick scooter with an elongated handlebar stem, bright turquoise solid disc wheels, and vibrant striped rainbow ribbon streamers fluttering from both handlebar grips.
4. Pebble's Blue Cargo Trike: a low sturdy sky-blue wooden three-wheel trike (one front wheel, two wide rear wheels) with solid cream wheels, low seat, and a small rectangular wooden open cargo box on the back holding a checkered pastel flag.
Clean studio lighting, warm soft contact shadows, beautiful tactile materials, toy-like chunky durability.`;

const outPath = join(REFS_DIR, 'vehicles-sheet.png');
console.log(`Generating vehicle reference sheet: ${outPath}...`);

const res = spawnSync(process.execPath, [
  IMG_SCRIPT,
  prompt,
  '--model', 'nano-banana-2',
  '--aspect', '16:9',
  '--resolution', '1K',
  '--output', outPath
], {
  cwd: MORPHEUS_DIR,
  env: process.env,
  stdio: 'inherit'
});

if (res.status !== 0 || !existsSync(outPath)) {
  console.error('Failed to generate vehicle reference sheet');
  process.exit(1);
}
console.log('Vehicle reference sheet generated successfully!');
