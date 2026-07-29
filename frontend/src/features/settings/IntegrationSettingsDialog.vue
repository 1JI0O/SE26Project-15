<template>
  <el-dialog
    :model-value="modelValue"
    title="集成设置"
    width="min(760px, calc(100vw - 32px))"
    class="settings-dialog"
    destroy-on-close
    @open="loadSettings"
    @close="closeDialog"
  >
    <div v-loading="loading" class="settings-body">
      <div v-if="settings" class="settings-status">
        <span>配置保存在本机应用数据中，修改后立即用于新请求。</span>
        <el-tag size="small" effect="plain" type="success">应用内配置</el-tag>
      </div>

      <el-tabs v-if="form" v-model="activeTab">
        <el-tab-pane label="Agent API" name="agent">
          <el-form label-position="top" class="settings-form">
            <div class="switch-row">
              <div>
                <strong>启用 Agent 与 LLM 辅助追溯</strong>
                <p>关闭后仍可使用静态追溯与其他工作台功能。</p>
              </div>
              <el-switch v-model="form.agent.enabled" />
            </div>

            <div class="form-grid">
              <el-form-item label="API 地址" class="wide-field">
                <el-input
                  v-model.trim="form.agent.base_url"
                  placeholder="https://api.deepseek.com"
                />
              </el-form-item>
              <el-form-item label="模型">
                <el-input
                  v-model.trim="form.agent.model"
                  placeholder="deepseek-v4-flash"
                />
              </el-form-item>
              <el-form-item label="追溯分析模型" class="wide-field">
                <el-input
                  v-model.trim="form.agent.analysis_model"
                  placeholder="留空则与对话模型相同；重要追溯可填更强模型，如 deepseek-v4-pro"
                />
              </el-form-item>
              <el-form-item label="思考模式">
                <el-select v-model="form.agent.thinking_mode">
                  <el-option label="由服务决定" value="" />
                  <el-option label="启用" value="enabled" />
                  <el-option label="关闭" value="disabled" />
                </el-select>
              </el-form-item>
              <el-form-item label="API Key" class="wide-field">
                <el-input
                  v-model="agentApiKey"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :placeholder="agentKeyPlaceholder"
                  @input="clearAgentKey = false"
                />
                <el-button
                  v-if="form.agent.api_key_configured"
                  text
                  type="danger"
                  class="clear-secret"
                  @click="markAgentKeyForRemoval"
                >
                  {{ clearAgentKey ? '取消清除' : '清除已保存密钥' }}
                </el-button>
              </el-form-item>
              <el-form-item label="请求超时（秒）">
                <el-input-number
                  v-model="form.agent.timeout_seconds"
                  :min="1"
                  :max="600"
                  controls-position="right"
                />
              </el-form-item>
            </div>

            <div class="probe-row">
              <el-button :loading="probing === 'agent'" @click="testAgent">测试连接</el-button>
              <el-alert
                v-if="agentProbe"
                :type="agentProbe.ok ? 'success' : 'error'"
                :closable="false"
                :title="probeTitle(agentProbe)"
                :description="agentProbe.detail"
              />
              <span v-else class="probe-hint">
                会用当前填写的地址、密钥与模型发一次最小请求，验证是否真的可用。
              </span>
            </div>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="MinerU API" name="mineru">
          <el-form label-position="top" class="settings-form">
            <el-form-item label="接入方式">
              <el-radio-group v-model="form.mineru.provider">
                <el-radio-button value="local">本地服务</el-radio-button>
                <el-radio-button value="official">官方 API</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <div v-if="form.mineru.provider === 'local'" class="form-grid">
              <el-form-item label="本地服务地址" class="wide-field">
                <el-input
                  v-model.trim="form.mineru.local_url"
                  placeholder="http://127.0.0.1:8001"
                />
              </el-form-item>
              <el-form-item label="解析后端">
                <el-input v-model.trim="form.mineru.backend" placeholder="pipeline" />
              </el-form-item>
              <el-form-item label="解析方式">
                <el-select v-model="form.mineru.parse_method">
                  <el-option label="自动" value="auto" />
                  <el-option label="文本" value="txt" />
                  <el-option label="OCR" value="ocr" />
                </el-select>
              </el-form-item>
            </div>

            <div v-else class="form-grid">
              <el-form-item label="官方 API 地址" class="wide-field">
                <el-input v-model.trim="form.mineru.official_api_url" />
              </el-form-item>
              <el-form-item label="模型">
                <el-select v-model="form.mineru.official_api_model">
                  <el-option label="VLM" value="vlm" />
                  <el-option label="Pipeline" value="pipeline" />
                </el-select>
              </el-form-item>
              <el-form-item label="API Token" class="wide-field">
                <el-input
                  v-model="mineruApiToken"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :placeholder="mineruTokenPlaceholder"
                  @input="clearMineruToken = false"
                />
                <el-button
                  v-if="form.mineru.api_token_configured"
                  text
                  type="danger"
                  class="clear-secret"
                  @click="markMineruTokenForRemoval"
                >
                  {{ clearMineruToken ? '取消清除' : '清除已保存令牌' }}
                </el-button>
              </el-form-item>
              <el-form-item label="解析能力" class="wide-field">
                <el-checkbox v-model="form.mineru.ocr">OCR</el-checkbox>
                <el-checkbox v-model="form.mineru.formula_enable">公式</el-checkbox>
                <el-checkbox v-model="form.mineru.table_enable">表格</el-checkbox>
              </el-form-item>
            </div>

            <div class="form-grid compact-grid">
              <el-form-item label="语言">
                <el-input v-model.trim="form.mineru.language" placeholder="ch" />
              </el-form-item>
              <el-form-item label="请求超时（秒）">
                <el-input-number
                  v-model="form.mineru.request_timeout_seconds"
                  :min="1"
                  :max="300"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="任务超时（秒）">
                <el-input-number
                  v-model="form.mineru.task_timeout_seconds"
                  :min="1"
                  :max="7200"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="轮询间隔（秒）">
                <el-input-number
                  v-model="form.mineru.poll_interval_seconds"
                  :min="0.1"
                  :max="30"
                  :step="0.5"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item v-if="form.mineru.provider === 'official'" label="请求重试次数">
                <el-input-number
                  v-model="form.mineru.request_retries"
                  :min="1"
                  :max="10"
                  controls-position="right"
                />
              </el-form-item>
            </div>

            <div class="probe-row">
              <el-button :loading="probing === 'mineru'" @click="testMinerU">测试连接</el-button>
              <el-alert
                v-if="mineruProbe"
                :type="mineruProbe.ok ? 'success' : 'error'"
                :closable="false"
                :title="probeTitle(mineruProbe)"
                :description="mineruProbe.detail"
              />
              <span v-else class="probe-hint">
                {{
                  form.mineru.provider === 'local'
                    ? '会请求本地服务的 /health 接口确认它已启动。'
                    : '会用当前 Token 访问官方 API，验证令牌是否有效（不会创建解析任务）。'
                }}
              </span>
            </div>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="语义检索" name="rag">
          <el-form label-position="top" class="settings-form">
            <div class="switch-row">
              <div>
                <strong>启用语义检索</strong>
                <p>
                  按语义而非关键词定位论文段落与代码符号，并召回本项目已复核的追溯案例。
                  关闭后 Agent 回退到分页与文本搜索，追溯与对话仍可正常完成。
                </p>
              </div>
              <el-switch v-model="form.rag.enabled" />
            </div>

            <el-form-item label="嵌入方式">
              <el-radio-group v-model="form.rag.embedder">
                <el-radio-button value="local">本地离线</el-radio-button>
                <el-radio-button value="remote">远程 API</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <p v-if="form.rag.embedder === 'local'" class="probe-hint">
              本地方式无需密钥与网络，按标识符切分与中文 n-gram 做词法级向量化，
              对长论文的定位已有明显帮助；需要真正的语义改写匹配时再切换到远程 API。
            </p>

            <div v-if="form.rag.embedder === 'remote'" class="form-grid">
              <el-form-item label="API 地址" class="wide-field">
                <el-input
                  v-model.trim="form.rag.base_url"
                  placeholder="https://api.openai.com/v1"
                />
              </el-form-item>
              <el-form-item label="嵌入模型" class="wide-field">
                <el-input
                  v-model.trim="form.rag.model"
                  placeholder="text-embedding-3-small"
                />
              </el-form-item>
              <el-form-item label="API Key" class="wide-field">
                <el-input
                  v-model="ragApiKey"
                  type="password"
                  show-password
                  autocomplete="new-password"
                  :placeholder="ragKeyPlaceholder"
                  @input="clearRagKey = false"
                />
                <el-button
                  v-if="form.rag.api_key_configured"
                  text
                  type="danger"
                  class="clear-secret"
                  @click="markRagKeyForRemoval"
                >
                  {{ clearRagKey ? '取消清除' : '清除已保存密钥' }}
                </el-button>
              </el-form-item>
              <el-form-item label="向量维度">
                <el-input-number
                  v-model="form.rag.dimensions"
                  :min="64"
                  :max="4096"
                  :step="64"
                  controls-position="right"
                />
              </el-form-item>
              <el-form-item label="请求超时（秒）">
                <el-input-number
                  v-model="form.rag.timeout_seconds"
                  :min="1"
                  :max="300"
                  controls-position="right"
                />
              </el-form-item>
            </div>

            <el-alert
              v-if="ragRebuildNotice"
              type="warning"
              :closable="false"
              show-icon
              title="保存后需要重建索引"
              description="嵌入方式、模型或维度变化会让已存向量不可比较，各项目的论文/代码/追溯索引将标记为待重建，并在下次检索时自动重建。"
            />
            <span v-else class="probe-hint">
              索引由解析、代码分析与追溯复核自动维护，无需手动操作。
            </span>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>

    <template #footer>
      <el-button @click="closeDialog">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading" @click="saveSettings">
        保存设置
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'

