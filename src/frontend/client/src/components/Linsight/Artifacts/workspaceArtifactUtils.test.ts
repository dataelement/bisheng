import {
    type ArtifactFile,
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
            { file_list: [report] },
            { file_list: [] },
        ])).toEqual([report]);
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
            { file_list: [oldReport] },
            { file_list: [newReport] },
        ])).toEqual([newReport]);
    });

    it('includes completed history rounds when multiple rounds share one version', () => {
        const first = makeArtifact({ file_name: 'round-one.md' });
        const second = makeArtifact({ file_name: 'round-two.docx' });

        expect(collectConversationWorkspaceFiles([{
            history: [{ file_list: [first] }],
            file_list: [second],
        }])).toEqual([first, second]);
    });

    it('keeps uploaded sources separate from generated files with the same name', () => {
        const output = makeArtifact({ file_name: 'requirements.docx', source: 'output' });
        const files = collectConversationWorkspaceFiles([{
            files: [{
                file_id: 'upload-1',
                file_name: 'requirements.docx',
                markdown_file_path: 'workspace/version/uploads/requirements.md',
            }],
            file_list: [output],
        }]);

        expect(files).toHaveLength(2);
        expect(files.map((file) => file.source)).toEqual(['upload', 'output']);
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
