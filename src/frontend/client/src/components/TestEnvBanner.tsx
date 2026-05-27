import { useLocalize } from '~/hooks';

// Floating, non-intrusive test-environment notice overlaid at the top of every client page.
// pointer-events-none keeps it from blocking interaction with the underlying page.
export default function TestEnvBanner() {
  const localize = useLocalize();

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[2000] flex justify-center">
      <div className="mt-1 rounded-md bg-amber-500/30 px-3 py-1 text-center text-xs font-medium text-amber-900 backdrop-blur-sm dark:text-amber-100">
        {localize('com_test_env_banner')}
      </div>
    </div>
  );
}
