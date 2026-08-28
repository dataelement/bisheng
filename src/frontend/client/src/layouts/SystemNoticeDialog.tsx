import { Button } from '~/components/ui/Button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/Dialog';
import { useLocalize } from '~/hooks';

interface SystemNoticeDialogProps {
  notice: string;
  onClose: () => void;
}

export function SystemNoticeDialog({ notice, onClose }: SystemNoticeDialogProps) {
  const localize = useLocalize();

  return (
    <Dialog
      open={Boolean(notice)}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-md w-[calc(100%-40px)] rounded-2xl mx-auto top-[50%] -translate-y-[50%]">
        <DialogHeader>
          <DialogTitle className="text-center text-lg font-medium">
            {localize('com_ui.system_notice_title')}
          </DialogTitle>
        </DialogHeader>
        <div className="py-6 px-2">
          <div className="text-sm text-gray-700 leading-relaxed text-center whitespace-pre-wrap">
            {notice}
          </div>
        </div>
        <DialogFooter className="sm:justify-center flex-row justify-center pb-2">
          <Button onClick={onClose} className="w-[120px] rounded-full">
            {localize('com_ui.system_notice_acknowledge')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
