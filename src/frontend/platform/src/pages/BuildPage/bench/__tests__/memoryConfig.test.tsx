import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DailyChatConfig } from '../DailyChatConfig';
import zhHans from '../../../../../public/locales/zh-Hans/bs.json';
import enUS from '../../../../../public/locales/en-US/bs.json';
import ja from '../../../../../public/locales/ja/bs.json';

const mocks = vi.hoisted(() => ({
    getDaily: vi.fn(),
    setDaily: vi.fn(),
    getLinsight: vi.fn(),
    setLinsight: vi.fn(),
    reload: vi.fn(),
    t: (key: string) => key,
}));

vi.mock('@/controllers/API', () => ({
    getDailyConfigApi: mocks.getDaily,
    setDailyConfigApi: mocks.setDaily,
    getLinsiConfigApi: mocks.getLinsight,
    setLinsiConfigApi: mocks.setLinsight,
}));
vi.mock('@/controllers/API/tools', () => ({ getToolsApi: vi.fn().mockResolvedValue([]) }));
vi.mock('@/controllers/request', () => ({ handleUiRequest: (handler: () => unknown) => handler, showApiError: vi.fn() }));
vi.mock('@/contexts/locationContext', async () => {
    const { createContext } = await import('react');
    return { locationContext: createContext({ appConfig: { isPro: false }, reloadConfig: mocks.reload }) };
});
vi.mock('@/contexts/userContext', async () => {
    const { createContext } = await import('react');
    return { userContext: createContext({ user: {} }) };
});
// A stable t: useChatConfig reloads the config whenever t changes identity.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('i18next', () => ({ default: { loadLanguages: async () => undefined, getFixedT: () => (key: string) => key } }));
vi.mock('../ConfigInheritanceBanner', () => ({ default: () => null, resolveConfigEnvelope: (data: unknown) => ({ data, meta: {} }) }));
vi.mock('../ToolsConfig', () => ({ default: () => null }));
vi.mock('../OrgKbConfig', () => ({ default: () => null }));
vi.mock('../RecommendedAppsConfig', () => ({ default: () => null }));
vi.mock('../Preview', () => ({ default: () => null }));
vi.mock('../IconUploadSection', () => ({ IconUploadSection: () => null }));
vi.mock('../WorkbenchSensitivePolicy', () => ({ WorkbenchSensitivePolicy: () => null }));
vi.mock('@/pages/ModelPage/manage', () => ({
    useModel: () => ({ llmOptions: [{ value: 1, label: 'Provider', children: [{ value: '7', label: 'model-7' }, { value: '9', label: 'model-9' }] }] }),
}));
// The shared Cascader needs layout APIs jsdom lacks; a native select keeps the value flow observable.
vi.mock('@/pages/ModelPage/manage/tabs/KnowledgeModel', () => ({
    ModelSelect: ({ label, value, options, onChange, placeholder }: {
        label: string; value: string; placeholder: string;
        options: { children: { value: string; label: string }[] }[];
        onChange: (value: string | null) => void;
    }) => (
        <select aria-label={label} value={value ?? ''} onChange={event => onChange(event.target.value || null)}>
            <option value="">{placeholder}</option>
            {options.flatMap(group => group.children).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
    ),
}));

function renderPage() {
    return render(<MemoryRouter><DailyChatConfig /></MemoryRouter>);
}

async function memorySelect() {
    const select = await screen.findByRole('combobox', { name: 'chatConfig.memoryModel' });
    await waitFor(() => expect(mocks.getDaily).toHaveBeenCalled());
    return select as HTMLSelectElement;
}

beforeEach(() => {
    vi.clearAllMocks();
    mocks.getDaily.mockResolvedValue({ systemPrompt: 'prompt', tools: [] });
    mocks.getLinsight.mockResolvedValue({ tab_display_name: 'Task' });
    mocks.setDaily.mockResolvedValue(true);
    mocks.setLinsight.mockResolvedValue(true);
});
afterEach(cleanup);

describe('workbench memory model', () => {
    it('AC-106: the selected model is saved as memory_model_id', async () => {
        renderPage();
        const select = await memorySelect();
        fireEvent.change(select, { target: { value: '9' } });
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.setDaily).toHaveBeenCalledWith(expect.objectContaining({ memory_model_id: 9 })));
    });

    it('AC-106: nothing selected saves an empty memory_model_id and shows the default-model placeholder', async () => {
        renderPage();
        const select = await memorySelect();
        expect(select.value).toBe('');
        expect(screen.getByRole('option', { name: 'chatConfig.memoryModelPlaceholder' })).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.setDaily).toHaveBeenCalledWith(expect.objectContaining({ memory_model_id: null })));
    });

    it('AC-106: a saved model loads into the select and clearing it saves empty', async () => {
        mocks.getDaily.mockResolvedValue({ systemPrompt: 'prompt', tools: [], memory_model_id: 7 });
        renderPage();
        const select = await memorySelect();
        await waitFor(() => expect(select.value).toBe('7'));
        fireEvent.change(select, { target: { value: '' } });
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.setDaily).toHaveBeenCalledWith(expect.objectContaining({ memory_model_id: null })));
    });

    it('AC-106: the workbench page has no memory on/off switch', async () => {
        renderPage();
        await memorySelect();
        const switches = screen.queryAllByRole('switch');
        switches.forEach(item => expect(item.closest('[data-memory-model]')).toBeNull());
        expect(screen.queryByRole('switch', { name: /memory/i })).toBeNull();
        expect(screen.queryByText(/memoryEnabled|memorySwitch/)).toBeNull();
    });

    it('AC-106: the label and placeholder exist in all three languages', () => {
        for (const locale of [zhHans, enUS, ja]) {
            expect(locale.chatConfig.memoryModel.length).toBeGreaterThan(0);
            expect(locale.chatConfig.memoryModelPlaceholder.length).toBeGreaterThan(0);
            expect(locale.chatConfig.memoryModelHint.length).toBeGreaterThan(0);
        }
    });
});
