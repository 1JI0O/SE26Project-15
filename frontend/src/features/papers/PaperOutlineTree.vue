<template>
  <nav class="paper-outline" aria-label="论文章节目录">
    <div v-if="!sections.length" class="outline-empty">解析完成后显示章节目录</div>
    <template v-for="(section, index) in sections" :key="section.id">
      <div
        v-if="isVisible(index)"
        :class="['outline-row', { active: section.id === activeSectionId }]"
        :style="{ paddingLeft: `${8 + Math.max(0, section.level - 1) * 12}px` }"
      >
        <button
          v-if="hasChildren(index)"
          class="collapse-button"
          :aria-label="collapsed.has(section.id) ? '展开章节' : '折叠章节'"
          @click.stop="toggle(section.id)"
        >
          {{ collapsed.has(section.id) ? '›' : '⌄' }}
        </button>
        <span v-else class="collapse-placeholder" />
        <button class="section-button" :title="section.title" @click="$emit('select', section.id)">
          <span>{{ section.title }}</span>
          <small v-if="section.page">p.{{ section.page }}</small>
        </button>
      </div>
    </template>
  </nav>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { WorkspacePaperSection } from '@/types/papers'

const props = defineProps<{
  sections: WorkspacePaperSection[]
  activeSectionId: string
}>()

defineEmits<{ select: [sectionId: string] }>()

const collapsed = ref(new Set<string>())

function hasChildren(index: number): boolean {
  return Boolean(props.sections[index + 1]?.level > props.sections[index].level)
}

function isVisible(index: number): boolean {
  const section = props.sections[index]
  for (let previous = index - 1; previous >= 0; previous -= 1) {
    const candidate = props.sections[previous]
    if (candidate.level < section.level && collapsed.value.has(candidate.id)) return false
  }
  return true
}

function toggle(sectionId: string): void {
  const next = new Set(collapsed.value)
  if (next.has(sectionId)) next.delete(sectionId)
  else next.add(sectionId)
  collapsed.value = next
}
</script>

<style scoped>
.paper-outline {
  min-height: 0;
  padding: 5px 0 12px;
  overflow: auto;
}

.outline-empty {
  padding: 18px 12px;
  color: #87939f;
  font-size: 11px;
  line-height: 1.6;
}

.outline-row {
  display: flex;
  min-width: 0;
  align-items: center;
  min-height: 27px;
  padding-right: 5px;
  color: #5d6976;
}

.outline-row:hover,
.outline-row.active {
  background: #eaf3f1;
  color: #176f60;
}

.collapse-button,
.section-button {
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}

.collapse-button,
.collapse-placeholder {
  width: 17px;
  flex: 0 0 17px;
  padding: 0;
  font-size: 16px;
}

.section-button {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 4px 3px;
  text-align: left;
}

.section-button span {
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.section-button small {
  color: #96a0aa;
  font-size: 9px;
}
</style>
