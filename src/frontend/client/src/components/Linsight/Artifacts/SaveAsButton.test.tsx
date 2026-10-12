import { fireEvent, render, screen } from '@testing-library/react';
import { SaveAsButton } from './SaveAsButton';

jest.mock('~/Providers', () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock('./useSaveArtifactToKnowledge', () => ({
    useSaveArtifactToKnowledge: () => ({
        pickerOpen: true,
        setPickerOpen: jest.fn(),
        openPicker: jest.fn(),
        saveTo: jest.fn(),
        saving: false,
    }),
}));

jest.mock('~/pages/Subscription/Article/AddToKnowledgeModal', () => ({
    AddToKnowledgeModal: ({ open }: { open: boolean }) => {
        const { createPortal } = jest.requireActual('react-dom');
        return open ? createPortal(<div data-testid="save-as-modal-blank" />, document.body) : null;
    },
}));

describe('SaveAsButton', () => {
    it('does not pass modal blank-area clicks to the parent file row', () => {
        const handleFilePreview = jest.fn();

        render(
            <div onClick={handleFilePreview}>
                <SaveAsButton
                    file={{
                        file_id: 'file-1',
                        file_name: 'report.md',
                        file_url: 'output/report.md',
                    }}
                    versionId="version-1"
                />
            </div>,
        );

        fireEvent.click(screen.getByTestId('save-as-modal-blank'));

        expect(handleFilePreview).not.toHaveBeenCalled();
    });
});
