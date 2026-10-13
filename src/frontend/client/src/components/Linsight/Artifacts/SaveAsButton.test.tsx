import { createEvent, fireEvent, render, screen } from '@testing-library/react';
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
    it.each(['Enter', ' '])('does not pass modal %s key presses to the parent file row', (key) => {
        const handleFilePreview = jest.fn();

        render(
            <div onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    handleFilePreview();
                }
            }}>
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

        const modal = screen.getByTestId('save-as-modal-blank');
        const event = createEvent.keyDown(modal, { key, bubbles: true, cancelable: true });
        fireEvent(modal, event);

        expect(handleFilePreview).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(false);
    });

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
