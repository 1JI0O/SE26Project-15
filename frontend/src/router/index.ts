import { createRouter, createWebHistory } from 'vue-router'

import { runtimeMode } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import AccountView from '@/views/AccountView.vue'
import AdminView from '@/views/AdminView.vue'
import AuthView from '@/views/AuthView.vue'
import CloudProjectsView from '@/views/CloudProjectsView.vue'
import ConflictCenterView from '@/views/ConflictCenterView.vue'
import CloudProjectView from '@/views/CloudProjectView.vue'
import ProjectListView from '@/views/ProjectListView.vue'
import ProjectWorkspaceView from '@/views/ProjectWorkspaceView.vue'

const cloudWeb = runtimeMode === 'cloud'
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: AuthView, meta: { public: true } },
    { path: '/register', name: 'register', component: AuthView, meta: { public: true } },
    { path: '/forgot-password', name: 'forgot-password', component: AuthView, meta: { public: true } },
    { path: '/reset-password', name: 'reset-password', component: AuthView, meta: { public: true } },
    { path: '/verify-email', name: 'verify', component: AuthView, meta: { public: true } },
    { path: '/account', name: 'account', component: AccountView, meta: { cloudAuth: true } },
    { path: '/conflicts', name: 'conflicts', component: ConflictCenterView, meta: { cloudAuth: true } },
    { path: '/cloud-projects', name: 'cloud-projects', component: CloudProjectsView, meta: { cloudAuth: true } },
    { path: '/admin', name: 'admin', component: AdminView, meta: { cloudAuth: true, admin: true } },
    { path: '/', name: 'projects', component: cloudWeb ? CloudProjectsView : ProjectListView, meta: { cloudAuth: cloudWeb } },
    { path: '/projects/:id', name: 'workspace', component: cloudWeb ? CloudProjectView : ProjectWorkspaceView, props: !cloudWeb, meta: { cloudAuth: cloudWeb } },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.initialize()
  if (to.meta.cloudAuth && !auth.authenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && !auth.user?.is_platform_admin) return { name: 'projects' }
  if (to.name === 'login' && auth.authenticated) return { name: 'projects' }
})

export default router
