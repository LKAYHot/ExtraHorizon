import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))

export default function globalSetup() {
  if (!existsSync(path.join(here, '..', 'build', 'index.html'))) {
    throw new Error('frontend/build is missing — run `npm run build` first (npm run e2e does it for you).')
  }
  for (const [faces, file] of [['1', 'face.y4m'], ['2', 'two_faces.y4m']]) {
    const out = path.join(here, '.cache', file)
    if (existsSync(out)) continue
    execFileSync('uv', ['run', '--directory', '../backend', 'python', 'scripts/make_fake_camera.py', '--faces', faces, '--out', out], {
      cwd: path.join(here, '..'),
      stdio: 'inherit',
    })
  }
}
