import { normalizeModelNames } from './modelConfig';

test.each(['', '   ', null, undefined])('uses the current model name for a cleared alias %p', displayName => {
  const model = { id: '42', name: 'qwen-max', displayName, visual: true };
  expect(normalizeModelNames([model])).toEqual([{ ...model, displayName: 'qwen-max' }]);
  expect(model.displayName).toBe(displayName);
});

test('resolves rename, clearing and another rename using each current response', () => {
  const model = { id: '42', name: 'qwen-max' };
  expect(['First', '', 'Next'].map(displayName => normalizeModelNames([{ ...model, displayName }])[0]))
    .toEqual(['First', 'qwen-max', 'Next'].map(displayName => ({ ...model, displayName })));
});
