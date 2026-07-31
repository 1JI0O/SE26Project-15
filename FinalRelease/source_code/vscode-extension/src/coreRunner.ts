import { spawn } from 'node:child_process'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import * as vscode from 'vscode'
import { runtimeConfig, SecretStore } from './secrets'

export interface CliResult {
  ok: boolean
  error?: string
  stdout?: string
  stderr?: string
  [key: string]: unknown
}

export interface ProgressEvent {
  phase: string
  message: string
  current?: number
  total?: number
  event_kind?: string
  tool?: string
  published?: number
  step?: number
  [key: string]: unknown
}

export type ProgressHandler = (event: ProgressEvent) => void

export class CoreRunner {
  private readonly log: vscode.OutputChannel
  private readonly bundledRoot: string
  private syncPromise?: Promise<CliResult>
  onProgress?: ProgressHandler

  constructor(
    private readonly secrets: SecretStore,
    extensionPath: string,
    log?: vscode.OutputChannel,
  ) {
    this.log = log ?? vscode.window.createOutputChannel('TraceLab')
    this.bundledRoot = path.join(extensionPath, 'bundled')
  }

  get output(): vscode.OutputChannel {
    return this.log
  }

  private runtimeReady(): boolean {
    return (
      fs.existsSync(path.join(this.bundledRoot, 'pyproject.toml')) &&
      fs.existsSync(path.join(this.bundledRoot, 'tracelab_core', 'cli.py'))
    )
  }

  async ensureRuntime(): Promise<CliResult> {
    if (!this.runtimeReady()) {
      const error =
        'Bundled TraceLab runtime missing (extension/bundled). Reinstall the VSIX.'
      this.log.appendLine(`[error] ${error}`)
      return { ok: false, error }
    }
    if (!this.syncPromise) {
      this.syncPromise = this.syncBundledDeps()
    }
    return this.syncPromise
  }

  /**
   * Interpreter inside the bundled venv, when `uv sync` already created it.
   *
   * Calling it directly skips `uv run`'s per-invocation project resolution
   * (~350ms vs ~70ms), which matters because the CLI is invoked for every
   * status / tensor refresh.
   */
  private venvPython(): string | undefined {
    const candidates =
      process.platform === 'win32'
        ? [path.join(this.bundledRoot, '.venv', 'Scripts', 'python.exe')]
        : [path.join(this.bundledRoot, '.venv', 'bin', 'python')]
    return candidates.find((candidate) => fs.existsSync(candidate))
  }

