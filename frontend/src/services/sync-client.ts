import { cloudHttp, hasLocalWorkspace, localHttp } from '@/api/http'
import type { SyncEvent, SyncOperation } from '@/types/cloud'
import type { CloudProject } from '@/types/cloud'

async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

async function attachBlob(operation: SyncOperation): Promise<SyncOperation> {
  if (!operation.payload.requires_blob) return operation
  const response = await localHttp.get<ArrayBuffer>(
    `/local-sync/blobs/${operation.entity_type}/${operation.entity_public_id}`,
    { responseType: 'arraybuffer' },
  )
  const bytes = response.data
  const filename = String(operation.payload.filename ?? 'upload.bin')
  const mimeType = filename.toLowerCase().endsWith('.pdf')
    ? 'application/pdf'
    : filename.toLowerCase().endsWith('.zip')
      ? 'application/zip'
      : 'application/octet-stream'
  const initialized = await cloudHttp.post<{
    blob_id: string
    status: 'upload' | 'reuse'
    chunk_size: number
    uploaded_bytes: number
  }>('/blobs/upload-init', {
    workspace_id: operation.workspace_id,
    project_public_id: operation.payload.project_public_id,
    sha256: await sha256Hex(bytes),
    byte_size: bytes.byteLength,
    mime_type: mimeType,
    filename,
  })
  if (initialized.data.status === 'upload') {
    const chunkSize = initialized.data.chunk_size
    for (
      let offset = initialized.data.uploaded_bytes;
      offset < bytes.byteLength;
      offset += chunkSize
    ) {
      const index = Math.floor(offset / chunkSize)
      await cloudHttp.put(
        `/blobs/${initialized.data.blob_id}/chunks/${index}`,
        bytes.slice(offset, Math.min(offset + chunkSize, bytes.byteLength)),
        { headers: { 'Content-Type': 'application/octet-stream' } },
      )
    }
    await cloudHttp.post(`/blobs/${initialized.data.blob_id}/complete`)
  }
  const { requires_blob: _requiresBlob, _upload_content: _uploadContent, ...safePayload } = operation.payload
  return {
    ...operation,
    payload: {
      ...safePayload,
      blob_id: initialized.data.blob_id,
    },
  }
}

async function importRemoteSourceEvents(events: SyncEvent[]): Promise<void> {
  const projects = await localHttp.get<Array<{ id: number; public_id: string }>>('/projects')
  const localProjectIds = new Map(projects.data.map((project) => [project.public_id, project.id]))
  const priority: Record<string, number> = {
    code_repository: 1,
    paper_document: 1,
    agent_conversation: 2,
    agent_run: 3,
    agent_message: 4,
    agent_run_event: 5,
    agent_memory: 6,
    trace_link: 7,
    code_edit: 8,
  }
  for (const event of [...events].sort(
    (left, right) => (priority[left.entity_type] ?? 99) - (priority[right.entity_type] ?? 99),
  )) {
    if (event.operation === 'delete' || event.entity_type === 'project') continue
    const projectPublicId = event.payload.project_public_id
    if (typeof projectPublicId !== 'string') continue
    const projectId = localProjectIds.get(projectPublicId)
    if (!projectId) continue
    if (event.entity_type === 'paper_document' || event.entity_type === 'code_repository') {
      const blobId = event.payload.blob_id
      if (typeof blobId !== 'string') continue
      const downloaded = await cloudHttp.get<ArrayBuffer>(`/blobs/${blobId}/download`, {
        responseType: 'arraybuffer',
      })
      await localHttp.put(
        `/local-sync/projects/${projectId}/imports/${event.entity_type}/${event.entity_public_id}`,
        downloaded.data,
        {
          params: {
            filename: String(event.payload.filename ?? 'cloud-import.txt'),
            version: event.entity_version,
            blob_id: blobId,
            artifact_version_id: event.payload.current_artifact_version_id,
          },
          headers: { 'Content-Type': 'application/octet-stream' },
        },
      )
    } else if (event.entity_type === 'code_edit') {
      const blobId = event.payload.blob_id
      if (typeof blobId !== 'string') continue
      const downloaded = await cloudHttp.get<ArrayBuffer>(`/blobs/${blobId}/download`, {
        responseType: 'arraybuffer',
      })
      await localHttp.put(
        `/local-sync/projects/${projectId}/imports/code-edit/${event.entity_public_id}`,
        downloaded.data,
        {
          params: {
            repository_public_id: event.payload.repository_public_id,
            file_path: event.payload.path,
            repository_revision: event.payload.repository_revision,
          },
          headers: { 'Content-Type': 'application/octet-stream' },
        },
      )
    } else if (
      ['trace_link', 'agent_conversation', 'agent_message', 'agent_run', 'agent_run_event', 'agent_memory']
        .includes(event.entity_type)
    ) {
      await localHttp.post(`/local-sync/projects/${projectId}/imports/entity`, {
        entity_type: event.entity_type,
        public_id: event.entity_public_id,
        version: event.entity_version,
        payload: event.payload,
      })
    }
  }
}

