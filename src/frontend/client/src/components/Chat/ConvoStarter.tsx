interface ConvoStarterProps {
  text: string;
  onClick: () => void;
}

export default function ConvoStarter({ text, onClick }: ConvoStarterProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative flex w-40 max-[575px]:w-[calc(33.333%-6px)] max-[575px]:min-w-0 max-[575px]:shrink max-[575px]:grow max-[575px]:basis-0 cursor-pointer flex-col gap-1 max-[575px]:gap-1 rounded-2xl max-[575px]:rounded-xl border border-border-medium max-[575px]:border-[#e5e6eb] px-3 max-[575px]:px-2 pb-4 max-[575px]:pb-2 pt-3 max-[575px]:pt-2 text-start align-top text-[15px] max-[575px]:text-[11px] leading-snug shadow-[0_0_2px_0_rgba(0,0,0,0.05),0_4px_6px_0_rgba(0,0,0,0.02)] max-[575px]:shadow-sm bg-white transition-colors duration-300 ease-in-out fade-in hover:bg-surface-tertiary max-[575px]:hover:bg-[#f7f8fa]"
    >
      <p className="break-word line-clamp-3 overflow-hidden text-balance break-all text-text-secondary max-[575px]:text-[#4e5969]">
        {text}
      </p>
    </button>
  );
}
