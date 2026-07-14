<template>
  <section class="import-strip">
    <article v-for="item in steps" :key="item.index" class="import-card">
      <div>
        <span class="step-index">{{ item.index }}</span>
        <h2>{{ item.title }}</h2>
        <p>{{ item.description }}</p>
      </div>
      <div class="step-footer">
        <el-tag :type="item.tagType" effect="plain">{{ item.status }}</el-tag>
        <el-button
          v-if="item.action"
          type="primary"
          plain
          :loading="loadingMap[item.index]"
          @click="$emit('action', item.index)"
        >
          {{ item.action }}
        </el-button>
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import type { ImportStepView } from '@/composables/useImport'

defineProps<{
  steps: ImportStepView[]
  loadingMap: Record<string, boolean>
}>()

defineEmits<{
  action: [stepIndex: string]
}>()
</script>

<style scoped>
.import-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.import-card {
  display: grid;
  gap: 16px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.step-index {
  color: #1f8f78;
  font-size: 12px;
  font-weight: 700;
}

.import-card h2 {
  margin: 4px 0 0;
  font-size: 17px;
}

.import-card p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.step-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

@media (max-width: 820px) {
  .import-strip {
    grid-template-columns: 1fr;
  }

  .step-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
