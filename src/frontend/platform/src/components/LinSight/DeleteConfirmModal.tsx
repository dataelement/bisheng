import { Button } from "@/components/bs-ui/button";

interface DeleteConfirmModalProps {
    open: boolean;
    content: string;
    cancelText: string;
    okText: string;
    onClose: () => void;
    onConfirm: () => void;
}

export default function DeleteConfirmModal({ open, content, cancelText, okText, onClose, onConfirm }: DeleteConfirmModalProps) {
    if (!open) return null;
    return (
        <div className="fixed inset-0 z-[1000] bg-opacity-50 flex items-center justify-center">
            <div className="relative rounded-lg p-6 w-[500px]  h-[150px]" style={{ background: 'white', opacity: 1, border: '1px solid #e5e7eb' }}>
                <button
                    className="absolute top-3 right-3 text-gray-400 hover:text-gray-600"
                    onClick={onClose}
                >
                    ×
                </button>
                <p className="text-gray-600 text-center mb-6">{content}</p>
                <div className="flex justify-between space-x-3">
                    <Button variant="ghost" onClick={onClose}>
                        {cancelText}
                    </Button>
                    <Button type="button" onClick={onConfirm}>
                        {okText}
                    </Button>
                </div>
            </div>
        </div>
    );
}


