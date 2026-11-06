import { toast } from '@bisheng/ui';
import { PdfViewer as SharedPdfViewer, type PdfViewerProps } from '@bisheng/file-viewers/pdf';
import { useLocalize } from '~/hooks';

export function PdfViewer(props: Omit<PdfViewerProps, 'loadingText' | 'onRenderError'>) {
    const localize = useLocalize();
    return <SharedPdfViewer {...props} loadingText={localize('com_knowledge.loading')}
        onRenderError={() => toast.error(localize('com_knowledge.load_pdf_failed'))} />;
}
