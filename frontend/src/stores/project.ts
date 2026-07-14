import { defineStore } from 'pinia'

import { createProject, deleteProjects, listProjects } from '@/api/projects'
import type { Project, ProjectCreate } from '@/types/api'

interface ProjectState {
  projects: Project[]
  loading: boolean
  deleting: boolean
}

const DELETE_BATCH_SIZE = 100

export const useProjectStore = defineStore('project', {
  state: (): ProjectState => ({
    projects: [],
    loading: false,
    deleting: false,
  }),
  actions: {
    async fetchProjects() {
      this.loading = true
      try {
        this.projects = await listProjects()
      } finally {
        this.loading = false
      }
    },
    async create(payload: ProjectCreate) {
      const project = await createProject(payload)
      this.projects.unshift(project)
      return project
    },
    async deleteMany(projectIds: number[]) {
      this.deleting = true
      try {
        const requestedIds = [...new Set(projectIds)]
        const deletedIds: number[] = []
        const missingIds: number[] = []
        for (let offset = 0; offset < requestedIds.length; offset += DELETE_BATCH_SIZE) {
          const result = await deleteProjects(
            requestedIds.slice(offset, offset + DELETE_BATCH_SIZE),
          )
          deletedIds.push(...result.deleted_ids)
          missingIds.push(...result.missing_ids)
          const deleted = new Set(result.deleted_ids)
          this.projects = this.projects.filter((project) => !deleted.has(project.id))
        }
        return { deleted_ids: deletedIds, missing_ids: missingIds }
      } finally {
        this.deleting = false
      }
    },
  },
})
