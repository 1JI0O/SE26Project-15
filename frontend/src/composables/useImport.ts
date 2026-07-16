import { computed, ref } from 'vue'
import type { TagType } from './useCode'

export interface ImportStepView {
  index: string
  title: string
  description: string
  status: string
  tagType: TagType
  action: string
}

type AnalysisStatus = 'missing' | 'pending' | 'queued' | 'running' | 'ready' | 'failed' | 'stale'

export function useImport(
  hasPaper: () => boolean,
  hasCode: () => boolean,
  analysisStatus: () => AnalysisStatus,
) {
  const codeStatus = computed(() => {
    if (!hasCode()) return { label: '待上传', type: 'info' as TagType }
    if (analysisStatus() === 'ready') return { label: '已分析', type: 'success' as TagType }
    if (analysisStatus() === 'failed') return { label: '分析失败', type: 'danger' as TagType }
    return { label: '后台分析中', type: 'warning' as TagType }
  })
  const importSteps = computed<ImportStepView[]>(() => [
    {
      index: '01',
      title: '导入论文 PDF',
      description: '读取 MinerU 结构化 Markdown、章节、公式、表格和图片；论文区只读展示。',
      status: hasPaper() ? '已解析' : '待上传',
      tagType: hasPaper() ? 'success' : 'info',
      action: hasPaper() ? '重新上传' : '上传 PDF',
    },
    {
      index: '02',
      title: '导入代码 ZIP',
      description: '按 .gitignore 和 macOS 元数据规则过滤，生成 IDE 风格完整代码仓库树。',
      status: codeStatus.value.label,
      tagType: codeStatus.value.type,
      action: hasCode() ? '替换代码包' : '上传 ZIP',
    },
    {
      index: '03',
      title: '生成代码追踪视图',
      description: '基于静态分析生成张量流和追溯候选；魔改冲突保留接口演示。',
      status: hasPaper() && hasCode() && analysisStatus() === 'ready'
        ? '追溯候选已生成'
        : hasPaper() && hasCode()
          ? '等待代码分析'
          : '等待导入',
      tagType: hasPaper() && hasCode() && analysisStatus() === 'ready' ? 'success' : 'warning',
      action: '',
    },
  ])

  return { importSteps }
}
