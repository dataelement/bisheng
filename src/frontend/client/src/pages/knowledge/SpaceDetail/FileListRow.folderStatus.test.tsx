/**
 * IKC813 regression: in a multi-level knowledge file tree, a folder with a
 * failed descendant must show the failure ("com_knowledge.fail") status itself.
 * The backend computes `has_failed_files` for every ancestor level; both list
 * renderers used to ignore it for folder rows, so a failed file nested inside
 * sub-folders left every parent folder looking clean.
 */
import { render, screen } from '@testing-library/react';
import { FileStatus, FileType, SpaceRole, type KnowledgeFile } from '~/api/knowledge';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
    useMediaQuery: () => false,
}));

jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy({}, { get: () => () => null }),
}));

jest.mock('@bisheng/ui', () => ({
    Button: () => null,
}));

jest.mock('~/components', () => ({
    Checkbox: () => null,
    DropdownMenu: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    DropdownMenuTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

jest.mock('~/components/ActionMenu', () => ({
    ActionMenuContent: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    ActionMenuItem: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

jest.mock('~/components/ui/Tooltip2', () => ({
    Tooltip: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    TooltipContent: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    TooltipTrigger: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

jest.mock('./FileIcon', () => () => null);
jest.mock('./TagGroup', () => () => null);

import { FileListRow } from './FileListRow';
import { FileCard } from './FileCard';

const noop = () => {};

const folder = (hasFailedFiles?: boolean) =>
    ({
        id: '1',
        name: 'folder',
        type: FileType.FOLDER,
        status: undefined,
        hasFailedFiles,
    }) as unknown as KnowledgeFile;

const successFile = {
    id: '2',
    name: 'file.pdf',
    type: FileType.PDF,
    status: FileStatus.SUCCESS,
} as unknown as KnowledgeFile;

describe('FileListRow folder failure status (IKC813)', () => {
    it('shows the failure pill on a folder whose subtree contains a failed file', () => {
        render(
            <FileListRow
                file={folder(true)}
                index={0}
                isAdmin
                isSelected={false}
                onSelect={noop}
                onDownload={noop}
                onEditTags={noop}
                onRename={noop}
                onDelete={noop}
                onRetry={noop}
            />,
        );
        expect(screen.getByText('com_knowledge.fail')).toBeTruthy();
    });

    it('shows no status pill on a clean folder', () => {
        render(
            <FileListRow
                file={folder()}
                index={0}
                isAdmin
                isSelected={false}
                onSelect={noop}
                onDownload={noop}
                onEditTags={noop}
                onRename={noop}
                onDelete={noop}
                onRetry={noop}
            />,
        );
        expect(screen.queryByText('com_knowledge.fail')).not.toBeTruthy();
    });

    it('keeps hiding the pill on successful files', () => {
        render(
            <FileListRow
                file={successFile}
                index={0}
                isAdmin
                isSelected={false}
                onSelect={noop}
                onDownload={noop}
                onEditTags={noop}
                onRename={noop}
                onDelete={noop}
                onRetry={noop}
            />,
        );
        expect(screen.queryByText('com_knowledge.fail')).not.toBeTruthy();
    });
});

describe('FileCard folder failure status (IKC813)', () => {
    it('shows the failure pill on a folder whose subtree contains a failed file', () => {
        render(
            <FileCard
                file={folder(true)}
                userRole={SpaceRole.ADMIN}
                isSelected={false}
                onSelect={noop}
                onDownload={noop}
                onRename={noop}
                onDelete={noop}
                onEditTags={noop}
                onRetry={noop}
            />,
        );
        expect(screen.getByText('com_knowledge.fail')).toBeTruthy();
    });

    it('shows no status pill on a clean folder', () => {
        render(
            <FileCard
                file={folder()}
                userRole={SpaceRole.ADMIN}
                isSelected={false}
                onSelect={noop}
                onDownload={noop}
                onRename={noop}
                onDelete={noop}
                onEditTags={noop}
                onRetry={noop}
            />,
        );
        expect(screen.queryByText('com_knowledge.fail')).not.toBeTruthy();
    });
});
