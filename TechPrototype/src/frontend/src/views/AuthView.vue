<template>
  <div class="auth-page">
    <el-card class="auth-card" shadow="never">
      <template #header>
        <strong>{{ title }}</strong>
      </template>
      <el-alert v-if="notice" :title="notice" type="success" show-icon :closable="false" />
      <el-form v-if="mode === 'login' || mode === 'register'" label-position="top" @submit.prevent="submit">
        <el-form-item v-if="mode === 'register'" label="显示名称">
          <el-input v-model="displayName" autocomplete="name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="email" type="email" autocomplete="email" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="password" type="password" show-password :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="auth.busy" :disabled="!email || password.length < (mode === 'register' ? 10 : 1)">
          {{ mode === 'login' ? '登录' : '注册' }}
        </el-button>
      </el-form>
      <el-form v-else-if="mode === 'forgot'" label-position="top" @submit.prevent="submit">
        <el-form-item label="邮箱"><el-input v-model="email" type="email" /></el-form-item>
        <el-button type="primary" native-type="submit">发送重置邮件</el-button>
      </el-form>
      <el-form v-else-if="mode === 'reset'" label-position="top" @submit.prevent="submit">
        <el-form-item label="新密码"><el-input v-model="password" type="password" show-password /></el-form-item>
        <el-button type="primary" native-type="submit" :disabled="password.length < 10">重置密码</el-button>
      </el-form>
      <div v-else class="verify-state">
        <el-icon class="is-loading"><Loading /></el-icon> 正在验证邮箱…
      </div>
      <footer class="auth-links">
        <router-link v-if="mode !== 'login'" to="/login">返回登录</router-link>
        <router-link v-if="mode === 'login'" to="/register">创建账号</router-link>
        <router-link v-if="mode === 'login'" to="/forgot-password">忘记密码</router-link>
      </footer>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { forgotPassword, resetPassword, verifyEmail } from '@/api/auth-api'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const email = ref('')
const password = ref('')
const displayName = ref('')
const notice = ref('')
const emailToken = ref('')
const mode = computed(() => String(route.name ?? 'login').replace('-password', ''))
const title = computed(() => ({
  login: '登录 TraceLab Cloud',
  register: '创建云端账号',
  forgot: '找回密码',
  reset: '重置密码',
  verify: '验证邮箱',
}[mode.value] ?? '账号'))

onMounted(async () => {
  emailToken.value = new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''
  if (emailToken.value) history.replaceState(null, '', window.location.pathname + window.location.search)
  if (mode.value !== 'verify') return
  try {
    await verifyEmail(emailToken.value)
    ElMessage.success('邮箱验证成功，请登录')
    await router.replace('/login')
  } catch {
    ElMessage.error('验证链接无效或已过期')
  }
})

async function submit() {
  try {
    if (mode.value === 'login') {
      await auth.login(email.value.trim(), password.value)
      await router.push(String(route.query.redirect ?? '/'))
    } else if (mode.value === 'register') {
      await auth.register(email.value.trim(), password.value, displayName.value.trim())
      notice.value = '注册成功。请查收验证邮件；验证前不能创建或同步云端项目。'
    } else if (mode.value === 'forgot') {
      await forgotPassword(email.value.trim())
      notice.value = '如果账号存在，重置邮件已经发送。'
    } else if (mode.value === 'reset') {
      await resetPassword(emailToken.value, password.value)
      ElMessage.success('密码已重置，请重新登录')
      await router.replace('/login')
    }
  } catch {
    ElMessage.error('操作失败，请检查输入后重试')
  }
}
</script>

<style scoped>
.auth-page { display: grid; min-height: 100%; padding: 48px 16px; place-items: start center; }
.auth-card { width: min(420px, 100%); }
.auth-links { display: flex; gap: 16px; margin-top: 20px; font-size: 13px; }
.verify-state { padding: 24px 0; text-align: center; }
</style>