import {
  getIntegrationSettings,
  probeIntegration,
  updateIntegrationSettings,
} from '@/api/integration-settings-api'
import type {
  IntegrationProbeResult,
  IntegrationSettings,
  IntegrationSettingsUpdate,
} from '@/types/integration-settings'

defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const activeTab = ref('agent')
const loading = ref(false)
const saving = ref(false)
const settings = ref<IntegrationSettings | null>(null)
const form = ref<IntegrationSettings | null>(null)
const agentApiKey = ref('')
const mineruApiToken = ref('')
const ragApiKey = ref('')
const clearAgentKey = ref(false)
const clearMineruToken = ref(false)
const clearRagKey = ref(false)
const probing = ref<'agent' | 'mineru' | null>(null)
const agentProbe = ref<IntegrationProbeResult | null>(null)
const mineruProbe = ref<IntegrationProbeResult | null>(null)
const PROBE_TIMEOUT_SECONDS = 30

function probeTitle(result: IntegrationProbeResult): string {
  const latency = result.latency_ms == null ? '' : ` · ${result.latency_ms}ms`
  return result.ok ? `连接成功${latency}` : `连接失败（${result.code}）${latency}`
}

async function testAgent(): Promise<void> {
  if (!form.value) return
  probing.value = 'agent'
  agentProbe.value = null
  try {
    agentProbe.value = await probeIntegration({
      target: 'agent',
      base_url: form.value.agent.base_url,
      // Omitted key means "use the one already saved on this machine".
      ...(agentApiKey.value ? { api_key: agentApiKey.value } : {}),
      model: form.value.agent.analysis_model || form.value.agent.model,
      timeout_seconds: Math.min(form.value.agent.timeout_seconds, PROBE_TIMEOUT_SECONDS),
    },
    (PROBE_TIMEOUT_SECONDS + 5) * 1000)
  } catch (cause) {
    ElMessage.error('无法发起测试，请确认本地后端已启动')
    console.error(cause)
  } finally {
    probing.value = null
  }
}

