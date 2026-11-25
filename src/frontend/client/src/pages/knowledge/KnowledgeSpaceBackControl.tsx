import { Outlined } from "bisheng-icons";

interface KnowledgeSpaceBackControlProps {
  label: string;
  onClick: () => void;
}

export function KnowledgeSpaceBackControl({ label, onClick }: KnowledgeSpaceBackControlProps) {
  return (
    <>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-md p-2 text-text-2 transition-colors hover:bg-fill-1"
      >
        <Outlined.ArrowLeft className="size-4" />
      </button>
      <span className="mx-1 h-4 w-px shrink-0 bg-border-base" aria-hidden />
    </>
  );
}