export async function enableLocalProjectSync(
  projectId: number,
  workspaceId: string,
  deviceId: string,
  agentHistorySync: boolean,
): Promise<void> {
  await localHttp.post(`/projects/${projectId}/sync/enable`, {
    workspace_id: workspaceId,
    device_id: deviceId,
    agent_history_sync: agentHistorySync,
  })
}

export async function setLocalProjectSyncMode(
  projectId: number,
  syncMode: 'cloud_enabled' | 'cloud_paused' | 'cloud_detached' | 'local_only',
): Promise<void> {
  const project = (await localHttp.get<{ public_id: string }>(`/projects/${projectId}`)).data
  const deviceMode = syncMode === 'local_only' ? 'cloud_detached' : syncMode
  if (syncMode === 'cloud_enabled') {
    await cloudHttp.patch(`/projects/${project.public_id}/device-sync`, {
      sync_mode: deviceMode,
    })
    await localHttp.patch(`/projects/${projectId}/sync`, { sync_mode: syncMode })
    return
  }
  await localHttp.patch(`/projects/${projectId}/sync`, { sync_mode: syncMode })
  try {
    await cloudHttp.patch(`/projects/${project.public_id}/device-sync`, {
      sync_mode: deviceMode,
    })
  } catch {
    // Pausing/unbinding must remain possible while offline. A later login can
    // reconcile the stale server-side device binding without uploading data.
  }
}

export async function synchronizeWorkspace(
  workspaceId: string,
  deviceId: string,
): Promise<{ pushed: number; pulled: number; conflicts: number }> {
  if (!hasLocalWorkspace) return { pushed: 0, pulled: 0, conflicts: 0 }
  const outbox = await localHttp.get<{ operations: SyncOperation[] }>('/local-sync/outbox', {
    params: { workspace_id: workspaceId },
  })
  const operations: SyncOperation[] = []
  for (const operation of outbox.data.operations) {
    operations.push(await attachBlob(operation))
  }
  let conflicts = 0
  if (operations.length) {
    const pushed = await cloudHttp.post<{ results: Array<Record<string, unknown>> }>(
      '/sync/push',
      { operations },
    )
    conflicts = pushed.data.results.filter((result) => result.status === 'conflict').length
    await localHttp.post('/local-sync/outbox/results', pushed.data)
  }
  let after = 0
  try {
    const state = await localHttp.get<{ last_pulled_seq: number }>('/local-sync/state', {
      params: { workspace_id: workspaceId },
    })
    after = state.data.last_pulled_seq
  } catch {
    after = 0
  }
  let pulledCount = 0
  let hasMore = true
  while (hasMore) {
    const pulled = await cloudHttp.get<{
      events: SyncEvent[]
      next_after: number
      has_more: boolean
    }>('/sync/pull', { params: { workspace_id: workspaceId, after, limit: 500 } })
    if (pulled.data.events.length) {
      await importRemoteSourceEvents(pulled.data.events)
      await localHttp.post('/local-sync/events', {
        workspace_id: workspaceId,
        device_id: deviceId,
        events: pulled.data.events,
      })
      pulledCount += pulled.data.events.length
      after = pulled.data.next_after
    }
    hasMore = pulled.data.has_more
  }
  await cloudHttp.post('/sync/ack', {
    workspace_id: workspaceId,
    device_id: deviceId,
    last_pulled_seq: after,
  })
  return { pushed: operations.length, pulled: pulledCount, conflicts }
}