async function testMinerU(): Promise<void> {
  if (!form.value) return
  const isLocal = form.value.mineru.provider === 'local'
  probing.value = 'mineru'
  mineruProbe.value = null
  try {
    mineruProbe.value = await probeIntegration({
      target: 'mineru',
      mineru_provider: form.value.mineru.provider,
      base_url: isLocal ? form.value.mineru.local_url : form.value.mineru.official_api_url,
      ...(!isLocal && mineruApiToken.value ? { api_key: mineruApiToken.value } : {}),
      timeout_seconds: Math.min(form.value.mineru.request_timeout_seconds, PROBE_TIMEOUT_SECONDS),
    },
    (PROBE_TIMEOUT_SECONDS + 5) * 1000)
  } catch (cause) {
    ElMessage.error('无法发起测试，请确认本地后端已启动')
    console.error(cause)
  } finally {
    probing.value = null
  }
}

const agentKeyPlaceholder = computed(() => {
  if (clearAgentKey.value) return '密钥将在保存后清除'
  return form.value?.agent.api_key_configured ? '已配置，留空则保留' : '输入 API Key'
})

const mineruTokenPlaceholder = computed(() => {
  if (clearMineruToken.value) return '令牌将在保存后清除'
  return form.value?.mineru.api_token_configured ? '已配置，留空则保留' : '输入 API Token'
})

