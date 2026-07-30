import { cloudHttp, hasLocalWorkspace, localHttp } from '@/api/http'
import type { SyncEvent, SyncOperation } from '@/types/cloud'
import type { CloudProject } from '@/types/cloud'

async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
}

async function uploadBlobBytes(
  bytes: ArrayBuffer,
  filename: string,
  mimeType: string,
  workspaceId: string,
  projectPublicId: string,
): Promise<string> {
  const initialized = await cloudHttp.post<{
    blob_id: string
    status: 'upload' | 'reuse'
    chunk_size: number
    uploaded_bytes: number
  }>('/blobs/upload-init', {
    workspace_id: workspaceId,
    project_public_id: projectPublicId,
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
  return initialized.data.blob_id
}

async function attachBlob(operation: SyncOperation): Promise<SyncOperation> {
  let payload = operation.payload
  // Upload the primary code/PDF blob if not yet on the cloud.
  if (payload.requires_blob) {
    const response = await localHttp.get<ArrayBuffer>(
      `/local-sync/blobs/${operation.entity_type}/${operation.entity_public_id}`,
      { responseType: 'arraybuffer' },
    )
    const bytes = response.data
    const filename = String(payload.filename ?? 'upload.bin')
    const mimeType = filename.toLowerCase().endsWith('.pdf')
      ? 'application/pdf'
      : filename.toLowerCase().endsWith('.zip')
        ? 'application/zip'
        : 'application/octet-stream'
    const blobId = await uploadBlobBytes(
      bytes,
      filename,
      mimeType,
      operation.workspace_id,
      String(payload.project_public_id),
    )
    const { requires_blob: _r, _upload_content: _u, ...rest } = payload
    payload = { ...rest, blob_id: blobId }
  }
  // Upload the generated flow diagram (tensor graph + analysis) for code repos.
  // The diagram can be hundreds of KB, so it travels as its own cloud blob.
  if (payload.requires_diagram_blob) {
    const response = await localHttp.get<ArrayBuffer>(
      `/local-sync/diagram/${operation.entity_public_id}`,
      { responseType: 'arraybuffer' },
    )
    const diagramBlobId = await uploadBlobBytes(
      response.data,
      `${operation.entity_public_id}-diagram.json`,
      'application/json',
      operation.workspace_id,
      String(payload.project_public_id),
    )
    const { requires_diagram_blob: _rd, ...rest2 } = payload
    payload = { ...rest2, diagram_blob_id: diagramBlobId }
  }
  return { ...operation, payload }
}

async function importDiagramBlob(
  entityType: string,
  payload: Record<string, unknown>,
  projectId: number,
  publicId: string,
): Promise<void> {
  if (entityType !== 'code_repository') return
  const diagramBlobId = payload.diagram_blob_id
  if (typeof diagramBlobId !== 'string') return
  try {
    const diagram = await cloudHttp.get<ArrayBuffer>(`/blobs/${diagramBlobId}/download`, {
      responseType: 'arraybuffer',
    })
    await localHttp.put(
      `/local-sync/projects/${projectId}/diagram-imports/${publicId}`,
      diagram.data,
      { headers: { 'Content-Type': 'application/json' } },
    )
  } catch {
    // A missing/failed diagram must not abort the whole import. The base graph
    // was already rebuilt from the code archive on import; the diagram is an
    // enhancement layer.
  }
}

/**
 * Import order. Anchors (paper_target/code_target) must land before trace_link: a relation
 * resolves its target references through the target's public id, and an unresolved reference
 * is dropped rather than retried. Anchors in turn need their paper/repository to exist first.
 *
 * Shared by the incremental pull and the first-time bootstrap download — these were separate
 * copies, which is how the two paths drifted apart as new entity types were added.
 */
const IMPORT_PRIORITY: Record<string, number> = {
  code_repository: 1,
  paper_document: 1,
  paper_target: 2,
  code_target: 2,
  agent_conversation: 3,
  agent_run: 4,
  agent_message: 5,
  agent_run_event: 6,
  agent_memory: 7,
  trace_link: 8,
  code_edit: 9,
}

/** Entity types imported as a JSON payload rather than a downloaded blob. */
const PAYLOAD_ENTITY_TYPES = [
  'paper_target',
  'code_target',
  'trace_link',
  'agent_conversation',
  'agent_message',
  'agent_run',
  'agent_run_event',
  'agent_memory',
]

async function importRemoteSourceEvents(events: SyncEvent[]): Promise<void> {
  const projects = await localHttp.get<Array<{ id: number; public_id: string }>>('/projects')
  const localProjectIds = new Map(projects.data.map((project) => [project.public_id, project.id]))
  const priority = IMPORT_PRIORITY
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
      // Restore the generated flow diagram after the repository exists locally.
      await importDiagramBlob(event.entity_type, event.payload, projectId, event.entity_public_id)
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
    } else if (PAYLOAD_ENTITY_TYPES.includes(event.entity_type)) {
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

/**
 * Marker key for the one-shot repair below. Bumping the suffix re-runs the backfill, which is
 * what a future protocol extension should do rather than adding a second marker.
 */
const BACKFILL_MARKER = 'tracelab_sync_backfill_targets_v1'

/**
 * Repair projects enabled before the protocol covered anchors and the full trace payload.
 *
 * Nothing re-touches an unchanged entity, so an old project's missing paper_target/code_target
 * and its truncated cloud trace_link copy would stay wrong forever. This re-enqueues them once
 * per workspace per install; the marker keeps a normal sync from re-queuing the same history
 * on every run.
 *
 * Failure is non-fatal: a workspace that cannot be repaired right now should still sync.
 */
async function backfillIncompleteSyncOnce(workspaceId: string): Promise<void> {
  const marker = `${BACKFILL_MARKER}:${workspaceId}`
  if (localStorage.getItem(marker)) return
  try {
    await localHttp.post('/local-sync/backfill', null, { params: { workspace_id: workspaceId } })
    localStorage.setItem(marker, new Date().toISOString())
  } catch {
    // Leave the marker unset so the next sync retries.
  }
}

async function pushOperations(operations: SyncOperation[]): Promise<number> {
  if (!operations.length) return 0
  const pushed = await cloudHttp.post<{ results: Array<Record<string, unknown>> }>(
    '/sync/push',
    { operations },
  )
  await localHttp.post('/local-sync/outbox/results', pushed.data)
  return pushed.data.results.filter((result) => result.status === 'conflict').length
}

async function ensureDeviceBindings(workspaceId: string): Promise<void> {
  // Re-bind the current device to every locally-enabled project that already
  // exists on the cloud. A project op push also creates the binding, but only
  // when there is a pending project op — a project whose metadata is already
  // synced would otherwise have no binding for a newly-adopted device, so its
  // blob uploads would 409. Best-effort: a project not yet on the cloud has no
  // record to bind and its first project push will create the binding.
  const projects = await localHttp.get<
    Array<{ public_id: string; sync_mode: string; cloud_workspace_id: string | null }>
  >('/projects')
  for (const project of projects.data) {
    if (project.sync_mode !== 'cloud_enabled') continue
    if (project.cloud_workspace_id !== workspaceId) continue
    try {
      await cloudHttp.patch(`/projects/${project.public_id}/device-sync`, {
        sync_mode: 'cloud_enabled',
      })
    } catch {
      // Project not yet on the cloud (404) or transient failure — the project
      // push will establish the binding.
    }
  }
}

export async function synchronizeWorkspace(
  workspaceId: string,
  deviceId: string,
): Promise<{ pushed: number; pulled: number; conflicts: number }> {
  if (!hasLocalWorkspace) return { pushed: 0, pulled: 0, conflicts: 0 }
  // Device ids rotate across logins (a fresh login without a persisted id mints
  // a new device). A local install must always sync as its CURRENT auth device,
  // so realign the workspace's local sync state + any pending outbox ops to it.
  // When the device actually changed, also (re)establish the cloud device
  // binding for every enabled project — blob upload-init (409) and push (403)
  // both reject operations from a device that is not bound to the project.
  const adopted = await localHttp.post<{ changed: boolean }>('/local-sync/device/adopt', {
    workspace_id: workspaceId,
    device_id: deviceId,
  })
  if (adopted.data.changed) await ensureDeviceBindings(workspaceId)
  await backfillIncompleteSyncOnce(workspaceId)
  // Drain the outbox in batches. The local backend returns at most 100 pending
  // ops per read, so a project with a long history (e.g. hundreds of agent run
  // events) needs several rounds. Loop until nothing pending remains so a single
  // sync fully clears the workspace instead of leaving it "待同步". The round cap
  // bounds the loop if new ops are produced faster than they push (agent still
  // running); the remainder drains on the next sync.
  let pushedCount = 0
  let conflicts = 0
  for (let round = 0; round < 200; round += 1) {
    const outbox = await localHttp.get<{ operations: SyncOperation[] }>('/local-sync/outbox', {
      params: { workspace_id: workspaceId },
    })
    const operations = outbox.data.operations
    if (!operations.length) break
    // The CloudProject must exist server-side before any blob upload-init or
    // child-entity push: the server rejects uploads for an unknown project.
    // attachBlob() calls the cloud, so push project operations first, then attach
    // blobs and push the remaining operations.
    const projectOps = operations.filter((op) => op.entity_type === 'project')
    const childOps = operations.filter((op) => op.entity_type !== 'project')
    conflicts += await pushOperations(projectOps)
    const preparedChildOps: SyncOperation[] = []
    for (const operation of childOps) {
      preparedChildOps.push(await attachBlob(operation))
    }
    conflicts += await pushOperations(preparedChildOps)
    pushedCount += projectOps.length + preparedChildOps.length
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
  return { pushed: pushedCount, pulled: pulledCount, conflicts }
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
  const priority = IMPORT_PRIORITY
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
      await importDiagramBlob(entity.entity_type, entity.payload, projectId, entity.public_id)
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
    } else if (PAYLOAD_ENTITY_TYPES.includes(entity.entity_type)) {
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
