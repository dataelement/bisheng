import type { ButtonHTMLAttributes } from "react";
import { useLayoutEffect, useRef } from "react";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";

interface WorkbenchMenuButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  type?: "button" | "submit" | "reset";
}

/** Only the Web shell owns the global workbench drawer. Local navigation stays separate. */
export function WorkbenchMenuButton(props: WorkbenchMenuButtonProps) {
  const { channel, capabilities } = useClientEnvironment();
  const hostOwnsHeader = capabilities?.hasHostChatHeader === true;
  const buttonRef = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (!hostOwnsHeader) return;
    // The menu and the module title share one mobile row. The app already
    // draws that chrome, so the whole row goes away with the button.
    const bar = buttonRef.current?.closest(".h-11")?.parentElement;
    if (!bar) return;
    bar.hidden = true;
    return () => {
      bar.hidden = false;
    };
  }, [hostOwnsHeader]);
  if (channel !== "web") return null;
  return <button ref={buttonRef} type="button" hidden={hostOwnsHeader} {...props} />;
}
