import type { PortalScopeFileCount as PortalScopeFileCountModel } from "../scopeFileCount";
import { portalScopeFileCountLabel } from "../scopeFileCount";
import s from "../PortalKnowledgeWorkbench.module.css";

interface PortalScopeFileCountProps {
    scope: PortalScopeFileCountModel;
    count: number | null;
}

export function PortalScopeFileCount({ scope, count }: PortalScopeFileCountProps) {
    const label = portalScopeFileCountLabel(scope.kind, count);
    return (
        <div
            className={s.scopeFileCount}
            data-testid="portal-scope-file-count"
            role="status"
            aria-live="polite"
            title={scope.name}
        >
            {label}
        </div>
    );
}
