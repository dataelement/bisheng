interface ConvoStarterProps {
  text: string;
  onClick: () => void;
}

export default function ConvoStarter({ text, onClick }: ConvoStarterProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative flex w-40 touch-mobile:w-[calc(33.333%-6px)] touch-mobile:min-w-0 touch-mobile:shrink touch-mobile:grow touch-mobile:basis-0 cursor-pointer flex-col gap-1 touch-mobile:gap-1 rounded-2xl touch-mobile:rounded-xl border border-border-medium touch-mobile:border-[#e5e6eb] px-3 touch-mobile:px-2 pb-4 touch-mobile:pb-2 pt-3 touch-mobile:pt-2 text-start align-top text-[15px] touch-mobile:text-[11px] leading-snug shadow-[0_0_2px_0_rgba(0,0,0,0.05),0_4px_6px_0_rgba(0,0,0,0.02)] touch-mobile:shadow-sm bg-white transition-colors duration-300 ease-in-out fade-in hover:bg-surface-tertiary touch-mobile:hover:bg-[#f7f8fa]"
    >
      <p className="break-word line-clamp-3 overflow-hidden text-balance break-all text-text-secondary touch-mobile:text-[#4e5969]">
        {text}
      </p>
    </button>
  );
}
