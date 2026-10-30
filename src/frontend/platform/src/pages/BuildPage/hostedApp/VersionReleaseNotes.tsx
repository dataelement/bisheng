import { Button } from "@bisheng/ui"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog"
import { useTranslation } from "react-i18next"

interface VersionReleaseNotesProps {
  notes?: string | null
}

export function VersionReleaseNotes({ notes }: VersionReleaseNotesProps) {
  const { t } = useTranslation()

  return <Dialog key={notes}>
    <DialogTrigger asChild>
      <Button variant="link" size="small">
        {t("hostedApp.releaseNotes.column")}
      </Button>
    </DialogTrigger>
    <DialogContent aria-modal="true" className="max-w-xl max-h-[calc(100dvh-4rem)]">
      <DialogHeader>
        <DialogTitle>{t("hostedApp.releaseNotes.column")}</DialogTitle>
      </DialogHeader>
      <DialogDescription className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words text-body-sm text-text-1 [overflow-wrap:anywhere]">
        {notes?.trim() ? notes : t("hostedApp.releaseNotes.empty")}
      </DialogDescription>
    </DialogContent>
  </Dialog>
}