  private async syncBundledDeps(): Promise<CliResult> {
    const marker = this.venvPython()
    if (marker) {
      this.log.appendLine(`[runtime] using existing venv at ${marker}`)
      return { ok: true }
    }
    this.log.appendLine(`[runtime] uv sync --project ${this.bundledRoot}`)
    try {
      await this.execCapture('uv', ['sync', '--project', this.bundledRoot], this.bundledRoot)
      return { ok: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.syncPromise = undefined
      return {
        ok: false,
        error: `Failed to install bundled Python deps (need uv on PATH): ${message}`,
      }
    }
  }

  private execCapture(command: string, args: string[], cwd: string): Promise<{ stdout: string; stderr: string }> {
    return new Promise((resolve, reject) => {
      const child = spawn(command, args, { cwd, env: process.env })
      let stdout = ''
      let stderr = ''
      child.stdout.on('data', (chunk: Buffer) => {
        stdout += chunk.toString()
      })
      child.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString()
      })
      child.on('error', reject)
      child.on('close', (code) => {
        if (code === 0) {
          resolve({ stdout, stderr })
        } else {
          reject(new Error(stderr.trim() || stdout.trim() || `exit ${code}`))
        }
      })
    })
  }

  private async runCli(
    workspace: string,
    subcommand: string[],
    config?: Record<string, unknown> | object,
  ): Promise<CliResult> {
    const ready = await this.ensureRuntime()
    if (!ready.ok) {
      return ready
    }

    const pythonPath = vscode.workspace.getConfiguration('tracelab').get<string>('pythonPath', 'uv')
    let configPath: string | undefined
    if (config) {
      configPath = await this.writeTempConfig(config)
    }

    const tracelabArgs = ['--workspace', workspace, ...subcommand]
    if (
      configPath &&
      (subcommand[0] === 'parse' ||
        subcommand[0] === 'trace' ||
        subcommand[0] === 'probe')
    ) {
      tracelabArgs.push('--config', configPath)
    }

    const env = {
      ...process.env,
      PYTHONPATH: [this.bundledRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    }
    const label = `tracelab ${subcommand.join(' ')}`
    this.log.appendLine(`[run] bundled=${this.bundledRoot} workspace=${workspace} ${label}`)

    const venv = pythonPath === 'uv' ? this.venvPython() : undefined
    const command = venv ?? (pythonPath === 'uv' ? 'uv' : pythonPath)
    const args =
      command === 'uv'
        ? ['run', '--project', this.bundledRoot, 'python', '-m', 'tracelab_core.cli', ...tracelabArgs]
        : ['-m', 'tracelab_core.cli', ...tracelabArgs]

    try {
      const { stdout, stderr, final } = await this.spawnNdjson(command, args, env)
      if (stderr.trim()) {
        this.log.appendLine(`[stderr] ${stderr.trim()}`)
      }
      if (!final) {
        return {
          ok: false,
          error: `No final JSON from CLI. stdout=${stdout.slice(0, 500)}`,
          stdout,
          stderr,
        }
      }
      if (!final.ok) {
        this.log.appendLine(`[error] ${String(final.error ?? 'unknown')}`)
      }
      return { ...final, stdout, stderr }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      this.log.appendLine(`[error] ${message}`)
      return { ok: false, error: message }
    } finally {
      if (configPath) {
        fs.unlink(configPath, () => undefined)
      }
    }
  }

  private spawnNdjson(
    command: string,
    args: string[],
    env: NodeJS.ProcessEnv,
  ): Promise<{ stdout: string; stderr: string; final?: CliResult }> {
    return new Promise((resolve, reject) => {
      const child = spawn(command, args, { cwd: this.bundledRoot, env })
      let stdout = ''
      let stderr = ''
      let buffer = ''
      let final: CliResult | undefined

      child.stdout.on('data', (chunk: Buffer) => {
        const text = chunk.toString()
        stdout += text
        buffer += text
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            continue
          }
          this.log.appendLine(`[stdout] ${trimmed}`)
          try {
            const parsed = JSON.parse(trimmed) as CliResult & {
              event?: string
              phase?: string
              message?: string
              current?: number
              total?: number
              event_kind?: string
              tool?: string
              published?: number
            }
            if (parsed.event === 'progress') {
              this.onProgress?.({
                ...parsed,
                phase: String(parsed.phase ?? ''),
                message: String(parsed.message ?? ''),
              })
            } else {
              final = parsed
            }
          } catch {
            // ignore non-json noise
          }
        }
      })
      child.stderr.on('data', (chunk: Buffer) => {
        stderr += chunk.toString()
      })
      child.on('error', reject)
      child.on('close', () => {
        const trimmed = buffer.trim()
        if (trimmed) {
          this.log.appendLine(`[stdout] ${trimmed}`)
          try {
            const parsed = JSON.parse(trimmed) as CliResult & { event?: string }
            if (parsed.event === 'progress') {
              this.onProgress?.({
                ...parsed,
                phase: String((parsed as { phase?: string }).phase ?? ''),
                message: String((parsed as { message?: string }).message ?? ''),
              })
            } else {
              final = parsed
            }
          } catch {
            // ignore
          }
        }
        resolve({ stdout, stderr, final })
      })
    })
  }

  private async writeTempConfig(config: Record<string, unknown> | object): Promise<string> {
    const file = path.join(os.tmpdir(), `tracelab-config-${Date.now()}.json`)
    await fs.promises.writeFile(file, JSON.stringify(config), 'utf8')
    return file
  }

  async init(workspace: string): Promise<CliResult> {
    return this.runCli(workspace, ['init'])
  }

  async importPdf(workspace: string, pdfPath: string): Promise<CliResult> {
    return this.runCli(workspace, ['import-pdf', '--pdf', pdfPath])
  }

  async parse(workspace: string): Promise<CliResult> {
    const config = await runtimeConfig(this.secrets)
    return this.runCli(workspace, ['parse'], config)
  }

  async analyze(workspace: string): Promise<CliResult> {
    return this.runCli(workspace, ['analyze'])
  }

  async trace(workspace: string, options: { replace?: boolean } = {}): Promise<CliResult> {
    const config = await runtimeConfig(this.secrets)
    const args = ['trace']
    if (options.replace) {
      args.push('--replace')
    }
    return this.runCli(workspace, args, config)
  }

  async status(workspace: string): Promise<CliResult> {
    return this.runCli(workspace, ['status'])
  }

  async review(workspace: string, linkId: string, status: 'accepted' | 'rejected' | 'proposed'): Promise<CliResult> {
    return this.runCli(workspace, ['review', '--link-id', linkId, '--status', status])
  }

  async reviewBatch(
    workspace: string,
    status: 'accepted' | 'rejected' | 'proposed',
    options: { ids?: string[]; allProposed?: boolean },
  ): Promise<CliResult> {
    const args = ['review-batch', '--status', status]
    if (options.allProposed) {
      args.push('--all-proposed')
    } else if (options.ids?.length) {
      args.push('--ids', options.ids.join(','))
    }
    return this.runCli(workspace, args)
  }

  async probe(workspace: string, target: 'llm' | 'mineru'): Promise<CliResult> {
    const config = await runtimeConfig(this.secrets)
    return this.runCli(workspace, ['probe', '--target', target], config)
  }

  async tensorFlow(
    workspace: string,
    options: { view?: 'architecture' | 'debug'; root?: string } = {},
  ): Promise<CliResult> {
    const args = ['tensor-flow', '--view', options.view ?? 'architecture']
    if (options.root) {
      args.push('--root', options.root)
    }
    return this.runCli(workspace, args)
  }

  tracelabRoot(workspace: string): string {
    return path.join(workspace, '.tracelab')
  }

  readJsonFile<T>(filePath: string): T | undefined {
    try {
      return JSON.parse(fs.readFileSync(filePath, 'utf8')) as T
    } catch {
      return undefined
    }
  }
}
