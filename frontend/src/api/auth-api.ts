import { cloudHttp } from '@/api/http'
import type { CloudAuthResponse, CloudUser, CloudWorkspace } from '@/types/cloud'

export async function registerAccount(payload: {
  email: string
  password: string
  display_name: string
}): Promise<CloudUser> {
  const { data } = await cloudHttp.post<CloudUser>('/auth/register', payload)
  return data
}

export async function loginAccount(payload: {
  email: string
  password: string
  client_kind: 'browser' | 'desktop'
  device_id?: string
  device_name: string
  platform: string
  client_version: string
}): Promise<CloudAuthResponse> {
  const { data } = await cloudHttp.post<CloudAuthResponse>('/auth/login', payload)
  return data
}

export async function refreshAccount(payload: {
  client_kind: 'browser' | 'desktop'
  refresh_token?: string
}, csrfToken?: string): Promise<CloudAuthResponse> {
  const { data } = await cloudHttp.post<CloudAuthResponse>('/auth/refresh', payload, {
    headers: csrfToken ? { 'X-CSRF-Token': csrfToken } : undefined,
  })
  return data
}

export async function logoutAccount(): Promise<void> {
  await cloudHttp.post('/auth/logout')
}

export async function listDevices() {
  const { data } = await cloudHttp.get<Array<{
    device_id: string
    name: string
    platform: string
    client_version: string
    last_seen_at: string
    current: boolean
  }>>('/auth/devices')
  return data
}

export async function revokeDevice(deviceId: string): Promise<void> {
  await cloudHttp.delete(`/auth/devices/${deviceId}`)
}

export async function listWorkspaces(): Promise<CloudWorkspace[]> {
  return (await cloudHttp.get<CloudWorkspace[]>('/workspaces')).data
}

export async function createWorkspace(name: string): Promise<CloudWorkspace> {
  return (await cloudHttp.post<CloudWorkspace>('/workspaces', { name })).data
}

export interface WorkspaceMember {
  user_id: string
  email: string
  display_name: string
  role: 'owner' | 'editor' | 'viewer'
}

export async function listWorkspaceMembers(workspaceId: string): Promise<WorkspaceMember[]> {
  const { data } = await cloudHttp.get<WorkspaceMember[]>(`/workspaces/${workspaceId}/members`)
  return data
}

export async function addWorkspaceMember(
  workspaceId: string,
  email: string,
  role: WorkspaceMember['role'],
): Promise<WorkspaceMember> {
  const { data } = await cloudHttp.post<WorkspaceMember>(`/workspaces/${workspaceId}/members`, { email, role })
  return data
}

export async function updateWorkspaceMember(
  workspaceId: string,
  userId: string,
  role: WorkspaceMember['role'],
): Promise<WorkspaceMember> {
  const { data } = await cloudHttp.patch<WorkspaceMember>(`/workspaces/${workspaceId}/members/${userId}`, { role })
  return data
}

export async function removeWorkspaceMember(workspaceId: string, userId: string): Promise<void> {
  await cloudHttp.delete(`/workspaces/${workspaceId}/members/${userId}`)
}

export async function verifyEmail(token: string): Promise<CloudUser> {
  const { data } = await cloudHttp.post<CloudUser>('/auth/verify-email', { token })
  return data
}

export async function forgotPassword(email: string): Promise<void> {
  await cloudHttp.post('/auth/password/forgot', { email })
}

export async function resetPassword(token: string, password: string): Promise<void> {
  await cloudHttp.post('/auth/password/reset', { token, password })
}
