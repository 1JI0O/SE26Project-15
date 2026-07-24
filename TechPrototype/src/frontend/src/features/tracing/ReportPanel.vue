<template>
  <div class="report-layout">
    <article v-for="card in cards" :key="card.title" class="report-card">
      <strong>{{ card.value }}</strong>
      <span>{{ card.title }}</span>
      <p>{{ card.description }}</p>
    </article>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  cards: Array<{
    value: string
    title: string
    description: string
  }>
}>()
</script>

<style scoped>
.report-layout {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  padding: 16px;
}

.report-card {
  display: grid;
  gap: 14px;
  padding: 16px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: #ffffff;
}

.report-card strong {
  color: #1f8f78;
  font-size: 28px;
}

.report-card span {
  font-weight: 700;
}

.report-card p {
  margin: 6px 0 0;
  color: #667789;
  line-height: 1.6;
}

@media (max-width: 1180px) {
  .report-layout {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
