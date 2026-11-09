import type { ReactNode } from 'react';

const BANNER_ARTWORK = {
  apps: '/assets/channel/apptab-icons.svg',
  channel: '/assets/channel/bgchannel-icons.svg',
  knowledge: '/assets/tabbg-icons.svg',
} as const;

// The app symbols match these slot viewBoxes to retain their original scale.
const ARTWORK_SLOTS = [
  { id: 'left-outer', x: 393, y: 60, width: 25, height: 25 },
  { id: 'left-top', x: 443, y: 23, width: 26, height: 26 },
  { id: 'left-bottom', x: 473, y: 73, width: 22, height: 22 },
  { id: 'right-top', x: 865, y: 24, width: 25, height: 25 },
  { id: 'right-bottom', x: 893, y: 69, width: 27, height: 27 },
  { id: 'right-outer', x: 942, y: 43, width: 31, height: 25 },
] as const;

interface SquareBannerProps {
  title: string;
  description: string;
  artwork?: keyof typeof BANNER_ARTWORK;
  children?: ReactNode;
}

export function SquareBanner({ title, description, artwork = 'apps', children }: SquareBannerProps) {
  const artworkUrl = `${__APP_ENV__.BASE_URL || ''}${BANNER_ARTWORK[artwork]}`;

  return (
    <div className="relative w-full shrink-0 overflow-hidden border-b border-[#F0F1F5] bg-blue-500/[0.05]">
      <svg
        aria-hidden
        className="pointer-events-none absolute inset-0 size-full text-blue-200"
        viewBox="0 0 1368 122"
        preserveAspectRatio="xMidYMid slice"
      >
        {ARTWORK_SLOTS.map(({ id, ...bounds }) => (
          <use key={id} href={`${artworkUrl}#${id}`} {...bounds} />
        ))}
      </svg>
      {children}
      <div className="relative mx-auto flex w-full max-w-[1000px] flex-col items-center justify-center px-5 pb-5 pt-7 text-center">
        <h1 className="mb-1 text-[26px] font-semibold text-blue-500">{title}</h1>
        <p className="mb-3 max-w-[640px] text-[13px] leading-[22px] text-text-3">{description}</p>
      </div>
    </div>
  );
}
