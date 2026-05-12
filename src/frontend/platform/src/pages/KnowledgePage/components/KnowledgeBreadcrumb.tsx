import { ChevronRight } from "lucide-react";

export interface BreadcrumbItem {
    id: number;
    name: string;
}

export interface KnowledgeBreadcrumbProps {
    spaceName: string;
    path: BreadcrumbItem[];
    onNavigate: (id: number | null, index: number) => void;
}

/**
 * Breadcrumb navigation bar for the knowledge space tree layout.
 * Clicking the space name fires onNavigate(null, -1).
 * Clicking a path segment fires onNavigate(item.id, segmentIndex).
 */
export function KnowledgeBreadcrumb({
    spaceName,
    path,
    onNavigate,
}: KnowledgeBreadcrumbProps) {
    return (
        <nav className="flex items-center text-sm text-gray-600 gap-1">
            <button
                className="hover:text-gray-900"
                onClick={() => onNavigate(null, -1)}
            >
                {spaceName}
            </button>
            {path.map((item, i) => (
                <span key={item.id} className="flex items-center gap-1">
                    <ChevronRight className="w-3 h-3 text-gray-400" />
                    <button
                        className={
                            i === path.length - 1
                                ? "text-gray-900 font-medium"
                                : "hover:text-gray-900"
                        }
                        onClick={() => onNavigate(item.id, i)}
                    >
                        {item.name}
                    </button>
                </span>
            ))}
        </nav>
    );
}
