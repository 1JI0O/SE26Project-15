import { cloudHttp, localHttp, runtimeMode } from '@/api/http'
import type {
  ArtifactVersion,
  CloudDomainEntity,
  CloudEntityType,
  CloudProject,
} from '@/types/cloud'
import type { Project } from '@/types/projects'

export type ProjectRef = string | number

export interface ProjectGateway {
  readonly kind: 'local' | 'cloud'
  listProjects(): Promise<Array<Project | CloudProject>>
  getProject(ref: ProjectRef): Promise<Project | CloudProject>
  listEntities(ref: ProjectRef, entityType?: CloudEntityType): Promise<CloudDomainEntity[]>
  createEntity(
    ref: ProjectRef,
    entityType: CloudEntityType,
    payload: Record<string, unknown>,
  ): Promise<Record<string, unknown>>
  updateEntity(
    ref: ProjectRef,
    entity: CloudDomainEntity,
    payload: Record<string, unknown>,
  ): Promise<Record<string, unknown>>
  listVersions(ref: ProjectRef, entity: CloudDomainEntity): Promise<ArtifactVersion[]>
}

export class CloudProjectGateway implements ProjectGateway {
  readonly kind = 'cloud' as const

  async listProjects(): Promise<CloudProject[]> {
    return (await cloudHttp.get<CloudProject[]>('/projects')).data
  }

  async getProject(ref: ProjectRef): Promise<CloudProject> {
    return (await cloudHttp.get<CloudProject>(`/projects/${ref}`)).data
  }

  async listEntities(ref: ProjectRef, entityType?: CloudEntityType): Promise<CloudDomainEntity[]> {
    return (
      await cloudHttp.get<CloudDomainEntity[]>(`/projects/${ref}/entities`, {
        params: entityType ? { entity_type: entityType } : undefined,
      })
    ).data
  }

  async createEntity(
    ref: ProjectRef,
    entityType: CloudEntityType,
    payload: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return (
      await cloudHttp.post<Record<string, unknown>>(`/projects/${ref}/entities/${entityType}`, {
        public_id: crypto.randomUUID(),
        base_version: 0,
        payload,
      })
    ).data
  }

  async updateEntity(
    ref: ProjectRef,
    entity: CloudDomainEntity,
    payload: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    return (
      await cloudHttp.patch<Record<string, unknown>>(
        `/projects/${ref}/entities/${entity.entity_type}/${entity.public_id}`,
        { base_version: entity.version, payload },
      )
    ).data
  }

  async listVersions(ref: ProjectRef, entity: CloudDomainEntity): Promise<ArtifactVersion[]> {
    return (
      await cloudHttp.get<ArtifactVersion[]>(
        `/projects/${ref}/artifacts/${entity.entity_type}/${entity.public_id}/versions`,
      )
    ).data
  }

  async uploadSource(project: CloudProject, file: File): Promise<string> {
    const bytes = await file.arrayBuffer()
    const digest = await crypto.subtle.digest('SHA-256', bytes)
    const sha256 = [...new Uint8Array(digest)]
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('')
    const initialized = (
      await cloudHttp.post<{
        blob_id: string
        status: 'upload' | 'reuse'
        chunk_size: number
        uploaded_bytes: number
      }>('/blobs/upload-init', {
        workspace_id: project.workspace_id,
        project_public_id: project.public_id,
        sha256,
        byte_size: bytes.byteLength,
        mime_type: file.type || 'application/octet-stream',
        filename: file.name,
      })
    ).data
    if (initialized.status === 'upload') {
      for (
        let offset = initialized.uploaded_bytes;
        offset < bytes.byteLength;
        offset += initialized.chunk_size
      ) {
        await cloudHttp.put(
          `/blobs/${initialized.blob_id}/chunks/${Math.floor(offset / initialized.chunk_size)}`,
          bytes.slice(offset, Math.min(offset + initialized.chunk_size, bytes.byteLength)),
          { headers: { 'Content-Type': 'application/octet-stream' } },
        )
      }
      await cloudHttp.post(`/blobs/${initialized.blob_id}/complete`)
    }
    return initialized.blob_id
  }
}

export class LocalProjectGateway implements ProjectGateway {
  readonly kind = 'local' as const
  async listProjects(): Promise<Project[]> {
    return (await localHttp.get<Project[]>('/projects')).data
  }
  async getProject(ref: ProjectRef): Promise<Project> {
    return (await localHttp.get<Project>(`/projects/${ref}`)).data
  }
  async listEntities(): Promise<CloudDomainEntity[]> {
    return []
  }
  async createEntity(): Promise<Record<string, unknown>> {
    throw new Error('Local domain mutations use the transactional Local API')
  }
  async updateEntity(): Promise<Record<string, unknown>> {
    throw new Error('Local domain mutations use the transactional Local API')
  }
  async listVersions(): Promise<ArtifactVersion[]> {
    return []
  }
}

export const projectGateway: ProjectGateway =
  runtimeMode === 'cloud' ? new CloudProjectGateway() : new LocalProjectGateway()
