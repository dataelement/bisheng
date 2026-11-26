import { useLayoutEffect, useState } from 'react';
import { getDisplayScale, getRectScale } from '~/utils/fontSize';

function readBounds() {
  const viewport = window.visualViewport;
  const width = viewport?.width ?? document.documentElement.clientWidth;
  const height = viewport?.height ?? document.documentElement.clientHeight;
  const rectScale = getRectScale();
  const displayScale = getDisplayScale();
  const correction = 1 - rectScale / displayScale;
  const left = viewport?.offsetLeft ?? 0;
  const top = viewport?.offsetTop ?? 0;
  const inset = 8 * rectScale;
  const logicalHeight = height / displayScale;

  return {
    // Use CSS pixels directly: older embedded engines may not support dvh.
    maxHeight: Math.max(0, Math.min(440, logicalHeight - 48)),
    // A menu capped to the current side's remaining space can shrink before
    // Radix flips it. Keep room for the larger side instead.
    actionMenuMaxHeight: Math.max(0, logicalHeight / 2 - 32),
    collisionPadding: {
      // Keep the visible viewport and the anchor in the same coordinate space.
      top: inset - top * correction,
      left: inset - left * correction,
      right: inset + (left + width) * correction,
      bottom: inset + (top + height) * correction,
    },
    isScaled: displayScale !== 1,
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
    window.visualViewport?.addEventListener('scroll', update);
    return () => {
      window.removeEventListener('resize', update);
      window.visualViewport?.removeEventListener('resize', update);
      window.visualViewport?.removeEventListener('scroll', update);
    };
  }, []);

  return bounds;
}
