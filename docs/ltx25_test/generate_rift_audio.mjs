import { spawnSync, execFileSync } from 'child_process';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';

const MORPHEUS_DIR = 'C:/Users/David Shambik/Downloads/chatcut-standalone-complete/chatcut-standalone-complete';
const LYRIA_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'lyria-generate.mjs');
const TTS_SCRIPT = join(MORPHEUS_DIR, 'scripts', 'gemini-tts.mjs');

const STATE_DIR = 'D:/repository/state/rift_runners_ep01';
const DIST_DIR = 'D:/repository/dist/rift-runners';
const VOICES_DIR = join(STATE_DIR, 'voices');
mkdirSync(VOICES_DIR, { recursive: true });

function syncDist() {
  try {
    spawnSync('robocopy', [STATE_DIR, DIST_DIR, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'], { stdio: 'ignore' });
  } catch {}
}

// 1. Generate Google Lyria 3.5 Hip-Hop Soundtrack
console.log('=== Step 1: Generating Google Lyria 3.5 Hip-Hop Soundtrack ===');
const track1 = join(STATE_DIR, 'lyria35_hiphop_part1.wav');
const track2 = join(STATE_DIR, 'lyria35_hiphop_part2.wav');
const finalScore = join(STATE_DIR, 'rift_runners_original_score.wav');

const p1 = 'Upbeat 98 BPM golden-era sci-fi boom-bap hip-hop instrumental beat with punchy MPC drums, deep warm 808 sub-bass groove, funky Rhodes electric piano chords, brass horn stabs, and turntablism scratches, clean studio mix';
const p2 = 'High-energy 110 BPM cinematic action hip-hop breakbeat instrumental with driving live drums, heavy sub-bass, heroic brass hits, and futuristic synth arpeggios, triumphant adventure finale';

const r1 = spawnSync(process.execPath, [LYRIA_SCRIPT, p1, '--model', 'lyria-3.5', '--instrumental', '--output', track1], {
  cwd: MORPHEUS_DIR,
  stdio: 'inherit',
});
const r2 = spawnSync(process.execPath, [LYRIA_SCRIPT, p2, '--model', 'lyria-3.5', '--instrumental', '--output', track2], {
  cwd: MORPHEUS_DIR,
  stdio: 'inherit',
});

if (existsSync(track1) && existsSync(track2)) {
  // Stitch & loop/crossfade into exact 119s 48kHz stereo WAV
  execFileSync('ffmpeg', [
    '-y',
    '-stream_loop', '1', '-i', track1,
    '-stream_loop', '1', '-i', track2,
    '-filter_complex', '[0:a]atrim=0:62,asetpts=PTS-STARTPTS[a0];[1:a]atrim=0:60,asetpts=PTS-STARTPTS[a1];[a0][a1]acrossfade=d=3:c1=tri:c2=tri,atrim=0:119,afade=t=out:st=116:d=3[out]',
    '-map', '[out]', '-ar', '48000', '-ac', '2', finalScore,
  ], { stdio: 'inherit' });
  console.log('✓ Saved 119s Google Lyria 3.5 Hip-Hop Score:', finalScore);
  syncDist();
} else if (existsSync(track1)) {
  execFileSync('ffmpeg', [
    '-y', '-stream_loop', '3', '-i', track1,
    '-t', '119', '-af', 'afade=t=out:st=116:d=3', '-ar', '48000', '-ac', '2', finalScore,
  ], { stdio: 'inherit' });
  syncDist();
}

// 2. Generate Gemini 3.8 Flash TTS Multi-Speaker Dialogue for all 16 shots
console.log('=== Step 2: Generating Gemini 3.8 Flash TTS Character Dialogue (S01-S16) ===');
const manifest = JSON.parse(readFileSync(join(STATE_DIR, 'manifest.json'), 'utf-8'));

for (const shot of manifest.shots) {
  const sid = shot.id;
  const outWav = join(VOICES_DIR, `${sid}.wav`);
  const dialogue = shot.dialogue || [];
  if (dialogue.length === 0) continue;
  console.log(`\n--- Synthesizing ${sid} (${shot.title}) ---`);
  const res = spawnSync(process.execPath, [
    TTS_SCRIPT,
    '--model', 'gemini-3.8-flash-tts',
    '--dialogue', JSON.stringify(dialogue),
    '--output', outWav,
  ], {
    cwd: MORPHEUS_DIR,
    stdio: 'inherit',
  });
  if (res.status === 0 && existsSync(outWav)) {
    syncDist();
  }
}

console.log('\n=== All Lyria 3.5 Hip-Hop Music & Gemini 3.8 Character Voices Complete! ===');
syncDist();
