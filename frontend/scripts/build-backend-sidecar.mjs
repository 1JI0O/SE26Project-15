import { execFileSync } from 'node:child_process'
import { chmodSync, copyFileSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const backendRoot = path.join(repositoryRoot, 'backend')
const buildRoot = path.join(backendRoot, '.desktop-build')
const distRoot = path.join(backendRoot, '.desktop-dist')
const binariesRoot = path.join(frontendRoot, 'src-tauri', 'binaries')
const executableSuffix = process.platform === 'win32' ? '.exe' : ''

function commandOutput(command, args) {
  return execFileSync(command, args, { encoding: 'utf8' }).trim()
}

let targetTriple
try {
  targetTriple = commandOutput('rustc', ['--print', 'host-tuple'])
} catch {
  throw new Error('Rust toolchain is required. Install rustup before building the desktop app.')
}

rmSync(buildRoot, { recursive: true, force: true })
rmSync(distRoot, { recursive: true, force: true })
mkdirSync(buildRoot, { recursive: true })
mkdirSync(binariesRoot, { recursive: true })

const addDataSeparator = process.platform === 'win32' ? ';' : ':'
const migrations = path.join(backendRoot, 'app', 'db', 'migrations')
const pyinstallerArgs = [
  'run',
  '--project',
  backendRoot,
  '--extra',
  'desktop',
  'pyinstaller',
  '--clean',
  '--noconfirm',
  '--onefile',
  '--name',
  'tracelab-backend',
  '--paths',
  backendRoot,
  '--distpath',
  distRoot,
  '--workpath',
  path.join(buildRoot, 'work'),
  '--specpath',
  buildRoot,
  '--collect-submodules',
  'app',
  '--collect-all',
  'uvicorn',
  '--add-data',
  `${migrations}${addDataSeparator}app/db/migrations`,
  path.join(backendRoot, 'app', 'desktop.py'),
]

execFileSync('uv', pyinstallerArgs, {
  cwd: repositoryRoot,
  stdio: 'inherit',
})

const builtBinary = path.join(distRoot, `tracelab-backend${executableSuffix}`)
const sidecarBinary = path.join(
  binariesRoot,
  `tracelab-backend-${targetTriple}${executableSuffix}`,
)
copyFileSync(builtBinary, sidecarBinary)
if (process.platform !== 'win32') chmodSync(sidecarBinary, 0o755)

console.log(`Prepared Tauri sidecar: ${sidecarBinary}`)
