import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Button } from "@/components/bs-ui/button";
import { UploadIcon } from "@/components/bs-icons";

interface LocalFileImportDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    t: (key: string, params?: any) => string;
    getRootProps: any;
    getInputProps: any;
    importFiles: File[];
    isImporting: boolean;
    onImport: () => Promise<void> | void;
    onCancel: () => void;
    downloadExample: () => void;
}

export default function LocalFileImportDialog({ open, onOpenChange, t, getRootProps, getInputProps, importFiles, isImporting, onImport, onCancel, downloadExample }: LocalFileImportDialogProps) {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[1200px]">
                <DialogHeader>
                    <DialogTitle>{t('chatConfig.importManual')}</DialogTitle>
                </DialogHeader>

                <div className="grid gap-4 py-4">
                    <div className="flex justify-between items-center w-full">
                        <div className="flex items-center gap-2">
                            <span className="text-red-500">*</span>
                            <span>{t('chatConfig.uploadFile')}</span>
                        </div>
                        <button className="flex items-center gap-1" onClick={downloadExample}>
                            <span className="text-black">{t('chatConfig.exampleFile')}:</span>
                            <span className="text-blue-600 hover:underline">{t('chatConfig.exampleFileName')}</span>
                        </button>
                    </div>

                    <div
                        {...getRootProps()}
                        className="group h-40 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary"
                    >
                        <input {...getInputProps()} />
                        <UploadIcon className="group-hover:text-primary size-5" />
                        <p className="text-sm">{t('code.clickOrDragHere')}</p>
                    </div>

                    {importFiles.length > 0 && (
                        <div className="text-sm text-start text-green-500 mt-2">
                            {importFiles.slice(0, 1).map((file, index) => (
                                <div key={index}>
                                    <span>{file.name}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={onCancel}>
                        {t('cancel')}
                    </Button>
                    <Button onClick={onImport} disabled={isImporting || importFiles.length === 0}>
                        {isImporting ? t('chatConfig.importing') : t('submit')}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    )
}


