import { useMemo } from 'react';
import { useLocalize, usePrefersMobileLayout } from '~/hooks';

// Compliance notice shown on every client page.
// - PC (>=768px): a faint, floating top banner (does not occupy layout space).
// - Mobile (<768px): a tiled diagonal watermark instead, so it never covers the
//   page title or the chat input the way a top/bottom bar would.
export default function TestEnvNotice() {
  const localize = useLocalize();
  const isMobile = usePrefersMobileLayout();
  const text = '' // localize('com_test_env_banner');

  const watermarkBackground = useMemo(() => {
    // Escape characters that are not valid inside SVG/XML text nodes.
    const safe = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    // One tile holds a single rotated instance; CSS repeat builds the field.
    // Mid-gray keeps it faintly visible on both light and dark themes.
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="360" height="200">`
      + `<text x="180" y="100" text-anchor="middle" dominant-baseline="middle"`
      + ` transform="rotate(-24 180 100)" fill="rgba(125,125,125,0.13)"`
      + ` font-size="15" font-family="-apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif">`
      + `${safe}</text></svg>`;
    return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  }, [text]);

  if (isMobile) {
    return (
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[9999]"
        style={{ backgroundImage: watermarkBackground, backgroundRepeat: 'repeat' }}
      />
    );
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 top-0 z-[2000] flex justify-center">
      <div className="mt-1 rounded-md bg-amber-500/30 px-3 py-1 text-center text-xs font-medium text-amber-900 backdrop-blur-sm dark:text-amber-100">
        {text}
      </div>
    </div>
  );
}
