<template>
  <section class="insight-dock">
    <nav class="insight-nav">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        :class="{ active: activeTab === tab.key }"
        @click="$emit('update:activeTab', tab.key)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <slot />
  </section>
</template>

<script setup lang="ts">
export interface InsightTab {
  key: string
  label: string
}

defineProps<{
  tabs: InsightTab[]
  activeTab: string
}>()

defineEmits<{
  'update:activeTab': [key: string]
}>()
</script>

<style scoped>
.insight-dock {
  overflow: hidden;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.insight-nav {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid #dce3ea;
  background: #fbfcfd;
}

.insight-nav button {
  padding: 9px 12px;
  border: 0;
  border-radius: 6px;
  background: #ffffff;
  color: #536475;
  cursor: pointer;
  font: inherit;
}

.insight-nav button.active {
  background: #1f8f78;
  color: #ffffff;
}
</style>
