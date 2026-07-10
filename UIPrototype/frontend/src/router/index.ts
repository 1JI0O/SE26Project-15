import { createRouter, createWebHistory } from 'vue-router'

import ProjectListView from '@/views/ProjectListView.vue'
import ProjectWorkspaceView from '@/views/ProjectWorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'projects', component: ProjectListView },
    { path: '/projects/:id', name: 'workspace', component: ProjectWorkspaceView, props: true },
  ],
})

export default router

