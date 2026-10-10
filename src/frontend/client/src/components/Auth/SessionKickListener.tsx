import { useEffect } from "react";
import i18next from "i18next";
import { setSessionKickHandler, markSessionKickAck } from "~/api/request";
import { useConfirm } from "~/Providers";
import { redirectToLogin } from "~/utils/loginRedirect";

/**
 * Bridges the axios interceptor to the Confirm dialog: when another device
 * takes the session (10604), show an acknowledge-only prompt, then send the
 * user to login. Must sit under ConfirmProvider.
 */
export function SessionKickListener() {
  const confirm = useConfirm();

  useEffect(() => {
    setSessionKickHandler((message) => {
      void confirm({
        title: i18next.t("com_auth.session_kicked_title"),
        description: message,
        confirmText: i18next.t("com_auth.got_it"),
        hideCancel: true,
        variant: "default",
      }).then(() => {
        markSessionKickAck();
        redirectToLogin();
      });
    });
    return () => setSessionKickHandler(null);
  }, [confirm]);

  return null;
}