const ragKeyPlaceholder = computed(() => {
  if (clearRagKey.value) return '密钥将在保存后清除'
  return form.value?.rag.api_key_configured ? '已配置，留空则保留' : '输入 API Key'
})

/**
 * True when saving would invalidate stored vectors. Mirrors the backend rule exactly
 * (embedder / model / dimensions), so the warning never appears for a harmless edit.
 */
const ragRebuildNotice = computed(() => {
  if (!form.value || !settings.value) return false
  const next = form.value.rag
  const previous = settings.value.rag
  return (
    next.embedder !== previous.embedder ||
    next.model !== previous.model ||
    next.dimensions !== previous.dimensions
  )
})

async function loadSettings() {
  loading.value = true
  try {
    const loaded = await getIntegrationSettings()
    settings.value = loaded
    form.value = structuredClone(loaded)
    agentApiKey.value = ''
    mineruApiToken.value = ''
    ragApiKey.value = ''
    clearAgentKey.value = false
    clearMineruToken.value = false
    clearRagKey.value = false
    agentProbe.value = null
    mineruProbe.value = null
  } catch {
    ElMessage.error('无法读取集成设置，请确认本地后端已启动')
  } finally {
    loading.value = false
  }
}

function closeDialog() {
  emit('update:modelValue', false)
}

function markAgentKeyForRemoval() {
  clearAgentKey.value = !clearAgentKey.value
  agentApiKey.value = ''
}

function markMineruTokenForRemoval() {
  clearMineruToken.value = !clearMineruToken.value
  mineruApiToken.value = ''
}

function markRagKeyForRemoval() {
  clearRagKey.value = !clearRagKey.value
  ragApiKey.value = ''
}

function hasHttpUrl(value: string) {
  return value.startsWith('http://') || value.startsWith('https://')
}

function validateSettings(): boolean {
  if (!form.value) return false
  if (form.value.agent.enabled) {
    if (!hasHttpUrl(form.value.agent.base_url) || !form.value.agent.model) {
      activeTab.value = 'agent'
      ElMessage.warning('启用 Agent 前请填写有效的 API 地址和模型')
      return false
    }
    if (!form.value.agent.api_key_configured && !agentApiKey.value) {
      activeTab.value = 'agent'
      ElMessage.warning('启用 Agent 前请填写 API Key')
      return false
    }
  }
  const mineruUrl =
    form.value.mineru.provider === 'local'
      ? form.value.mineru.local_url
      : form.value.mineru.official_api_url
  if (!hasHttpUrl(mineruUrl)) {
    activeTab.value = 'mineru'
    ElMessage.warning('请填写有效的 MinerU 服务地址')
    return false
  }
  if (
    form.value.mineru.provider === 'official' &&
    !form.value.mineru.api_token_configured &&
    !mineruApiToken.value
  ) {
    activeTab.value = 'mineru'
    ElMessage.warning('使用官方 MinerU API 前请填写 API Token')
    return false
  }
  // An incomplete remote embedder silently falls back to local on the backend, which would
  // look like the setting was ignored. Catch it here instead.
  if (form.value.rag.enabled && form.value.rag.embedder === 'remote') {
    if (!hasHttpUrl(form.value.rag.base_url) || !form.value.rag.model) {
      activeTab.value = 'rag'
      ElMessage.warning('使用远程嵌入前请填写有效的 API 地址和嵌入模型')
      return false
    }
    if (!form.value.rag.api_key_configured && !ragApiKey.value) {
      activeTab.value = 'rag'
      ElMessage.warning('使用远程嵌入前请填写 API Key')
      return false
    }
  }
  return true
}

