import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

interface ValidationDialogProps {
    open: boolean;
    statusMessage: string;
    t: (key: string, params?: any) => string;
    onConfirm: () => void;
    onOpenChange: (open: boolean) => void;
}

export default function ValidationDialog({ open, statusMessage, t, onConfirm, onOpenChange }: ValidationDialogProps) {
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[500px] max-h-[80vh]" close={false as any}>
                <div className="absolute left-0 top-0 h-full w-1.5 bg-blue-500"></div>
                <div
                    className="pl-4 overflow-y-auto"
                    style={{
                        maxHeight: 'calc(80vh - 2rem)',
                        scrollbarWidth: 'thin',
                        scrollbarColor: '#3b82f6 transparent'
                    }}
                >
                    <DialogHeader>
                        <div className="flex items-center gap-4">
                            <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center">
                                <span className="text-white font-bold text-lg">i</span>
                            </div>
                            <DialogTitle>{t('chatConfig.fileFormatError')}</DialogTitle>
                        </div>
                    </DialogHeader>

                    <div className="py-4">
                        {statusMessage && (
                            <div className="space-y-2">
                                <p className="font-medium">
                                    {statusMessage.split("：")[0]}：
                                </p>
                                {statusMessage.includes("：") && (
                                    <div className="text-sm text-gray-600">
                                        {statusMessage.split("：")[1].split("\n").map((line, index) => (
                                            <p key={index}>{line.trim()}</p>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    <div className="flex justify-end">
                        <Button onClick={onConfirm}>
                            {t('chatConfig.gotIt')}
                        </Button>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}


