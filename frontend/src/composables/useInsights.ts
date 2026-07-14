import { ref } from 'vue'
import {
  getWorkspaceConflicts,
  getWorkspaceReportSummary,
} from '@/api/workspace-api'
import type { WorkspaceConflictItem, WorkspaceReportCard } from '@/types/workspace'

export function useInsights(projectId: () => number) {
  const conflictItems = ref<WorkspaceConflictItem[]>([])
  const reportCards = ref<WorkspaceReportCard[]>([])
  const loading = ref(false)

  async function loadInsights(): Promise<void> {
    loading.value = true
    try {
      const [conflicts, report] = await Promise.all([
        getWorkspaceConflicts(projectId()),
        getWorkspaceReportSummary(projectId()),
      ])
      conflictItems.value = conflicts
      reportCards.value = report
    } finally {
      loading.value = false
    }
  }

  return { conflictItems, reportCards, loading, loadInsights }
}
