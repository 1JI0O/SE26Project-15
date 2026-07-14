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

export function useImport(hasPaper: () => boolean, hasCode: () => boolean) {
  const importSteps = computed<ImportStepView[]>(() => [
    {
      index: '01',
      title: '导入论文 PDF',
      description: '保留原文页视图，抽取章节、段落和页码；论文区只读展示。',
      status: hasPaper() ? '已解析' : '待上传',
      tagType: hasPaper() ? 'success' : 'info',
      action: hasPaper() ? '重新上传' : '上传 PDF',
    },
    {
      index: '02',
      title: '导入代码 ZIP',
      description: '按 .gitignore 和 macOS 元数据规则过滤，生成 IDE 风格完整代码仓库树。',
      status: hasCode() ? '已分析' : '待上传',
      tagType: hasCode() ? 'success' : 'info',
      action: hasCode() ? '替换代码包' : '上传 ZIP',
    },
    {
      index: '03',
      title: '生成代码追踪视图',
      description: '基于代码静态分析输出追溯矩阵；张量流与魔改冲突仍为演示占位。',
      status: hasPaper() && hasCode() ? '追溯候选已生成' : '等待导入',
      tagType: hasPaper() && hasCode() ? 'success' : 'warning',
      action: '',
    },
  ])

  return { importSteps }
}
