import { defineStore } from 'pinia'

import { extractErrorDetail, localHttp } from '@/api/http'
import { deleteCloudProject, listCloudProjects } from '@/api/cloud-project-api'
import { getProject, updateProject } from '@/api/project-api'
import {
  enableLocalProjectSync,
  setLocalProjectSyncMode,
  synchronizeWorkspace,
} from '@/services/sync-client'
import { useAuthStore } from '@/stores/auth'
import type { CloudProject, SyncOperation } from '@/types/cloud'

export const useSyncStore = defineStore('cloud-sync', {
  state: () => ({
    syncing: false,
    // The public_id the user explicitly triggered a sync for, so only that
    // project's row shows "正在同步" (a sync is workspace-wide under the hood, but
    // the UI scopes the spinner to the clicked project). Null for background /
    // workspace-level syncs that are not tied to a single row.
    activeSyncPublicId: null as string | null,
    lastSyncedAt: '' as string,
    lastError: '' as string,
    conflictCount: 0,
    // public_ids of local cloud-projects with pending (not-yet-pushed) outbox
    // operations. Drives the "待同步 / 已同步" status labels on the home page.
    pendingProjectPublicIds: [] as string[],
    // Cloud projects for the current workspace, used to surface "cloud-only"
    // projects (not yet downloaded to this device) on the merged home page.
    cloudProjects: [] as CloudProject[],
  }),
  actions: {
    async sync(focusPublicId?: string) {
      const auth = useAuthStore()
      if (!auth.workspace || !auth.deviceId || !auth.verified) return
      // A sync is workspace-wide (it drains the whole outbox), so a second
      // concurrent run would push the same operations again — racing the server's
      // per-operation receipt insert and causing duplicate-key 500s. Serialize:
      // if a sync is already in flight, this click is a no-op (the running sync
      // already covers every project's pending work).
      if (this.syncing) return
      this.syncing = true
      this.activeSyncPublicId = focusPublicId ?? null
      this.lastError = ''
      try {
        const result = await synchronizeWorkspace(auth.workspace.workspace_id, auth.deviceId)
        await this.refreshConflicts()
        await this.refreshPending()
        await this.refreshCloudProjects()
        this.lastSyncedAt = new Date().toISOString()
        return result
      } catch (error) {
        this.lastError = extractErrorDetail(error, '云同步失败')
        throw error
      } finally {
        this.syncing = false
        this.activeSyncPublicId = null
      }
    },
    async refreshPending() {
      const auth = useAuthStore()
      if (!auth.workspace) {
        this.pendingProjectPublicIds = []
        return
      }
      try {
        const { data } = await localHttp.get<{ operations: SyncOperation[] }>(
          '/local-sync/outbox',
          { params: { workspace_id: auth.workspace.workspace_id } },
        )
        const ids = new Set<string>()
        for (const op of data.operations) {
          const pid =
            op.entity_type === 'project'
              ? op.entity_public_id
              : (op.payload?.project_public_id as string | undefined)
          if (typeof pid === 'string') ids.add(pid)
        }
        this.pendingProjectPublicIds = [...ids]
      } catch {
        this.pendingProjectPublicIds = []
      }
    },
    async refreshCloudProjects() {
      const auth = useAuthStore()
      if (!auth.workspace || !auth.verified) {
        this.cloudProjects = []
        return
      }
      try {
        this.cloudProjects = await listCloudProjects(auth.workspace.workspace_id)
      } catch {
        this.cloudProjects = []
      }
    },
    projectStatus(project: {
      public_id: string
      sync_mode: string
      cloud_workspace_id?: string | null
    }): 'local' | 'syncing' | 'pending' | 'synced' {
      const auth = useAuthStore()
      if (
        !auth.workspace ||
        (project.cloud_workspace_id &&
          project.cloud_workspace_id !== auth.workspace.workspace_id)
      ) {
        return 'local'
      }
      if (project.sync_mode === 'local_only' || project.sync_mode === 'cloud_detached') {
        return 'local'
      }
      // Only the row the user actually triggered shows the syncing spinner; the
      // rest keep their last-known pending/synced label during a workspace sync.
      if (this.syncing && this.activeSyncPublicId === project.public_id) return 'syncing'
      if (this.pendingProjectPublicIds.includes(project.public_id)) return 'pending'
      return 'synced'
    },
    async refreshConflicts() {
      const auth = useAuthStore()
      if (!auth.workspace) {
        this.conflictCount = 0
        return []
      }
      const response = await localHttp.get<Array<Record<string, unknown>>>(
        '/local-sync/conflicts',
        { params: { workspace_id: auth.workspace.workspace_id } },
      )
      this.conflictCount = response.data.length
      return response.data
    },
    async enable(projectId: number, agentHistorySync: boolean) {
      const auth = useAuthStore()
      if (!auth.workspace || !auth.deviceId || !auth.verified) {
        throw new Error('请先登录并验证邮箱')
      }
      await enableLocalProjectSync(
        projectId,
        auth.workspace.workspace_id,
        auth.deviceId,
        agentHistorySync,
      )
      return this.sync()
    },
    // 需求 3.3 "覆盖云端": delete the conflicting cloud project (tombstone), then
    // enable the local one. The local project keeps its own public_id and its
    // content becomes the authoritative cloud copy.
    async overwriteCloudWithLocal(
      projectId: number,
      cloudPublicId: string,
      agentHistorySync: boolean,
    ) {
      const auth = useAuthStore()
      if (!auth.workspace || !auth.deviceId || !auth.verified) {
        throw new Error('请先登录并验证邮箱')
      }
      const target = this.cloudProjects.find((item) => item.public_id === cloudPublicId)
      if (target) await deleteCloudProject(target)
      await this.refreshCloudProjects()
      return this.enable(projectId, agentHistorySync)
    },
    // 需求 3.3 "创建副本": rename the local project so it no longer collides,
    // then enable it as a brand-new cloud project (fresh public_id).
    async enableAsCopy(projectId: number, agentHistorySync: boolean) {
      const local = await updateProject(projectId, {
        name: `${(await getProject(projectId)).name}（副本）`,
      })
      void local
      return this.enable(projectId, agentHistorySync)
    },
    async setMode(
      projectId: number,
      mode: 'cloud_enabled' | 'cloud_paused' | 'cloud_detached' | 'local_only',
    ) {
      await setLocalProjectSyncMode(projectId, mode)
      if (mode !== 'local_only') await this.sync()
    },
  },
})
