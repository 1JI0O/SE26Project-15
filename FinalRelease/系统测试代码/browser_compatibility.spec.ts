import { expect, test } from '@playwright/test'
import path from 'node:path'

test('项目基本流、名称备选流与桌面布局兼容性', async ({ page }, testInfo) => {
  const browserErrors: string[] = []
  const httpErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') {
      const location = message.location().url
      browserErrors.push(`${message.text()}${location ? ` @ ${location}` : ''}`)
    }
  })
  page.on('pageerror', (error) => browserErrors.push(error.message))
  page.on('response', (response) => {
    if (response.status() >= 400) httpErrors.push(`${response.status()} ${response.url()}`)
  })

  await page.goto('/')
  await expect(page.getByRole('heading', { name: '工作区' })).toBeVisible()
  const initialProjects = (await (await page.request.get('/api/v1/projects')).json()) as unknown[]

  const nameInput = page.getByPlaceholder('项目名称')
  const createButton = page.getByRole('button', { name: '创建', exact: true })
  await createButton.click()
  await expect(page.getByText('请输入项目名称').last()).toBeVisible()
  await nameInput.fill('   ')
  await createButton.click()
  await expect(page.getByText('请输入项目名称').last()).toBeVisible()
  const projectsAfterInvalidInput = (
    await (await page.request.get('/api/v1/projects')).json()
  ) as unknown[]
  expect(projectsAfterInvalidInput).toHaveLength(initialProjects.length)

  const projectName = `系统测试-${testInfo.project.name}-${Date.now()}`
  await nameInput.fill(projectName)
  await page.getByPlaceholder('项目说明（可选）').fill('浏览器兼容性自动化测试')
  await createButton.click()
  await expect(page).toHaveURL(/\/projects\/\d+$/)
  await expect(page.getByText(projectName, { exact: true }).first()).toBeVisible({
    timeout: 20_000,
  })

  const projectId = Number(new URL(page.url()).pathname.split('/').pop())
  expect(Number.isInteger(projectId)).toBe(true)
  const createdProject = (await (
    await page.request.get(`/api/v1/projects/${projectId}`)
  ).json()) as { sync_mode: string }
  expect(createdProject.sync_mode).toBe('local_only')
  await page.goto('/')
  const projectRow = page.locator('.project-row').filter({ hasText: projectName })
  await expect(projectRow).toBeVisible()
  await projectRow.getByRole('button', { name: '打开项目' }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`))
  await page.waitForLoadState('networkidle')

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }))
  expect(overflow.document).toBeLessThanOrEqual(1)
  expect(overflow.body).toBeLessThanOrEqual(1)

  const screenshotPath = path.resolve(
    process.cwd(),
    '../FinalRelease/系统测试证据/兼容性测试',
    `${testInfo.project.name}-workspace.png`,
  )
  await page.screenshot({ path: screenshotPath, fullPage: true })

  const expectedEmptyProject404 =
    /\/api\/v1\/projects\/\d+\/(?:workspace\/code-tree|paper|workspace\/paper-document|code)$/
  const unexpectedErrors = browserErrors.filter((message) => {
    const url = message.split(' @ ').at(-1) ?? ''
    if (expectedEmptyProject404.test(url)) return false
    if (message.startsWith('JSHandle@object @ ') && message.endsWith('/useTrace.ts')) return false
    return true
  })
  const unexpectedHttpErrors = httpErrors.filter((message) => {
    const url = message.split(' ').at(-1) ?? ''
    return !expectedEmptyProject404.test(url)
  })
  expect(unexpectedErrors).toEqual([])
  expect(unexpectedHttpErrors).toEqual([])

  const deleted = await page.request.delete(`/api/v1/projects/${projectId}`)
  expect(deleted.status()).toBe(204)
})
