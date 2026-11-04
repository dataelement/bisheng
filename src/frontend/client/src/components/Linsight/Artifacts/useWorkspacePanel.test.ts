import { act, renderHook } from '@testing-library/react';
import { useWorkspacePanel } from './useWorkspacePanel';

const mockOpenHtml = jest.fn();
jest.mock('./artifactUtils', () => ({
  isHtmlArtifact: (file: { file_name: string }) => file.file_name.endsWith('.html'),
  openHtmlArtifactViewer: (...args: unknown[]) => mockOpenHtml(...args),
}));

const file = { file_id: 'a', file_name: 'a.pdf', file_url: '/a.pdf', directUrl: '/a.pdf' };
describe('conversation preview lifecycle', () => {
  it('resets between two ordinary chats even when both have no research version', () => {
    const { result, rerender } = renderHook(({ chat }) => useWorkspacePanel('', chat), { initialProps: { chat: 'one' } });
    act(() => result.current.openPreview(file));
    expect(result.current.open).toBe(true);
    rerender({ chat: 'two' });
    expect(result.current.open).toBe(false);
    expect(result.current.previewFile).toBeNull();
  });
  it('retains an open document when the same conversation starts another research turn', () => {
    const { result, rerender } = renderHook(({ version }) => useWorkspacePanel(version, 'one'), { initialProps: { version: 'v1' } });
    act(() => result.current.openPreview(file));
    rerender({ version: 'v2' });
    expect(result.current.previewFile).toEqual(file);
    expect(result.current.open).toBe(true);
  });
  it('resolves standalone HTML with the research version rather than the conversation ID', () => {
    const { result } = renderHook(() => useWorkspacePanel('v1', 'chat1'));
    const html = { ...file, file_name: 'a.html', directUrl: undefined };
    act(() => result.current.openPreview(html));
    expect(mockOpenHtml).toHaveBeenCalledWith(html, 'v1');
  });
  it('opens an ordinary HTML attachment in the shared preview', () => {
    const { result } = renderHook(() => useWorkspacePanel('', 'chat1'));
    const html = { ...file, file_name: 'a.html' };
    act(() => result.current.openPreview(html));
    expect(result.current.previewFile).toEqual(html);
  });
  it('closes fullscreen with the panel and reopens on the file list', () => {
    const { result } = renderHook(() => useWorkspacePanel('v1', 'one'));
    act(() => result.current.openPreview(file));
    act(() => result.current.toggleFullscreen());
    act(() => result.current.closeWorkspace());
    expect(result.current.fullscreen).toBe(false);
    act(() => result.current.openWorkspace());
    expect(result.current.previewFile).toBeNull();
  });
});
