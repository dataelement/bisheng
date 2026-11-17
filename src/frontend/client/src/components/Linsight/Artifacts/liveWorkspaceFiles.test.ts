import { renderHook } from '@testing-library/react';
import { act } from 'react';
import { useRunStore, type RunFileData } from '~/store/runStore';
import type { ArtifactFile } from './artifactUtils';
import { mergeWorkspaceFiles, newLiveArtifacts, toLiveArtifact, useNewLiveArtifacts } from './liveWorkspaceFiles';

let mockEnabled: boolean | undefined = true;
jest.mock('~/hooks/queries/data-provider', () => ({
    useGetBsConfig: () => ({ data: { unified_runtime_enabled: mockEnabled } }),
}));

const live = (over: Partial<RunFileData> = {}): RunFileData => ({
    file_id: 'f1',
    name: 'report.md',
    path: 'linsight/final_result/sv1/f1.md',
    size: 10,
    source: 'final_result',
    ...over,
});

describe('toLiveArtifact', () => {
    it('maps a turn-owned object key to an artifact resolved against that turn (AC-24)', () => {
        expect(toLiveArtifact(live())).toEqual({
            file_id: 'f1',
            file_name: 'report.md',
            file_url: 'linsight/final_result/sv1/f1.md',
            source: 'output',
            versionId: 'sv1',
        });
    });
    it('drops a bucket prefix and a leading slash from the key', () => {
        expect(toLiveArtifact(live({ path: '/bisheng/linsight/session_files/sv2/a.png' }))).toMatchObject({
            file_url: 'linsight/session_files/sv2/a.png',
            versionId: 'sv2',
        });
    });
    it('lists a workspace output file of the run through the run file endpoint (AC-24)', () => {
        expect(toLiveArtifact(live({ file_id: 'abc', name: 'report.xlsx', path: 'output/report.xlsx' }), 'c1')).toEqual({
            file_id: 'abc',
            file_name: 'report.xlsx',
            file_url: 'output/report.xlsx',
            source: 'output',
            directUrl: '/api/v1/workstation/conversations/c1/files/abc/url',
            attachment: { conversationId: 'c1', fileId: 'abc', run: true },
        });
    });
    it('does not list a file whose path the download helper cannot resolve', () => {
        expect(toLiveArtifact(live({ path: 'output/report.xlsx' }))).toBeNull();
        expect(toLiveArtifact(live({ path: 'scratch/notes.md' }), 'c1')).toBeNull();
        expect(toLiveArtifact(live({ path: 'workspace/c1/output/report.xlsx' }), 'c1')).toBeNull();
        expect(toLiveArtifact(live({ path: '' }))).toBeNull();
        expect(toLiveArtifact(live({ file_id: '' }))).toBeNull();
    });
});

describe('mergeWorkspaceFiles', () => {
    const known: ArtifactFile[] = [
        { file_id: 'h1', file_name: 'old.md', file_url: 'linsight/final_result/sv0/h1.md', versionId: 'sv0' },
    ];
    it('appends live files after the history files', () => {
        expect(mergeWorkspaceFiles(known, [live()]).map((f) => f.file_id)).toEqual(['h1', 'f1']);
    });
    it('keeps the history entry when the ids match', () => {
        const merged = mergeWorkspaceFiles(known, [live({ file_id: 'h1', name: 'renamed.md' })]);
        expect(merged).toBe(known);
    });
    it('keeps the history entry when only the paths match', () => {
        const merged = mergeWorkspaceFiles(known, [live({ file_id: 'other', path: '/linsight/final_result/sv0/h1.md' })]);
        expect(merged).toBe(known);
    });
    it('lists two live events of one path once', () => {
        expect(newLiveArtifacts([], [live(), live({ file_id: 'f2' })])).toHaveLength(1);
    });
    it('returns the same array when there is nothing to add', () => {
        expect(mergeWorkspaceFiles(known, [])).toBe(known);
        expect(mergeWorkspaceFiles(known, [live({ path: 'output/x.md' })])).toBe(known);
    });
});

describe('useNewLiveArtifacts', () => {
    const known: ArtifactFile[] = [];
    beforeEach(() => {
        mockEnabled = true;
        act(() => useRunStore.getState().resetConversation('c1'));
    });
    const emit = (file: RunFileData) =>
        act(() => {
            useRunStore.getState().applyEvent('c1', { type: 'run_started', data: {}, run_id: 'r1' });
            useRunStore.getState().applyEvent('c1', { type: 'file', data: file, run_id: 'r1' });
        });

    it('lists a file while the run is still going (AC-24)', () => {
        const { result } = renderHook(() => useNewLiveArtifacts(known, 'c1'));
        expect(result.current).toEqual([]);
        emit(live());
        expect(useRunStore.getState().conversations.c1.run?.status).toBe('running');
        expect(result.current.map((f) => f.file_id)).toEqual(['f1']);
    });
    it('stays empty when the tenant switch is off or missing', () => {
        mockEnabled = false;
        const off = renderHook(() => useNewLiveArtifacts(known, 'c1'));
        emit(live());
        expect(off.result.current).toEqual([]);
        mockEnabled = undefined;
        const missing = renderHook(() => useNewLiveArtifacts(known, 'c1'));
        expect(missing.result.current).toEqual([]);
    });
    it('is scoped to its conversation', () => {
        const { result } = renderHook(() => useNewLiveArtifacts(known, 'c2'));
        emit(live());
        expect(result.current).toEqual([]);
    });
});
