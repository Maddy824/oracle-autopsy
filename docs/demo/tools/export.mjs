// Frame-by-frame export (Bang Motion export-frames.mjs approach): seek the timeline, wait two rAFs, capture, pipe to ffmpeg.
import { chromium } from 'playwright-core';
import { pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
const [src, out] = process.argv.slice(2); const FPS = Number(process.env.FPS || 30);
const exe = process.env.CHROME; // path to a Chromium / headless-shell binary
const browser = await chromium.launch({ executablePath: exe || undefined, args: ['--force-color-profile=srgb'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
page.on('pageerror', e => console.log('PAGEERROR', e.message));
await page.goto(pathToFileURL(src).href + '?clean=1', { waitUntil: 'networkidle' });
await page.waitForFunction('window.OPENER && window.OPENER.ready', null, { timeout: 60000 });
const DURATION = await page.evaluate(() => window.OPENER.DURATION);
const total = Math.round(DURATION * FPS);
const ff = spawn('ffmpeg', ['-loglevel','error','-y','-f','image2pipe','-framerate',String(FPS),'-i','-',
  '-c:v','libx264','-preset','slow','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart', out], { stdio: ['pipe','inherit','inherit'] });
for (let i = 0; i < total; i++) {
  const t = i / FPS;
  await page.evaluate(async (time) => { window.OPENER.seek(time);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); window.OPENER.seek(time); }, t);
  const buf = await page.screenshot({ type: 'jpeg', quality: 95 });
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
  if (i % (FPS * 5) === 0) console.log(`${i}/${total} ${t.toFixed(1)}s`);
}
ff.stdin.end(); await new Promise(r => ff.on('close', r));
await browser.close(); console.log('done', total, 'frames');
