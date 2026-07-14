import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getProject } from '@/api/project-api'

export function useWorkspace() {
  const route = useRoute()
  const projectId = computed(() => Number(route.params.id))
  const projectIdLabel = computed(() => String(route.params.id ?? ''))
  const projectName = ref('加载中...')
  const loadingWorkspace = ref(false)
  const error = ref<string | null>(null)

  async function loadProject(): Promise<void> {
    if (!projectId.value || Number.isNaN(projectId.value)) return
    try {
      const project = await getProject(projectId.value)
      projectName.value = project.name
    } catch (e) {
      ElMessage.error('加载项目信息失败')
      console.error(e)
      error.value = '加载项目信息失败'
    }
  }

  return {
    projectId,
    projectIdLabel,
    projectName,
    loadingWorkspace,
    error,
    loadProject,
  }
}