async function saveSettings() {
  if (!form.value || !validateSettings()) return
  const payload: IntegrationSettingsUpdate = {
    agent: {
      enabled: form.value.agent.enabled,
      base_url: form.value.agent.base_url,
      model: form.value.agent.model,
      analysis_model: form.value.agent.analysis_model,
      thinking_mode: form.value.agent.thinking_mode,
      timeout_seconds: form.value.agent.timeout_seconds,
      clear_api_key: clearAgentKey.value,
      ...(agentApiKey.value ? { api_key: agentApiKey.value } : {}),
    },
    mineru: {
      provider: form.value.mineru.provider,
      local_url: form.value.mineru.local_url,
      backend: form.value.mineru.backend,
      language: form.value.mineru.language,
      parse_method: form.value.mineru.parse_method,
      official_api_url: form.value.mineru.official_api_url,
      official_api_model: form.value.mineru.official_api_model,
      ocr: form.value.mineru.ocr,
      formula_enable: form.value.mineru.formula_enable,
      table_enable: form.value.mineru.table_enable,
      request_timeout_seconds: form.value.mineru.request_timeout_seconds,
      request_retries: form.value.mineru.request_retries,
      task_timeout_seconds: form.value.mineru.task_timeout_seconds,
      poll_interval_seconds: form.value.mineru.poll_interval_seconds,
      clear_api_token: clearMineruToken.value,
      ...(mineruApiToken.value ? { official_api_token: mineruApiToken.value } : {}),
    },
    rag: {
      enabled: form.value.rag.enabled,
      embedder: form.value.rag.embedder,
      base_url: form.value.rag.base_url,
      model: form.value.rag.model,
      dimensions: form.value.rag.dimensions,
      timeout_seconds: form.value.rag.timeout_seconds,
      clear_api_key: clearRagKey.value,
      ...(ragApiKey.value ? { api_key: ragApiKey.value } : {}),
    },
  }
  saving.value = true
  try {
    settings.value = await updateIntegrationSettings(payload)
    ElMessage.success('集成设置已保存')
    closeDialog()
  } catch {
    ElMessage.error('保存失败，请检查设置后重试')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
:global(.settings-dialog.el-dialog) {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 32px);
  margin-top: 16px;
  overflow: hidden;
}

:global(.settings-dialog .el-dialog__body) {
  min-height: 0;
  overflow-y: auto;
}

.settings-body {
  min-height: 390px;
}

.settings-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #dce3ea;
  border-radius: 6px;
  color: #596978;
  font-size: 13px;
}

.settings-form {
  padding-top: 8px;
}

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 2px 0 16px;
}

.switch-row p {
  margin: 4px 0 0;
  color: #71808f;
  font-size: 13px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
}

.wide-field {
  grid-column: 1 / -1;
}

.clear-secret {
  margin-left: auto;
  padding-right: 0;
}

.compact-grid {
  padding-top: 8px;
  border-top: 1px solid #e4e9ee;
}

.probe-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px solid #e4e9ee;
}

.probe-row :deep(.el-alert) {
  flex: 1;
  min-width: 0;
  padding: 6px 10px;
}

.probe-row :deep(.el-alert__description) {
  margin: 2px 0 0;
  word-break: break-word;
}

.probe-hint {
  flex: 1;
  color: #8a95a1;
  font-size: 12px;
  line-height: 1.5;
}

:deep(.el-input-number),
:deep(.el-select) {
  width: 100%;
}

@media (max-width: 640px) {
  .settings-status,
  .switch-row {
    align-items: flex-start;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .wide-field {
    grid-column: auto;
  }
}
</style>
