<template>
  <el-dialog
    :model-value="annotation.formVisible"
    title="追加追溯关系"
    width="620px"
    :close-on-click-modal="false"
    :close-on-press-escape="!annotation.submitting"
    @close="annotation.cancel()"
  >
    <div class="annotation-dialog">
      <div class="selection-preview">
        <div class="preview-item">
          <div class="preview-label">论文</div>
          <div class="preview-ref">{{ annotation.paperPick?.ref }}</div>
          <div class="preview-text">{{ annotation.paperPick?.preview }}</div>
        </div>
        <div class="preview-item">
          <div class="preview-label">代码</div>
          <div class="preview-ref">{{ annotation.codePick?.ref }}</div>
          <pre class="preview-code">{{ annotation.codePick?.preview }}</pre>
        </div>
      </div>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="88px"
        class="annotation-form"
        @submit.prevent
      >
        <el-form-item label="关系类型" prop="relationType">
          <el-select v-model="form.relationType">
            <el-option
              v-for="option in RELATION_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="置信度" prop="confidence">
          <el-slider v-model="form.confidence" :min="0" :max="100" :step="5" show-input />
        </el-form-item>

        <el-form-item label="描述" prop="rationale">
          <el-input
            v-model="form.rationale"
            type="textarea"
            :rows="4"
            placeholder="说明这条追溯关系的依据"
            maxlength="5000"
            show-word-limit
          />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button text @click="annotation.backToCode()">上一步</el-button>
      <el-button @click="annotation.cancel()">取消</el-button>
      <el-button type="primary" :loading="annotation.submitting" @click="create">创建</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { useAnnotationStore } from '@/stores/annotation'
import type { TraceRelationType } from '@/types/tracing'

const annotation = useAnnotationStore()
const route = useRoute()
const projectId = computed(() => Number(route.params.id))

const RELATION_OPTIONS: Array<{ value: TraceRelationType; label: string }> = [
  { value: 'implements', label: '实现 (implements)' },
  { value: 'computes', label: '计算 (computes)' },
  { value: 'defines', label: '定义 (defines)' },
  { value: 'constrains', label: '约束 (constrains)' },
  { value: 'updates', label: '更新 (updates)' },
  { value: 'configures', label: '配置 (configures)' },
  { value: 'invokes', label: '调用 (invokes)' },
  { value: 'tests', label: '测试 (tests)' },
  { value: 'mentions', label: '提及 (mentions)' },
]

interface FormData {
  relationType: TraceRelationType
  confidence: number
  rationale: string
}

const formRef = ref<FormInstance>()
const form = ref<FormData>({ relationType: 'implements', confidence: 80, rationale: '' })

// Non-empty only. A length floor was in the way during debugging and buys nothing: the field
// is free-form prose that no downstream consumer parses.
const rules: FormRules<FormData> = {
  relationType: [{ required: true, message: '请选择关系类型', trigger: 'change' }],
  rationale: [{ required: true, message: '请填写描述', trigger: 'blur' }],
}

watch(
  () => annotation.formVisible,
  (visible) => {
    if (!visible) return
    form.value = { relationType: 'implements', confidence: 80, rationale: '' }
    formRef.value?.clearValidate()
  },
)

async function create(): Promise<void> {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return // Field-level messages already rendered.
  }
  try {
    const traceId = await annotation.submit(projectId.value, {
      relationType: form.value.relationType,
      confidence: form.value.confidence,
      rationale: form.value.rationale,
    })
    ElMessage.success('追溯关系已追加')
    // The matrix flashes the new row and the workspace reloads trace data.
    window.dispatchEvent(new CustomEvent('trace-link-created', { detail: { traceId } }))
  } catch (cause) {
    const detail =
      (cause as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? ''
    ElMessage.error(detail || '创建失败，请重试')
    console.error(cause)
  }
}
</script>

<style scoped>
.annotation-dialog {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.selection-preview {
  display: grid;
  gap: 12px;
  padding: 12px;
  border-radius: 4px;
  background: #f5f7fa;
}

.preview-item {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.preview-label {
  color: #909399;
  font-size: 12px;
}

.preview-ref {
  color: #1f8f78;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.preview-text {
  display: -webkit-box;
  max-height: 66px;
  overflow: hidden;
  color: #55636e;
  font-size: 13px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.preview-code {
  max-height: 108px;
  margin: 0;
  overflow: auto;
  color: #55636e;
  font-family: "SFMono-Regular", Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
}
</style>
