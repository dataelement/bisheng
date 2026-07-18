import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

export interface UseNotificationsFromUrlResult {
  open: boolean;
  setOpen: (open: boolean) => void;
  focusedMessageId: number | null;
}

export function useNotificationsFromUrl(): UseNotificationsFromUrlResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const [open, setOpen] = useState<boolean>(
    () => searchParams.get("open-notifications") === "1"
  );

  const midRaw = searchParams.get("message-id");
  const focusedMessageId = midRaw && /^\d+$/.test(midRaw) ? Number(midRaw) : null;

  useEffect(() => {
    if (searchParams.get("open-notifications") === "1") {
      // Trace: visible in browser console when dialog is triggered via URL (e.g. textcard redirect)
      // eslint-disable-next-line no-console
      console.info("[notifications] auto-open", { messageId: focusedMessageId });
      const next = new URLSearchParams(searchParams);
      next.delete("open-notifications");
      next.delete("message-id");
      setSearchParams(next, { replace: true });
    }
    // run once per searchParams change
  }, [searchParams, setSearchParams, focusedMessageId]);

  return { open, setOpen, focusedMessageId };
}
