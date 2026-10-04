#!/usr/bin/env node
// Playwright + ffmpeg frame-render pipeline.
//   node render.js --out six_to_picnic.mp4 --audio /path/track.wav      # full encode (frames piped, never stored)
//   node render.js --preview 0.5,1.3,2.5 --dir /path/previews             # PNG stills for eyeballing
'use strict';
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const FPS = 60, DUR = 15, N = FPS * DUR, W = 1920, H = 1080;
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  page.on('pageerror', e => { console.error('PAGE ERROR:', e.message); process.exitCode = 1; });
  await page.goto('file://' + path.resolve(__dirname, 'scene.html'));
  await page.waitForFunction(() => window.__ready === true);

  const grab = async (t) => {
    const url = await page.evaluate(tt => window.__frame(tt), t);
    return Buffer.from(url.slice(url.indexOf(',') + 1), 'base64');
  };

  if (opt('--preview')) {
    const dir = opt('--dir', '.'); fs.mkdirSync(dir, { recursive: true });
    for (const ts of opt('--preview').split(',')) {
      const t = parseFloat(ts); fs.writeFileSync(path.join(dir, `f_${t.toFixed(2)}.png`), await grab(t));
    }
    await browser.close(); return;
  }

  const out = opt('--out', 'six_to_picnic.mp4');
  const audio = opt('--audio');
  const ff = spawn('ffmpeg', [
    '-y', '-hide_banner', '-loglevel', 'warning',
    '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    ...(audio ? ['-i', audio] : []),
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '19', '-tune', 'animation',
    '-maxrate', '13M', '-bufsize', '26M', '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.2',
    '-r', String(FPS), '-vframes', String(N),
    ...(audio ? ['-c:a', 'aac', '-b:a', '192k', '-shortest'] : []),
    '-movflags', '+faststart', out,
  ], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((res, rej) => ff.on('close', c => c === 0 ? res() : rej(new Error('ffmpeg exit ' + c))));

  const t0 = Date.now();
  for (let i = 0; i < N; i++) {
    const buf = await grab(i / FPS);
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (i % 120 === 0) console.log(`frame ${i}/${N}  ${((Date.now() - t0) / 1000).toFixed(1)}s`);
  }
  ff.stdin.end();
  await done;
  await browser.close();
  console.log(`done: ${out} in ${((Date.now() - t0) / 1000).toFixed(1)}s`);
})().catch(e => { console.error(e); process.exit(1); });
