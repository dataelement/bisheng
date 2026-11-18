import { Button, Input } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog";
import type { KnowledgeSpaceChild } from "@/controllers/API/knowledgeSpace";
import type { SpaceFilePreview } from "@/controllers/API/knowledgeFiles";
import PreviewFile from "./PreviewFile";
interface SpaceDirectoryOverlaysProps {
  instance: string;
  editOpen: boolean;
  editingItem?: KnowledgeSpaceChild;
  name: string;
  setName: (value: string) => void;
  saving: boolean;
  closeEdit: () => void;
  handleSave: () => Promise<void>;
  previewOpen: boolean;
  previewItem?: KnowledgeSpaceChild;
  previewData?: SpaceFilePreview;
  closePreview: () => void;
}
export function SpaceDirectoryOverlays({
  instance,
  editOpen,
  editingItem,
  name,
  setName,
  saving,
  closeEdit,
  handleSave,
  previewOpen,
  previewItem,
  previewData,
  closePreview,
}: SpaceDirectoryOverlaysProps) {
  const { t } = useTranslation("knowledge");
  const previewFile = previewItem
    ? { ...previewItem, fileType: previewItem.parse_type ?? "", fileName: previewItem.file_name }
    : null;
  return (
    <>
      <Dialog
        open={editOpen}
        onOpenChange={(open) => {
          if (!open) closeEdit();
        }}
      >
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>{t(editingItem ? "rename" : "f118.create_folder")}</DialogTitle>
          </DialogHeader>
          <label htmlFor={`${instance}-name`}>{t(editingItem ? "name" : "f118.folder_name")}</label>
          <Input
            id={`${instance}-name`}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <DialogFooter>
            <Button variant="outlined" onClick={closeEdit}>
              {t("cancel")}
            </Button>
            <Button
              disabled={!name.trim() || saving}
              onClick={() => {
                void handleSave();
              }}
            >
              {t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={previewOpen}
        onOpenChange={(open) => {
          if (!open) closePreview();
        }}
      >
        <DialogContent className="max-w-5xl" aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>{previewItem?.file_name}</DialogTitle>
          </DialogHeader>
          {previewData && previewFile ? (
            <PreviewFile
              file={previewFile}
              rawFiles={[previewFile]}
              partitions={{}}
              chunks={[]}
              setChunks={() => undefined}
              edit={false}
              urlState={{
                load: true,
                url: previewData.preview_url || previewData.original_url,
              }}
              previewData={{
                ...previewData,
                file_source: previewData.file_source ?? undefined,
              }}
            />
          ) : (
            <p role="status">{t("loading")}</p>
          )}
          <DialogFooter>
            <Button variant="outlined" onClick={closePreview}>
              {t("cancel")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
