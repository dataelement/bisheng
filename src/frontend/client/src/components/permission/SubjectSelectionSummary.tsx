import type { SelectedSubject } from "~/api/permission";
import { SubjectIdentity } from "./SubjectIdentity";
import { PermissionSubjectAvatar } from "./PermissionSubjectAvatar";

interface SubjectSelectionSummaryProps {
  subjects: SelectedSubject[];
}

export function SubjectSelectionSummary({ subjects }: SubjectSelectionSummaryProps) {
  if (subjects.length === 0) return null;
  return (
    <div className="scrollbar-os flex max-h-24 flex-wrap gap-2 overflow-y-auto py-2 text-body-sm text-text-1">
      {subjects.map((subject) => (
        <span key={`${subject.type}:${subject.id}`} className="inline-flex flex-wrap items-center gap-1.5">
          <PermissionSubjectAvatar
            type={subject.type}
            subjectId={subject.id}
            name={subject.name}
            avatar={subject.avatar}
            className="size-5"
            fallbackClassName="text-caption-sm"
          />
          <span className="select-text" title={subject.name}>{subject.name}</span>
          <SubjectIdentity type={subject.type} externalId={subject.externalId} path={subject.departmentPath} />
        </span>
      ))}
    </div>
  );
}
