import { defineStore } from 'pinia'

import { createProject, listProjects } from '@/api/projects'
import type { Project, ProjectCreate } from '@/types/api'

interface ProjectState {
  projects: Project[]
  loading: boolean
}

export const useProjectStore = defineStore('project', {
  state: (): ProjectState => ({
    projects: [],
    loading: false,
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
  },
})

