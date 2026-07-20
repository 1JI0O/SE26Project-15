import { defineStore } from 'pinia'

import { localHttp } from '@/api/http'
import {
  enableLocalProjectSync,
  setLocalProjectSyncMode,
  synchronizeWorkspace,
} from '@/services/sync-client'
import { useAuthStore } from '@/stores/auth'

export const useSyncStore = defineStore('cloud-sync', {
  state: () => ({
    syncing: false,
    lastSyncedAt: '' as string,
    lastError: '' as string,
    conflictCount: 0,
  }),
  actions: {
    async sync() {
      const auth = useAuthStore()
      if (!auth.workspace || !auth.deviceId || !auth.verified) return
      this.syncing = true
      this.lastError = ''
      try {
        const result = await synchronizeWorkspace(auth.workspace.workspace_id, auth.deviceId)
        await this.refreshConflicts()
        this.lastSyncedAt = new Date().toISOString()
        return result
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : '云同步失败'
        throw error
      } finally {
        this.syncing = false
      }
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
    async setMode(
      projectId: number,
      mode: 'cloud_enabled' | 'cloud_paused' | 'cloud_detached' | 'local_only',
    ) {
      await setLocalProjectSyncMode(projectId, mode)
      if (mode !== 'local_only') await this.sync()
    },
  },
})
