<template>
  <div class="project-page">
    <section class="create-panel">
      <div>
        <h1>项目列表</h1>
        <p>创建一个追溯工作空间，然后上传论文与代码包进行分析。</p>
      </div>
      <el-form class="create-form" :model="form" @submit.prevent>
        <el-input v-model="form.name" placeholder="项目名称" />
        <el-input v-model="form.description" placeholder="项目说明" />
        <el-button type="primary" @click="submit">创建项目</el-button>
      </el-form>
    </section>

    <el-skeleton v-if="store.loading" :rows="4" animated />
    <el-empty v-else-if="store.projects.length === 0" description="暂无项目" />
    <section v-else class="project-grid">
      <article v-for="project in store.projects" :key="project.id" class="project-card">
        <div>
          <h2>{{ project.name }}</h2>
          <p>{{ project.description || '未填写项目说明' }}</p>
        </div>
        <el-button type="primary" plain @click="openProject(project.id)">进入工作台</el-button>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'

import { useProjectStore } from '@/stores/project'

const router = useRouter()
const store = useProjectStore()
const form = reactive({
  name: '',
  description: '',
})

onMounted(() => {
  void store.fetchProjects()
})

async function submit() {
  if (!form.name.trim()) {
    ElMessage.warning('请输入项目名称')
    return
  }
  const project = await store.create({
    name: form.name.trim(),
    description: form.description.trim(),
  })
  form.name = ''
  form.description = ''
  await router.push({ name: 'workspace', params: { id: project.id } })
}

function openProject(projectId: number) {
  void router.push({ name: 'workspace', params: { id: projectId } })
}
</script>

<style scoped>
.project-page {
  display: grid;
  gap: 20px;
}

.create-panel {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(320px, 560px);
  gap: 24px;
  align-items: end;
  padding: 20px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

h1 {
  margin: 0;
  font-size: 24px;
}

.create-panel p {
  margin: 8px 0 0;
  color: #667789;
}

.create-form {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 10px;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.project-card {
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid #dce3ea;
  border-radius: 8px;
  background: white;
}

.project-card h2 {
  margin: 0;
  font-size: 18px;
}

.project-card p {
  min-height: 44px;
  margin: 8px 0 0;
  color: #667789;
  line-height: 1.55;
}

@media (max-width: 900px) {
  .create-panel,
  .create-form {
    grid-template-columns: 1fr;
  }
}
</style>

