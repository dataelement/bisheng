import { Button } from "@bisheng/ui";
import { useTranslation } from "react-i18next";

interface SpaceProcessingActionsProps {
  busy: boolean;
  showReview: boolean;
  reviewDisabled: boolean;
  hasPlan: boolean;
  canExecute: boolean;
  onClose?: () => void;
  onReview: () => void;
  onConfirm: () => void;
  onReviewAgain: () => void;
}

export function SpaceProcessingActions({
  busy,
  showReview,
  reviewDisabled,
  hasPlan,
  canExecute,
  onClose,
  onReview,
  onConfirm,
  onReviewAgain,
}: SpaceProcessingActionsProps) {
  const { t } = useTranslation("knowledge");
  return (
    <>
      {onClose && (
        <Button variant="outlined" disabled={busy} onClick={onClose}>
          {t("close", { ns: "bs" })}
        </Button>
      )}
      {showReview &&
        (hasPlan ? (
          <>
            <Button variant="outlined" disabled={busy} onClick={onReviewAgain}>
              {t("f118.processing_review_again")}
            </Button>
            <Button disabled={busy || !canExecute} onClick={onConfirm}>
              {t("confirm", { ns: "bs" })}
            </Button>
          </>
        ) : (
          <Button disabled={reviewDisabled} onClick={onReview}>
            {t("f118.processing_review_action")}
          </Button>
        ))}
    </>
  );
}
