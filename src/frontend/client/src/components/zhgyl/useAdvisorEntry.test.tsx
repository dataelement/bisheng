import { renderHook } from '@testing-library/react';
import { useAdvisorEntry } from './useAdvisorEntry';

let mockCatalog: { name: string; display_name: string; description: string }[] | undefined;
jest.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: mockCatalog, isError: false, isFetching: false, refetch: jest.fn() }) }));
jest.mock('~/api/linsight', () => ({ getSelectableSkills: jest.fn() }));

it('restores hydrated preferences when the advisor catalog arrives after entering a scene', () => {
    mockCatalog = undefined;
    const callbacks = { setSkills: jest.fn(), setTools: jest.fn(), setTaskMode: jest.fn(), setSearchType: jest.fn() };
    const initial: Parameters<typeof useAdvisorEntry>[0] = {
        scene: 'procurement', skills: [], tools: [], taskMode: false, searchType: '', canUseTaskMode: false, ...callbacks,
    };
    const { rerender, unmount } = renderHook((props) => useAdvisorEntry(props), { initialProps: initial });
    const originalSkills = [{ name: 'synthetic-global-skill', display_name: 'Synthetic', description: 'Synthetic' }];
    mockCatalog = [{ name: 'procurement-history', display_name: 'Procurement', description: 'Synthetic' }];
    rerender({
        ...initial, skills: originalSkills, searchType: 'original-search', canUseTaskMode: true,
        config: { tools: [
            { id: 21, name: 'API', children: [{ id: 44, tool_key: 'tool_type_21_df150bfcffc4d3a398f68301818e9165', name: 'API' }] },
            { id: 22, name: 'Code', children: [{ id: 22, tool_key: 'bisheng_code_interpreter', name: 'Code' }] },
        ] },
    });
    unmount();
    expect(callbacks.setSkills).toHaveBeenLastCalledWith(originalSkills);
    expect(callbacks.setSearchType).toHaveBeenLastCalledWith('original-search');
});
