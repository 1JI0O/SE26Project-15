import { execFileSync } from 'node:child_process'
import { chmodSync, cpSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const backendRoot = path.join(repositoryRoot, 'backend')
const buildRoot = path.join(backendRoot, '.desktop-build')
const distRoot = path.join(backendRoot, '.desktop-dist')
const runtimeRoot = path.join(frontendRoot, 'src-tauri', 'resources', 'backend-runtime')
const executableSuffix = process.platform === 'win32' ? '.exe' : ''

rmSync(buildRoot, { recursive: true, force: true })
rmSync(distRoot, { recursive: true, force: true })
rmSync(runtimeRoot, { recursive: true, force: true })
mkdirSync(buildRoot, { recursive: true })
mkdirSync(path.dirname(runtimeRoot), { recursive: true })

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
  '--onedir',
  '--noconsole',
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

const builtRuntime = path.join(distRoot, 'tracelab-backend')
cpSync(builtRuntime, runtimeRoot, { recursive: true })
const runtimeExecutable = path.join(runtimeRoot, `tracelab-backend${executableSuffix}`)
if (process.platform !== 'win32') chmodSync(runtimeExecutable, 0o755)

console.log(`Prepared Tauri backend runtime: ${runtimeRoot}`)
