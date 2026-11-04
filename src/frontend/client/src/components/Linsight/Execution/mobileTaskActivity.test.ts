import { getMobileTaskActivity } from './mobileTaskActivity';
import type { ExecStepEventData } from './execTypes';

it.each([
    ['web_search', 'start', 'searching'],
    ['read_file', 'start', 'reading'],
    ['write_file', 'start', 'writing'],
    ['thinking', 'end', 'researching'],
    ['web_search', 'end', 'researching'],
] as const)('shows activity for %s/%s without exposing its output', (name, status, expected) => {
    const frame: ExecStepEventData = { name, status };
    Object.defineProperty(frame, 'output', { get: () => { throw new Error('Do not read process bodies'); } });
    expect(getMobileTaskActivity([frame], [])).toBe(expected);
});

it('uses the newest child-task activity instead of old session output', () => {
    expect(getMobileTaskActivity([{ name: 'web_search', status: 'start', timestamp: 1 }], [{
        id: 'parent', name: 'Research', status: 'in_progress', children: [{
            id: 'child', name: 'Read sources', status: 'in_progress',
            history: [{ name: 'read_file', status: 'start', timestamp: 2 }],
        }],
    }])).toBe('reading');
});

it('keeps a generic working status before task output arrives', () => {
    expect(getMobileTaskActivity([], [])).toBe('researching');
});

it('shows result preparation while the session is running with all tasks done', () => {
    expect(getMobileTaskActivity([], [{ id: 'done', name: 'Research', status: 'success' }])).toBe('summarizing');
});
