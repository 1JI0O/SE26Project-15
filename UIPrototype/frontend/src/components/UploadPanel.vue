<template>
  <section class="upload-grid">
    <div class="upload-box">
      <div>
        <h3>论文 PDF</h3>
        <p>上传后端会解析标题、摘要、章节、段落和页码。</p>
      </div>
      <input type="file" accept="application/pdf" @change="onPaperSelected" />
      <el-button :loading="paperLoading" type="primary" @click="submitPaper">上传并解析</el-button>
    </div>

    <div class="upload-box">
      <div>
        <h3>代码 ZIP</h3>
        <p>上传后端会分析文件树、类、函数、导入关系和 PyTorch 候选。</p>
      </div>
      <input type="file" accept=".zip,application/zip" @change="onCodeSelected" />
      <el-button :loading="codeLoading" type="primary" @click="submitCode">上传并分析</el-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { ref } from 'vue'

import { uploadCode, uploadPaper } from '@/api/projects'

const props = defineProps<{
  projectId: number
}>()

const emit = defineEmits<{
  uploaded: []
}>()

const paperFile = ref<File | null>(null)
const codeFile = ref<File | null>(null)
const paperLoading = ref(false)
const codeLoading = ref(false)

// Keep paper parsing and code analysis upload flows independent.
function onPaperSelected(event: Event) {
  const input = event.target as HTMLInputElement
  paperFile.value = input.files?.[0] ?? null
}

function onCodeSelected(event: Event) {
  const input = event.target as HTMLInputElement
  codeFile.value = input.files?.[0] ?? null
}

async function submitPaper() {
  if (!paperFile.value) {
    ElMessage.warning('请先选择 PDF 文件')
    return
  }
  paperLoading.value = true
  try {
    await uploadPaper(props.projectId, paperFile.value)
    ElMessage.success('论文解析完成')
    emit('uploaded')
  } finally {
    paperLoading.value = false
  }
}

async function submitCode() {
  if (!codeFile.value) {
    ElMessage.warning('请先选择 ZIP 文件')
    return
  }
  codeLoading.value = true
  try {
    await uploadCode(props.projectId, codeFile.value)
    ElMessage.success('代码分析完成')
    emit('uploaded')
  } finally {
    codeLoading.value = false
  }
}
</script>

<style scoped>
.upload-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.upload-box {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

.upload-box h3 {
  margin: 0 0 4px;
  font-size: 16px;
}

.upload-box p {
  margin: 0;
  color: #667789;
  line-height: 1.6;
}

input {
  width: 100%;
}

@media (max-width: 780px) {
  .upload-grid {
    grid-template-columns: 1fr;
  }
}
</style>

