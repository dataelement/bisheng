import { X } from "lucide-react";

export default function RemoveFile({ onRemove }: { onRemove: () => void }) {
  return (
    <button
      type="button"
      className="absolute right-2 top-2 -translate-y-1/2 translate-x-1/2 rounded-full bg-gray-600/40 p-0.5 transition-colors duration-200 hover:bg-gray-300 z-50 text-white"
      onClick={onRemove}
    >
      <span>
        <X size={12}/>
      </span>
    </button>
  );
}
