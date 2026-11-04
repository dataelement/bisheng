import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import type { SelectedOrgKb } from '~/store/modeltype';
import { useComposerReferences } from './useComposerReferences';

test('shows a separate removable tag, keeps its space, and restores it on undo', () => {
  const space: SelectedOrgKb = { id: '12', name: 'Space', type: 'space', tag: { id: 7, name: 'Report' } };
  const { result } = renderHook(() => {
    const [spaces, setSpaces] = useState([space]);
    return { ...useComposerReferences([], spaces, () => {}, setSpaces), spaces };
  });
  const original = result.current.references.map(item => item.key);
  expect(result.current.references.map(item => item.label)).toEqual(['Space', '#Report']);
  act(() => result.current.onReferencesChange(original.slice(0, 1)));
  expect(result.current.spaces).toEqual([{ id: '12', name: 'Space', type: 'space' }]);
  act(() => result.current.onReferencesChange(original));
  expect(result.current.spaces).toEqual([space]);
  act(() => result.current.onReferencesChange([]));
  expect(result.current.spaces).toEqual([]);
});
