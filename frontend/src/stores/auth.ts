import { defineStore } from 'pinia'

import {
  loginAccount,
  logoutAccount,
  refreshAccount,
  registerAccount,
} from '@/api/auth-api'
import {
  isDesktop,
  runtimeMode,
  setCloudAccessToken,
  setCloudRefreshHandler,
  setSessionExpiredHandler,
} from '@/api/http'
import {
  deleteRefreshToken,
  loadRefreshToken,
  saveRefreshToken,
} from '@/services/desktop-credentials'
import type { CloudUser, CloudWorkspace } from '@/types/cloud'

function browserCsrfCookie(): string {
  if (typeof document === 'undefined') return ''
  return document.cookie
    .split('; ')
    .find((part) => part.startsWith('tracelab_csrf='))
    ?.split('=', 2)[1] ?? ''
}

export const useAuthStore = defineStore('cloud-auth', {
  state: () => ({
    accessToken: '',
    csrfToken: '',
    deviceId: '',
    user: null as CloudUser | null,
    workspace: null as CloudWorkspace | null,
    ready: false,
    busy: false,
    sessionEndedElsewhere: false,
  }),
  getters: {
    authenticated: (state) => Boolean(state.accessToken && state.user),
    verified: (state) => Boolean(state.user?.email_verified),
  },
  actions: {
    selectWorkspace(workspace: CloudWorkspace) {
      this.workspace = workspace
    },
    applyAuth(payload: {
      access_token: string
      csrf_token: string | null
      refresh_token: string | null
      device_id: string | null
      user: CloudUser
      default_workspace: CloudWorkspace | null
    }) {
      this.accessToken = payload.access_token
      this.csrfToken = payload.csrf_token ?? browserCsrfCookie()
      this.deviceId = payload.device_id ?? this.deviceId
      this.user = payload.user
      this.workspace = payload.default_workspace
      setCloudAccessToken(this.accessToken)
    },
    async initialize() {
      if (this.ready) return
      setCloudRefreshHandler(() => this.refresh())
      setSessionExpiredHandler(() => {
        // A revoked session (e.g. this account logged in on another device)
        // fails refresh. Clear local auth and flag a one-time notice so the
        // router/UI can surface "signed in elsewhere" and redirect to login.
        const wasAuthenticated = Boolean(this.user)
        this.accessToken = ''
        this.csrfToken = ''
        this.user = null
        this.workspace = null
        setCloudAccessToken('')
        void deleteRefreshToken()
        if (wasAuthenticated) this.sessionEndedElsewhere = true
      })
      try {
        if (isDesktop) {
          const refreshToken = await loadRefreshToken()
          if (refreshToken) await this.refresh(refreshToken)
        } else if (browserCsrfCookie()) {
          await this.refresh()
        }
      } catch {
        await deleteRefreshToken()
      } finally {
        this.ready = true
      }
    },
    async login(email: string, password: string) {
      this.busy = true
      try {
        const payload = await loginAccount({
          email,
          password,
          client_kind: isDesktop ? 'desktop' : 'browser',
          device_id: this.deviceId || undefined,
          device_name: isDesktop
            ? 'TraceLab Desktop'
            : runtimeMode === 'cloud'
              ? 'TraceLab Cloud Web'
              : 'TraceLab Local Web',
          // Cloud Web does not keep an offline cursor. Local Web does, so it
          // must not be classified as the compaction-exempt "web" platform.
          platform: isDesktop
            ? navigator.platform
            : runtimeMode === 'cloud'
              ? 'web'
              : 'web-local',
          client_version: '0.2.0',
        })
        this.applyAuth(payload)
        if (payload.refresh_token) await saveRefreshToken(payload.refresh_token)
      } finally {
        this.busy = false
      }
    },
    async register(email: string, password: string, displayName: string) {
      return registerAccount({ email, password, display_name: displayName })
    },
    async refresh(explicitToken?: string): Promise<string> {
      try {
        const refreshToken = explicitToken ?? (isDesktop ? await loadRefreshToken() : '')
        const payload = await refreshAccount(
          {
            client_kind: isDesktop ? 'desktop' : 'browser',
            refresh_token: refreshToken || undefined,
          },
          this.csrfToken || browserCsrfCookie(),
        )
        this.applyAuth(payload)
        if (payload.refresh_token) await saveRefreshToken(payload.refresh_token)
        return payload.access_token
      } catch (error) {
        await deleteRefreshToken()
        this.accessToken = ''
        this.user = null
        this.workspace = null
        setCloudAccessToken('')
        throw error
      }
    },
    async logout() {
      try {
        if (this.accessToken) await logoutAccount()
      } finally {
        this.$reset()
        this.ready = true
        setCloudAccessToken('')
        await deleteRefreshToken()
      }
    },
  },
})
