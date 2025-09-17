import { X } from "lucide-react";

export default function RemoveFile({ onRemove }: { onRemove: () => void }) {
  return (
    <button
      type="button"
      className="absolute p-0.5 right-1.5 top-1.5 bg-black text-white rounded-full transition-colors duration-200 hover:bg-gray-300 z-50"
      onClick={onRemove}
    >
      <span>
        <X size={12} />
      </span>
    </button>
  );
}
