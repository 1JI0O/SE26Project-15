<template>
  <el-dialog
    v-model="visible"
    title="创建追溯关系"
    width="600px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <div class="annotation-dialog">
      <!-- Selected References Preview -->
      <div class="selection-preview">
        <div class="preview-item">
          <div class="preview-label">论文块</div>
          <div class="preview-content">{{ paperRef }}</div>
          <div v-if="paperPreview" class="preview-text">{{ paperPreview }}</div>
        </div>
        <div class="preview-item">
          <div class="preview-label">代码符号</div>
          <div class="preview-content">{{ codeRef }}</div>
          <div v-if="codePreview" class="preview-text">{{ codePreview }}</div>
        </div>
      </div>

      <!-- Form -->
      <el-form :model="form" :rules="rules" ref="formRef" label-width="100px" class="annotation-form">
        <el-form-item label="关系类型" prop="relationType">
          <el-select v-model="form.relationType" placeholder="选择关系类型">
            <el-option label="实现 (implements)" value="implements" />
            <el-option label="计算 (computes)" value="computes" />
            <el-option label="定义 (defines)" value="defines" />
            <el-option label="约束 (constrains)" value="constrains" />
            <el-option label="更新 (updates)" value="updates" />
            <el-option label="配置 (configures)" value="configures" />
            <el-option label="调用 (invokes)" value="invokes" />
            <el-option label="测试 (tests)" value="tests" />
            <el-option label="提及 (mentions)" value="mentions" />
          </el-select>
        </el-form-item>

        <el-form-item label="置信度" prop="confidence">
          <el-slider v-model="form.confidence" :min="0" :max="100" :step="5" show-input />
          <div class="confidence-hint">当前置信度: {{ form.confidence }}%</div>
        </el-form-item>

        <el-form-item label="理由说明" prop="rationale">
          <el-input
            v-model="form.rationale"
            type="textarea"
            :rows="4"
            placeholder="请说明建立此追溯关系的理由（至少20字）"
            maxlength="5000"
            show-word-limit
          />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <span class="dialog-footer">
        <el-button @click="handleClose">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAnnotationStore } from '@/stores/annotation'
import type { TraceRelationType } from '@/types/tracing'

const annotationStore = useAnnotationStore()

const visible = computed({
  get: () => annotationStore.dialogVisible,
  set: (val) => {
    if (!val) {
      annotationStore.dialogVisible = false
    }
  },
})

const paperRef = computed(() => annotationStore.selectedPaperRef)
const codeRef = computed(() => annotationStore.selectedCodeRef)

// TODO: Fetch actual preview content from workspace state
const paperPreview = ref<string>('')
const codePreview = ref<string>('')

const formRef = ref<FormInstance>()
const creating = ref(false)

interface FormData {
  relationType: TraceRelationType
  confidence: number
  rationale: string
}

const form = ref<FormData>({
  relationType: 'implements',
  confidence: 80,
  rationale: '',
})

const rules: FormRules<FormData> = {
  relationType: [{ required: true, message: '请选择关系类型', trigger: 'change' }],
  confidence: [
    { required: true, message: '请设置置信度', trigger: 'change' },
    { type: 'number', min: 0, max: 100, message: '置信度范围为0-100', trigger: 'change' },
  ],
  rationale: [
    { required: true, message: '请填写理由说明', trigger: 'blur' },
    { min: 20, message: '理由说明至少需要20个字符', trigger: 'blur' },
  ],
}

// Reset form when dialog opens
watch(visible, (newVal) => {
  if (newVal) {
    form.value = {
      relationType: 'implements',
      confidence: 80,
      rationale: '',
    }
    formRef.value?.clearValidate()
  }
})

const handleClose = () => {
  visible.value = false
}

const handleCreate = async () => {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
    creating.value = true

    const result = await annotationStore.createManualTraceLink({
      relationType: form.value.relationType,
      confidence: form.value.confidence,
      rationale: form.value.rationale,
    })

    ElMessage.success('追溯关系已创建')

    // Emit event to refresh trace matrix
    window.dispatchEvent(new CustomEvent('trace-link-created', { detail: result }))

    visible.value = false
  } catch (error: any) {
    if (error.errors) {
      // Validation error
      return
    }
    ElMessage.error('创建失败: ' + (error.message || '未知错误'))
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.annotation-dialog {
  .selection-preview {
    margin-bottom: 24px;
    padding: 16px;
    background: #f5f7fa;
    border-radius: 4px;

    .preview-item {
      margin-bottom: 12px;

      &:last-child {
        margin-bottom: 0;
      }

      .preview-label {
        font-size: 12px;
        color: #909399;
        margin-bottom: 4px;
      }

      .preview-content {
        font-size: 14px;
        font-weight: 500;
        color: #303133;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        margin-bottom: 4px;
      }

      .preview-text {
        font-size: 13px;
        color: #606266;
        line-height: 1.5;
        max-height: 60px;
        overflow: hidden;
        text-overflow: ellipsis;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
      }
    }
  }

  .annotation-form {
    .confidence-hint {
      font-size: 12px;
      color: #909399;
      margin-top: 8px;
    }
  }
}
</style>
