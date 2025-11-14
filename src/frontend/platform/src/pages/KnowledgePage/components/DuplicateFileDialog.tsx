import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

const DialogWithRepeatFiles = ({
    repeatFiles, setRepeatFiles, retryLoad, t, unRetry, onRetry
}) => {
    return (
        <Dialog open={!!repeatFiles.length} onOpenChange={b => !b && setRepeatFiles([])}>
            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>{t('modalTitle')}</DialogTitle>
                    <DialogDescription>{t('modalMessage')}</DialogDescription>
                </DialogHeader>
                <ul className="overflow-y-auto max-h-[400px] py-2">
                    {repeatFiles.map(el => (
                        <li key={el.id} className="py-1 text-red-500 text-sm">{el.remark}</li>
                    ))}
                </ul>
                <DialogFooter>
                    <Button className="h-8" variant="outline" onClick={unRetry}>
                        {t('keepOriginal')}
                    </Button>
                    <Button className="h-8" disabled={retryLoad} onClick={() => onRetry(repeatFiles)}>
                        {retryLoad && <span className="loading loading-spinner loading-xs mr-1"></span>}
                        {t('override')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

export default DialogWithRepeatFiles;
