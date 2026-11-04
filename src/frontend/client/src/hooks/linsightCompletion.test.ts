import { closeCompletedTaskRows } from './linsightCompletion';

it('closes stale checklist rows after final_result without inventing successful work', () => {
    const tasks = ['success', 'failed', 'terminated', 'in_progress', 'not_started'].map((status) => ({ id: status, name: status, status }));
    expect(closeCompletedTaskRows(tasks).map((task) => task.status))
        .toEqual(['success', 'failed', 'terminated', 'terminated', 'terminated']);
    expect(tasks[3].status).toBe('in_progress');
});

it('closes child tasks while preserving titles and execution history', () => {
    const history = [{ name: 'web_search', output: 'Existing source output' }];
    const result = closeCompletedTaskRows([{
        id: 'parent', name: 'Research', status: 'success', history,
        children: [{ id: 'child', name: 'Read sources', status: 'in_progress' }],
    }]);
    expect(result[0].status).toBe('success');
    expect(result[0].children?.[0]).toEqual({ id: 'child', name: 'Read sources', status: 'terminated', children: [] });
    expect(result[0].history).toBe(history);
});
