import type { SubjectType } from "~/api/permission";
import { useLocalize } from "~/hooks";

interface SubjectIdentityProps {
  type: SubjectType;
  externalId?: string | null;
  path?: string | null;
}

export function SubjectIdentity({ type, externalId, path }: SubjectIdentityProps) {
  const localize = useLocalize();
  if (!externalId && !path) return null;
  return (
    <span className="min-w-0 select-text text-caption text-text-3" onClick={(event) => event.stopPropagation()} onDoubleClick={(event) => event.stopPropagation()}>
      {externalId && <span title={externalId} className="break-all">{localize(`com_permission.${type}_id`)}: {externalId}</span>}
      {path && <span title={path} className="block break-all">{localize("com_permission.department_path")}: {path}</span>}
    </span>
  );
}
