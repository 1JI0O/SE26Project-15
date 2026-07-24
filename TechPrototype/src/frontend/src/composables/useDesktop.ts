import { ref } from 'vue'

/**
 * Detect if running inside Tauri desktop shell.
 * Uses the __TAURI_INTERNALS__ global injected by Tauri at runtime.
 */
function isTauri(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export function useDesktop() {
  const isDesktop = ref(isTauri())

  /**
   * Open a file dialog filtered to PDF files.
   * Returns a File object or null if cancelled.
   */
  async function pickPdfFile(): Promise<File | null> {
    if (!isDesktop.value) return null

    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      multiple: false,
      filters: [
        { name: 'PDF 文件', extensions: ['pdf'] },
      ],
    })

    if (!selected) return null

    const filePath = typeof selected === 'string' ? selected : selected
    const fileName = filePath.split('/').pop() ?? 'paper.pdf'
    const { readFile } = await import('@tauri-apps/plugin-fs')
    const fileData = await readFile(filePath)
    return new File([fileData], fileName, { type: 'application/pdf' })
  }

  /**
   * Open a file dialog filtered to ZIP files.
   * Returns a File object or null if cancelled.
   */
  async function pickZipFile(): Promise<File | null> {
    if (!isDesktop.value) return null

    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      multiple: false,
      filters: [
        { name: 'ZIP 压缩包', extensions: ['zip'] },
      ],
    })

    if (!selected) return null

    const filePath = typeof selected === 'string' ? selected : selected
    const fileName = filePath.split('/').pop() ?? 'repo.zip'
    const { readFile } = await import('@tauri-apps/plugin-fs')
    const fileData = await readFile(filePath)
    return new File([fileData], fileName, { type: 'application/zip' })
  }

  /**
   * Open a directory picker.
   * Returns the selected directory path or null if cancelled.
   */
  async function pickDirectory(): Promise<string | null> {
    if (!isDesktop.value) return null

    const { open } = await import('@tauri-apps/plugin-dialog')
    const selected = await open({
      directory: true,
      multiple: false,
    })

    if (!selected) return null
    return typeof selected === 'string' ? selected : String(selected)
  }

  return {
    isDesktop,
    pickPdfFile,
    pickZipFile,
    pickDirectory,
  }
}
