import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const run = (script, args) =>
  execFileSync('uv', ['run', '--directory', '../backend', 'python', `scripts/${script}`, ...args], {
    cwd: path.join(here, '..'),
    stdio: 'inherit',
  })

export default function globalSetup() {
  if (!existsSync(path.join(here, '..', 'build', 'index.html'))) {
    throw new Error('frontend/build is missing — run `npm run build` first (npm run e2e does it for you).')
  }
  // virtual camera clips (the MediaPipe test portrait)
  for (const [faces, file] of [['1', 'face.y4m'], ['2', 'two_faces.y4m']]) {
    const out = path.join(here, '.cache', file)
    if (!existsSync(out)) run('make_fake_camera.py', ['--faces', faces, '--out', out])
  }
  // virtual microphone clip (offline Windows voice); the voice test is skipped without it
  const wav = path.join(here, '.cache', 'question.wav')
  if (!existsSync(wav) && process.platform === 'win32') {
    try {
      run('make_fake_mic.py', ['--out', wav])
    } catch {
      console.warn('[e2e] could not build the virtual microphone clip — the voice test will be skipped')
    }
  }
}
