import { ref } from 'vue'
import { getWorkspaceConflicts } from '@/api/workspace-api'
import type { WorkspaceConflictItem } from '@/types/workspace'

export function useInsights(projectId: () => number) {
  const conflictItems = ref<WorkspaceConflictItem[]>([])
  const loading = ref(false)

  async function loadInsights(): Promise<void> {
    loading.value = true
    try {
      conflictItems.value = await getWorkspaceConflicts(projectId())
    } finally {
      loading.value = false
    }
  }

  return { conflictItems, loading, loadInsights }
}
