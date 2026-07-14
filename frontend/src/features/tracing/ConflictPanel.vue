<template>
  <div class="conflict-grid">
    <article v-for="item in items" :key="item.title" class="conflict-card">
      <div>
        <el-tag :type="item.type" effect="plain">{{ item.level }}</el-tag>
        <h2>{{ item.title }}</h2>
      </div>
      <p>{{ item.description }}</p>
      <button>查看影响范围</button>
    </article>
  </div>
</template>

<script setup lang="ts">
import type { TagType } from '@/composables/useCode'

defineProps<{
  items: Array<{
    level: string
    type: TagType
    title: string
    description: string
  }>
}>()
</script>

<style scoped>
.conflict-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 16px;
}

.conflict-card {
  display: grid;
  gap: 14px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.conflict-card h2 {
  margin: 0;
}

.conflict-card p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

.conflict-card button {
  justify-self: start;
  padding: 8px 10px;
  border: 0;
  border-radius: 6px;
  background: #eef3f2;
  color: #1f8f78;
  cursor: pointer;
  font: inherit;
}

@media (max-width: 820px) {
  .conflict-grid {
    grid-template-columns: 1fr;
  }
}
</style>
