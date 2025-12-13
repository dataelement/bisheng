import { LoadIcon } from "@/components/bs-icons";
import { Button } from "@/components/bs-ui/button";

interface SopActionsBarProps {
    importFromRecord: () => void;
    importFromLocal: () => void;
    createManual: () => void;
    batchDelete: () => void;
    batchDeleting: boolean;
    disableBatchDelete: boolean;
    importText: string;
    importLocalText: string;
    createText: string;
    batchDeleteText: string;
}

export default function SopActionsBar({
    importFromRecord,
    importFromLocal,
    createManual,
    batchDelete,
    batchDeleting,
    disableBatchDelete,
    importText,
    importLocalText,
    createText,
    batchDeleteText
}: SopActionsBarProps) {
    return (
        <div className="flex gap-2">
            <Button variant="default" size="sm" onClick={importFromRecord}>
                {importText}
            </Button>
            <Button variant="outline" size="sm" onClick={importFromLocal}>
                {importLocalText}
            </Button>
            <Button variant="outline" size="sm" onClick={createManual}>
                {createText}
            </Button>
            <Button
                variant="outline"
                size="sm"
                disabled={disableBatchDelete || batchDeleting}
                onClick={batchDelete}
            >
                {batchDeleting && <LoadIcon className=" mr-2 text-gray-600" />}
                {batchDeleteText}
            </Button>
        </div>
    );
}


