import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { userContext } from '@/contexts/userContext'
import { KnowledgeLibraryDialog } from '@/pages/KnowledgePage/components/KnowledgeLibraryDialog'
import { QaLibraryDialog } from '@/pages/KnowledgePage/components/QaLibraryDialog'
import KnowledgeFile from '@/pages/KnowledgePage/KnowledgeFile'
import KnowledgeQa from '@/pages/KnowledgePage/KnowledgeQa'

const mock = vi.hoisted(() => ({ create: vi.fn(), config: vi.fn(), navigate: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }) }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: {} }) }))
vi.mock('@/controllers/API', () => ({ createFileLib: mock.create, updateKnowledge: vi.fn(), readFileLibDatabase: vi.fn(), copyLibDatabase: vi.fn(), copyQaDatabase: vi.fn(), deleteFileLib: vi.fn() }))
vi.mock('@/util/hook', () => ({ useInfiniteCursorTable: () => ({ data: [], loading: false, hasMore: false, search: vi.fn(), reload: vi.fn(), loadMore: vi.fn() }) }))
vi.mock('@/components/bs-comp/permission/useResourceActions', () => ({ useLazyResourceActions: () => ({ actions: {}, loading: false, load: vi.fn() }) }))
vi.mock('@/components/bs-comp/permission/PermissionDialog', () => ({ PermissionDialog: () => null }))
vi.mock('@/controllers/API/finetune', () => ({ getKnowledgeModelConfig: mock.config }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
vi.mock('react-router-dom', () => ({ useNavigate: () => mock.navigate }))
vi.mock('@/pages/ModelPage/manage', () => ({ useModel: () => ({ embeddings: [], isLoading: false }) }))
vi.mock('@/pages/ModelPage/manage/tabs/WorkbenchModel', () => ({ ModelSelect: () => null }))
afterEach(cleanup)
beforeEach(() => { vi.clearAllMocks(); mock.config.mockResolvedValue({ embedding_model_id: 1 }); mock.create.mockResolvedValue({ id: 1 }) })

it.each([KnowledgeFile, KnowledgeQa])('exposes creation to a tenant admin without a create menu', Page => {
  const view = render(<userContext.Provider value={{ user: { role: 'user', is_child_admin: true, web_menu: [] } } as never}><Page /></userContext.Provider>)
  expect(screen.getByRole('button', { name: 'create' })).toBeVisible()
  view.rerender(<userContext.Provider value={{ user: { role: 'user', is_child_admin: false, web_menu: [] } } as never}><Page /></userContext.Provider>)
  expect(screen.queryByRole('button', { name: 'create' })).toBeNull()
})

it.each([KnowledgeLibraryDialog, QaLibraryDialog])('fixes expected tenant when opening a new-library form', async Dialog => {
  const props = { datalist: [], open: true, onOpenChange: vi.fn(), onLoadEnd: vi.fn() }
  const view = render(<userContext.Provider value={{ user: { leaf_tenant_id: 60 } } as never}><Dialog {...props} /></userContext.Provider>)
  await waitFor(() => expect(mock.config).toHaveBeenCalled())
  view.rerender(<userContext.Provider value={{ user: { leaf_tenant_id: 61 } } as never}><Dialog {...props} /></userContext.Provider>)
  fireEvent.change(screen.getByPlaceholderText('lib.enterLibraryName'), { target: { value: 'Test library' } })
  fireEvent.click(screen.getByRole('button', { name: /^(finishCreate|completeCreation)$/ }))
  await waitFor(() => expect(mock.create).toHaveBeenCalledWith(expect.objectContaining({ expected_tenant_id: 60 })))
})

it.each([KnowledgeLibraryDialog, QaLibraryDialog])('blocks new-library submission when current membership is unknown', async Dialog => {
  render(<userContext.Provider value={{ user: {} } as never}><Dialog datalist={[]} open onOpenChange={vi.fn()} onLoadEnd={vi.fn()} /></userContext.Provider>)
  await waitFor(() => expect(mock.config).toHaveBeenCalled())
  fireEvent.change(screen.getByPlaceholderText('lib.enterLibraryName'), { target: { value: 'Test library' } })
  fireEvent.click(screen.getByRole('button', { name: /^(finishCreate|completeCreation)$/ }))
  expect(mock.create).not.toHaveBeenCalled()
})
