import {
    type ArtifactFile,
    artifactVersionId,
    collectConversationWorkspaceFiles,
    getWorkspaceLoadState,
} from './artifactUtils';

const makeArtifact = (overrides: Partial<ArtifactFile>): ArtifactFile => ({
    file_id: overrides.file_id || Math.random().toString(36).slice(2),
    file_name: overrides.file_name || 'artifact.md',
    file_url: overrides.file_url || 'linsight/final_result/version/artifact.md',
    ...overrides,
});

describe('collectConversationWorkspaceFiles', () => {
    it('keeps prior deliverables when the latest round has no final files', () => {
        const report = makeArtifact({ file_name: 'report.md', file_url: 'final/old/report.md' });

        expect(collectConversationWorkspaceFiles([
            { versionId: 'v1', snapshot: { file_list: [report] } },
            { versionId: 'v2', snapshot: { file_list: [] } },
        ])).toEqual([{ ...report, versionId: 'v1' }]);
    });

    it('lets a newer round replace the same workspace path', () => {
        const oldReport = makeArtifact({
            file_name: 'report.md',
            file_url: 'final/old/report.md',
            file_path: '/cache/old/output/report.md',
        });
        const newReport = makeArtifact({
            file_name: 'report.md',
            file_url: 'final/new/report.md',
            file_path: '/cache/new/output/report.md',
        });

        expect(collectConversationWorkspaceFiles([
            { versionId: 'v1', snapshot: { file_list: [oldReport] } },
            { versionId: 'v2', snapshot: { file_list: [newReport] } },
        ])).toEqual([{ ...newReport, versionId: 'v2' }]);
    });

    it('includes completed history rounds when multiple rounds share one version', () => {
        const first = makeArtifact({ file_name: 'round-one.md' });
        const second = makeArtifact({ file_name: 'round-two.docx' });

        expect(collectConversationWorkspaceFiles([{
            versionId: 'v1',
            snapshot: { history: [{ file_list: [first] }], file_list: [second] },
        }])).toEqual([{ ...first, versionId: 'v1' }, { ...second, versionId: 'v1' }]);
    });

    it('keeps uploaded sources separate from generated files with the same name', () => {
        const output = makeArtifact({ file_name: 'requirements.docx', source: 'output' });
        const files = collectConversationWorkspaceFiles([{
            versionId: 'v1',
            snapshot: {
                files: [{
                    file_id: 'upload-1',
                    file_name: 'requirements.docx',
                    markdown_file_path: 'workspace/version/uploads/requirements.md',
                }],
                file_list: [output],
            },
        }]);

        expect(files).toHaveLength(2);
        expect(files.map((file) => file.source)).toEqual(['upload', 'output']);
    });

    it('tags each file with the turn that produced it, not the latest turn', () => {
        // Regression: the workspace panel resolved an earlier turn's file with the
        // latest turn's id and the backend's owned_file_key check answered 403.
        const pdf = makeArtifact({ file_name: 'plan.pdf', file_url: 'linsight/final_result/v1/plan.pdf' });
        const files = collectConversationWorkspaceFiles([
            { versionId: 'v1', snapshot: { file_list: [pdf] } },
            { versionId: 'v2', snapshot: { file_list: [] } },
        ]);

        expect(files).toHaveLength(1);
        expect(artifactVersionId(files[0], 'v2')).toBe('v1');
    });
});

describe('getWorkspaceLoadState', () => {
    const none = new Set<string>();

    it('is loading while a task turn has neither detail nor a failure marker', () => {
        expect(getWorkspaceLoadState(['a', 'b'], new Set(['a']), none)).toBe('loading');
    });

    it('stays loading while another turn is pending even if one failed', () => {
        expect(getWorkspaceLoadState(['a', 'b'], none, new Set(['a']))).toBe('loading');
    });

    it('reports failed once every unloaded turn has failed', () => {
        expect(getWorkspaceLoadState(['a', 'b'], new Set(['b']), new Set(['a']))).toBe('failed');
    });

    it('is ready when every turn is loaded or there are no task turns', () => {
        expect(getWorkspaceLoadState(['a'], new Map([['a', {}]]), none)).toBe('ready');
        expect(getWorkspaceLoadState([], none, none)).toBe('ready');
    });
});
