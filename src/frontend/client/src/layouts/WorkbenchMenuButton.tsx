import type { ButtonHTMLAttributes } from "react";
import { useClientEnvironment } from "~/hooks/useClientEnvironment";

interface WorkbenchMenuButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  type?: "button" | "submit" | "reset";
}

/** Only the Web shell owns the global workbench drawer. Local navigation stays separate. */
export function WorkbenchMenuButton(props: WorkbenchMenuButtonProps) {
  const { channel } = useClientEnvironment();
  return channel === "web" ? <button type="button" {...props} /> : null;
}
