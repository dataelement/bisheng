import { applyToolDefaults } from './agentToolDefaults';
import type { AvailableToolGroup } from './AgentToolSelector';

const web: AvailableToolGroup = { id: 1, name: 'Web', default_checked: true, children: [{ id: 11, tool_key: 'web_search' }] };
const code: AvailableToolGroup = { id: 2, name: 'Code', default_checked: true, children: [{ id: 21, tool_key: 'bisheng_code_interpreter' }] };
const time: AvailableToolGroup = { id: 3, name: 'Time', children: [{ id: 31, tool_key: 'time' }] };

describe('applyToolDefaults', () => {
    it('preselects every default as auto for a new account', () => {
        const { selection, applied } = applyToolDefaults(undefined, undefined, [web, code, time]);
        expect(selection.map((g) => [g.id, g.auto])).toEqual([[1, true], [2, true]]);
        expect(applied.sort()).toEqual([1, 2]);
    });

    it('keeps a default the user turned off', () => {
        const { selection } = applyToolDefaults([], [1, 2], [web, code, time]);
        expect(selection).toEqual([]);
    });

    it('adds a group that became a default after the last visit', () => {
        const restored = [{ id: 3, name: 'Time', children: [] }];
        const { selection } = applyToolDefaults(restored, [1], [web, code, time]);
        expect(selection.map((g) => [g.id, g.auto])).toEqual([[3, undefined], [2, true]]);
    });

    it('treats defaults in a legacy snapshot as preselected and keeps manual picks visible', () => {
        const restored = [{ id: 1, name: 'Web', children: [] }, { id: 3, name: 'Time', children: [] }];
        const { selection } = applyToolDefaults(restored, undefined, [web, code, time]);
        expect(selection.map((g) => [g.id, g.auto])).toEqual([[1, true], [3, undefined], [2, true]]);
    });

    it('adds only the code executor to a legacy snapshot where the user turned web search off', () => {
        const { selection, applied } = applyToolDefaults([], undefined, [web, code, time]);
        expect(selection.map((g) => [g.id, g.auto])).toEqual([[2, true]]);
        expect(applied.sort()).toEqual([1, 2]);
    });

    it('skips a default whose tools are all disabled for the account', () => {
        const off = { ...code, children: [{ id: 21, tool_key: 'bisheng_code_interpreter', enabled: false }] };
        const { selection } = applyToolDefaults(undefined, undefined, [off]);
        expect(selection).toEqual([]);
    });
});
