import { defineStore } from 'pinia'

import { createProject, deleteProjects, listProjects } from '@/api/projects'
import type { Project, ProjectCreate } from '@/types/api'

interface ProjectState {
  projects: Project[]
  loading: boolean
  deleting: boolean
}

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
        const result = await deleteProjects(projectIds)
        const deleted = new Set(result.deleted_ids)
        this.projects = this.projects.filter((project) => !deleted.has(project.id))
        return result
      } finally {
        this.deleting = false
      }
    },
  },
})
