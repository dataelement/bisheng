import { useLocalize } from '~/hooks';

const MASK = `url(${__APP_ENV__.BASE_URL || ''}/assets/channel/apptab-icons.svg)`;

/** 技能广场 banner — same brand-tinted art as the 应用 / 知识 / 频道 squares. */
export function SkillSquareBanner() {
  const localize = useLocalize();
  return (
    <div className="relative w-full shrink-0 overflow-hidden border-b border-[#F0F1F5] bg-blue-500/[0.05]">
      {/* Decorative scattered icons, recolored through a mask so they follow the brand theme. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-blue-200"
        style={{
          WebkitMaskImage: MASK,
          maskImage: MASK,
          WebkitMaskSize: 'cover',
          maskSize: 'cover',
          WebkitMaskPosition: 'center',
          maskPosition: 'center',
          WebkitMaskRepeat: 'no-repeat',
          maskRepeat: 'no-repeat',
        }}
      />
      <div className="relative mx-auto flex w-full max-w-[1000px] flex-col items-center justify-center px-5 pb-5 pt-7 text-center">
        <h1 className="mb-1 text-[26px] font-semibold text-blue-500">{localize('com_skill_center_square_title')}</h1>
        <p className="mb-3 max-w-[640px] text-[13px] leading-[22px] text-text-3">{localize('com_skill_center_square_description')}</p>
      </div>
    </div>
  );
}
