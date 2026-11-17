import { useLayoutEffect, useState } from 'react';
import { getLogicalViewport, getRectScale, getRectViewport } from '~/utils/fontSize';

function readBounds() {
  const viewport = window.visualViewport;
  const width = viewport?.width ?? document.documentElement.clientWidth;
  const height = viewport?.height ?? document.documentElement.clientHeight;
  const rectViewport = getRectViewport();
  const inset = 8 * getRectScale();

  return {
    // Use CSS pixels directly: older embedded engines may not support dvh.
    maxHeight: Math.max(0, Math.min(440, getLogicalViewport().height - 48)),
    collisionPadding: {
      top: inset,
      left: inset,
      // Floating UI's viewport uses physical pixels, while older WeCom rects
      // use layout pixels. Correct the far edges, retaining its horizontal flip.
      right: width - rectViewport.width + inset,
      bottom: height - rectViewport.height + inset,
    },
  };
}

/** Keep list flyouts inside the window in every supported font-size level. */
export function useScaledMenuBounds() {
  const [bounds, setBounds] = useState(readBounds);

  useLayoutEffect(() => {
    const update = () => setBounds(readBounds());
    update();
    window.addEventListener('resize', update);
    window.visualViewport?.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
      window.visualViewport?.removeEventListener('resize', update);
    };
  }, []);

  return bounds;
}
