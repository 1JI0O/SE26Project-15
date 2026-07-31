import { defineStore } from 'pinia'

import {
  loginAccount,
  logoutAccount,
  refreshAccount,
  registerAccount,
} from '@/api/auth-api'
import {
  hasLocalWorkspace,
  isDesktop,
  localHttp,
  runtimeMode,
  setCloudAccessToken,
  setCloudRefreshHandler,
  setSessionExpiredHandler,
} from '@/api/http'
import {
  deleteRefreshToken,
  loadDeviceId,
  loadLastUserId,
  loadRefreshToken,
  saveDeviceId,
  saveLastUserId,
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

async function clearLocalCloudBindings(): Promise<void> {
  if (!hasLocalWorkspace) return
  try {
    await localHttp.post('/local-sync/clear-cloud-bindings')
  } catch {
    // Account-switch must still proceed offline.
  }
}

async function adoptLocalSyncDevice(workspaceId: string, deviceId: string): Promise<void> {
  if (!hasLocalWorkspace || !workspaceId || !deviceId) return
  try {
    // Main already exposes adopt (+ ensureDeviceBindings is done inside
    // synchronizeWorkspace). Login-time adopt keeps enable/sync usable before
    // the first manual sync click.
    await localHttp.post('/local-sync/device/adopt', {
      workspace_id: workspaceId,
      device_id: deviceId,
    })
  } catch {
    // Sync paths also self-heal on device mismatch.
  }
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
      if (this.deviceId) void adoptLocalSyncDevice(workspace.workspace_id, this.deviceId)
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
    async afterAuthenticated() {
      if (this.deviceId) await saveDeviceId(this.deviceId)
      const previousUserId = await loadLastUserId()
      const currentUserId = this.user?.user_id ?? ''
      // Only detach local cloud bindings when the account actually changes.
      if (previousUserId && currentUserId && previousUserId !== currentUserId) {
        await clearLocalCloudBindings()
      }
      if (currentUserId) await saveLastUserId(currentUserId)
      if (this.workspace && this.deviceId) {
        await adoptLocalSyncDevice(this.workspace.workspace_id, this.deviceId)
      }
    },
    async initialize() {
      if (this.ready) return
      const storedDeviceId = await loadDeviceId()
      if (storedDeviceId) this.deviceId = storedDeviceId
      setCloudRefreshHandler(() => this.refresh())
      setSessionExpiredHandler(() => {
        const wasAuthenticated = Boolean(this.user)
        const keptDeviceId = this.deviceId
        this.accessToken = ''
        this.csrfToken = ''
        this.user = null
        this.workspace = null
        // Keep deviceId so the next login on this machine can reuse it.
        this.deviceId = keptDeviceId
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
        if (!this.deviceId) this.deviceId = await loadDeviceId()
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
          platform: isDesktop
            ? navigator.platform
            : runtimeMode === 'cloud'
              ? 'web'
              : 'web-local',
          client_version: '0.2.0',
        })
        this.applyAuth(payload)
        if (payload.refresh_token) await saveRefreshToken(payload.refresh_token)
        await this.afterAuthenticated()
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
        await this.afterAuthenticated()
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
        const keptDeviceId = this.deviceId || (await loadDeviceId())
        // Same-account re-login should keep sync bindings; account-switch
        // clears them in afterAuthenticated().
        this.$reset()
        this.ready = true
        this.deviceId = keptDeviceId
        setCloudAccessToken('')
        await deleteRefreshToken()
        if (keptDeviceId) await saveDeviceId(keptDeviceId)
      }
    },
  },
})
