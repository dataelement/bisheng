import { useMemo } from 'react';
import { useLocalize, usePrefersMobileLayout } from '~/hooks';

// Compliance notice shown on client pages.
// - PC (>=768px): none (the top banner was removed).
// - Mobile (<768px): a tiled diagonal watermark, so it never covers the page title
//   or the chat input the way a top/bottom bar would.
export default function TestEnvNotice() {
  const localize = useLocalize();
  const isMobile = usePrefersMobileLayout();
  const text = localize('com_test_env_banner');

  const watermark = useMemo(() => {
    // Escape characters that are not valid inside SVG/XML text nodes.
    const safe = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const fontSize = 15;
    const angleDeg = 24; // tilt up-to-the-right (original direction, unchanged)
    // Estimate the unrotated sentence width so the tile can fit the WHOLE sentence —
    // full-width CJK/kana glyphs ≈ fontSize wide, others ≈ 0.55× (latin/space).
    let textWidth = 0;
    for (const ch of text) {
      // CJK radicals/ideographs/kana (U+2E80–U+9FFF) + full-width forms (U+FF00–U+FFEF).
      textWidth += /[⺀-鿿＀-￯]/.test(ch) ? fontSize : fontSize * 0.55;
    }
    const rad = (angleDeg * Math.PI) / 180;
    const textHeight = fontSize * 1.4;
    // Tile = rotated bounding box of one full sentence + small margin. tileH sets the
    // vertical gap between repeats; the tile is rendered as a single centered column
    // (see below), so each sentence stays whole (no wrap/clip).
    const tileW = Math.ceil(textWidth * Math.cos(rad) + textHeight * Math.sin(rad)) + 70;
    const tileH = Math.ceil(textWidth * Math.sin(rad) + textHeight * Math.cos(rad)) + 64;
    const cx = Math.round(tileW / 2);
    const cy = Math.round(tileH / 2);
    // Mid-gray keeps it faintly visible on both light and dark themes.
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${tileW}" height="${tileH}">`
      + `<text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="middle"`
      + ` transform="rotate(-${angleDeg} ${cx} ${cy})" fill="rgba(125,125,125,0.13)"`
      + ` font-size="${fontSize}" font-family="-apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif">`
      + `${safe}</text></svg>`;
    return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
  }, [text]);

  if (isMobile) {
    return (
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 z-[9999]"
        style={{
          // Single centered column, repeating vertically only — no left/right columns.
          // The vertical offset nudges the whole column down a bit from the very top.
          backgroundImage: watermark,
          backgroundRepeat: 'repeat-y',
          backgroundPosition: 'center 20px',
        }}
      />
    );
  }

  // PC (>=768px): banner removed — no compliance notice on desktop.
  return null;
}
