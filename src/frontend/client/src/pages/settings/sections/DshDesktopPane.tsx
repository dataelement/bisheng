import { DshDesktopPanel } from "~/components/dsh/DshDesktopPanel";
import { useDshDesktop } from "~/hooks/useDshDesktop";

/**
 * The DSH desktop entry. It used to hang off the account pop menu, which this
 * line replaced with the settings page, so it lives here as its own section.
 * The nav item only appears when the deployment reports DSH management on, so
 * reaching this pane with DSH off means a stale link: render nothing rather
 * than an entry that cannot launch.
 */
export function DshDesktopPane() {
  const { enabled, downloadUrl, launchUrl } = useDshDesktop();
  if (!enabled) {
    return null;
  }
  return (
    <div className="flex flex-col gap-4">
      <DshDesktopPanel active downloadUrl={downloadUrl} launchUrl={launchUrl} />
    </div>
  );
}
