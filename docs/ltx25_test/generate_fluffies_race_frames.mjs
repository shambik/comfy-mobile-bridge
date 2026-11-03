import { spawnSync } from 'child_process';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const MORPHEUS_DIR = 'C:/Users/David Shambik/Downloads/chatcut-standalone-complete/chatcut-standalone-complete';
const IMG_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'image-generate.mjs');
const EP_DIR = 'D:/repository/state/fluffies_ep04_scooter_race';
const REFS_DIR = join(EP_DIR, 'refs');
const FRAMES_DIR = join(EP_DIR, 'frames');

// Load environment variables for credentials
for (const line of readFileSync(join(MORPHEUS_DIR, 'CREDENTIALS.env'), 'utf-8').split('\n')) {
  const t = line.trim();
  if (!t || t.startsWith('#') || !t.includes('=')) continue;
  const idx = t.indexOf('=');
  const k = t.slice(0, idx).replace(/^export\s+/, '').trim();
  let v = t.slice(idx + 1).trim();
  if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
  process.env[k] = v;
}

const vehiclesRef = join(REFS_DIR, 'vehicles-sheet.png');
const trioRef = join(REFS_DIR, 'blue-pink-purple-lineup-v1.png');
const duoRef = join(REFS_DIR, 'white-charcoal-lineup-v2.png');
const openerRef = join(REFS_DIR, 'selected-opener-cast.png');

const manifest = JSON.parse(readFileSync(join(EP_DIR, 'manifest.json'), 'utf-8'));

function getRefsForShot(shot) {
  const cast = shot.cast;
  const refs = [vehiclesRef];
  const hasBobo = cast.includes('Bobo');
  const hasLulu = cast.includes('Lulu');
  const hasZuzu = cast.includes('Zuzu');
  const hasPebble = cast.includes('Pebble');
  const hasNumi = cast.includes('Numi');

  if (hasBobo || hasLulu || hasZuzu) {
    refs.push(trioRef);
  }
  if (hasPebble || hasNumi) {
    refs.push(duoRef);
  }
  return refs.filter(p => existsSync(p));
}

function generateFrame(shot) {
  const outPath = join(FRAMES_DIR, `${shot.id}.png`);
  if (existsSync(outPath) && !process.argv.includes('--force')) {
    console.log(`[SKIP] ${shot.id} frame already exists: ${outPath}`);
    return true;
  }

  const refs = getRefsForShot(shot);
  const args = [
    IMG_SCRIPT,
    shot.image_prompt,
    '--model', 'nano-banana-2',
    '--aspect', '16:9',
    '--resolution', '1K',
    '--output', outPath,
  ];
  if (refs.length > 0) {
    args.push('--image', ...refs);
  }

  console.log(`\n======================================================`);
  console.log(`>>> Generating ${shot.id} (${shot.title}) with ${refs.length} refs <<<`);
  console.log(`======================================================`);

  const res = spawnSync(process.execPath, args, {
    cwd: MORPHEUS_DIR,
    env: process.env,
    stdio: 'inherit',
  });

  if (res.status === 0 && existsSync(outPath)) {
    console.log(`✓ ${shot.id} frame generated successfully`);
    return true;
  }

  console.error(`WARN: Generation failed for ${shot.id}, retrying once...`);
  const retry = spawnSync(process.execPath, args, {
    cwd: MORPHEUS_DIR,
    env: process.env,
    stdio: 'inherit',
  });
  return retry.status === 0 && existsSync(outPath);
}

const onlyArgIndex = process.argv.indexOf('--only');
const targetId = onlyArgIndex !== -1 ? process.argv[onlyArgIndex + 1] : null;

for (const shot of manifest.shots) {
  if (targetId && shot.id !== targetId) continue;
  const ok = generateFrame(shot);
  if (!ok) {
    console.error(`Failed on ${shot.id}`);
    process.exit(1);
  }
}

console.log('\nAll requested frames generated successfully!');