export async function downloadCloudProjectToLocal(
  project: CloudProject,
  deviceId: string,
): Promise<number> {
  if (!hasLocalWorkspace) throw new Error('Cloud Web does not have a local project store')
  await cloudHttp.patch(`/projects/${project.public_id}/device-sync`, {
    sync_mode: 'cloud_enabled',
  })
  const bootstrapped = await cloudHttp.get<{
    projects: Array<Record<string, unknown>>
    entities: Array<{
      entity_type: string
      public_id: string
      project_public_id: string | null
      version: number
      payload: Record<string, unknown>
      deleted_at?: string | null
    }>
  }>('/sync/bootstrap', { params: { workspace_id: project.workspace_id } })
  const imported = await localHttp.post<{ id: number }>('/local-sync/projects/import', {
    workspace_id: project.workspace_id,
    device_id: deviceId,
    public_id: project.public_id,
    name: project.name,
    description: project.description,
    version: project.version,
    agent_history_sync: project.agent_history_sync,
  })
  const projectId = imported.data.id
  const priority: Record<string, number> = {
    code_repository: 1, paper_document: 1, agent_conversation: 2, agent_run: 3,
    agent_message: 4, agent_run_event: 5, agent_memory: 6, trace_link: 7, code_edit: 8,
  }
  for (const entity of [...bootstrapped.data.entities].sort(
    (left, right) => (priority[left.entity_type] ?? 99) - (priority[right.entity_type] ?? 99),
  )) {
    if (entity.project_public_id !== project.public_id) continue
    if (entity.deleted_at) continue
    if (entity.entity_type === 'paper_document' || entity.entity_type === 'code_repository') {
      const blobId = entity.payload.blob_id
      if (typeof blobId !== 'string') continue
      const downloaded = await cloudHttp.get<ArrayBuffer>(`/blobs/${blobId}/download`, {
        responseType: 'arraybuffer',
      })
      await localHttp.put(
        `/local-sync/projects/${projectId}/imports/${entity.entity_type}/${entity.public_id}`,
        downloaded.data,
        {
          params: {
            filename: String(entity.payload.filename ?? 'cloud-import.bin'),
            version: entity.version,
            blob_id: blobId,
          },
          headers: { 'Content-Type': 'application/octet-stream' },
        },
      )
    } else if (entity.entity_type === 'code_edit') {
      const blobId = entity.payload.blob_id
      if (typeof blobId !== 'string') continue
      const downloaded = await cloudHttp.get<ArrayBuffer>(`/blobs/${blobId}/download`, {
        responseType: 'arraybuffer',
      })
      await localHttp.put(
        `/local-sync/projects/${projectId}/imports/code-edit/${entity.public_id}`,
        downloaded.data,
        {
          params: {
            repository_public_id: entity.payload.repository_public_id,
            file_path: entity.payload.path,
            repository_revision: entity.payload.repository_revision,
          },
          headers: { 'Content-Type': 'application/octet-stream' },
        },
      )
    } else if (['trace_link', 'agent_conversation', 'agent_message', 'agent_run', 'agent_run_event', 'agent_memory'].includes(entity.entity_type)) {
      await localHttp.post(`/local-sync/projects/${projectId}/imports/entity`, {
        entity_type: entity.entity_type,
        public_id: entity.public_id,
        version: entity.version,
        payload: entity.payload,
      })
    }
  }
  return projectId
}
