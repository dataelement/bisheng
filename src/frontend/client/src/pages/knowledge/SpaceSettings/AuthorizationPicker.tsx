import { useEffect, useState } from "react";
import type { SelectedSubject, SubjectType } from "~/api/permission";
import { SubjectSearchDepartment } from "~/components/permission/SubjectSearchDepartment";
import { SubjectSearchUser } from "~/components/permission/SubjectSearchUser";
import { SubjectSearchUserGroup } from "~/components/permission/SubjectSearchUserGroup";
import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "~/components/ui/Dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";
import { useLocalize } from "~/hooks";

export interface AuthorizationPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "edit";
  spaceId?: string;
  disabledIds: Record<SubjectType, number[]>;
  canAddNonUserSubjects: boolean;
  onConfirm: (subjects: SelectedSubject[]) => void;
}

export function AuthorizationPicker({
  open,
  onOpenChange,
  mode,
  spaceId,
  disabledIds,
  canAddNonUserSubjects,
  onConfirm,
}: AuthorizationPickerProps) {
  const localize = useLocalize();
  const [subjectType, setSubjectType] = useState<SubjectType>("user");
  const [subjects, setSubjects] = useState<SelectedSubject[]>([]);
  const [includeChildren, setIncludeChildren] = useState(true);

  useEffect(() => {
    if (!open) {
      setSubjects([]);
      setSubjectType("user");
      setIncludeChildren(true);
    }
  }, [open]);

  const currentSubjects = subjects.filter(
    (subject) => subject.type === subjectType,
  );
  const handleSubjectChange = (next: SelectedSubject[]) => {
    setSubjects((current) => [
      ...current.filter((subject) => subject.type !== subjectType),
      ...next,
    ]);
  };
  const handleIncludeChildrenChange = (checked: boolean) => {
    setIncludeChildren(checked);
    setSubjects((current) =>
      current.map((subject) =>
        subject.type === "department"
          ? { ...subject, include_children: checked }
          : subject,
      ),
    );
  };
  const searchProps = {
    mode: mode === "create" ? ("create" as const) : ("resource" as const),
    resourceType: "knowledge_space" as const,
    resourceId: spaceId,
    value: currentSubjects,
    onChange: handleSubjectChange,
    disabledIds: disabledIds[subjectType],
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(680px,80vh)] max-w-[720px] flex-col overflow-hidden bg-surface-primary">
        <DialogHeader>
          <DialogTitle>
            {localize("com_unified_permission.add_authorization")}
          </DialogTitle>
        </DialogHeader>
        <Tabs
          value={subjectType}
          onValueChange={(value) => setSubjectType(value as SubjectType)}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex items-center justify-between gap-3">
            <TabsList>
              <TabsTrigger value="user">
                {localize("com_permission.subject_user")}
              </TabsTrigger>
              <TabsTrigger value="department" disabled={!canAddNonUserSubjects}>
                {localize("com_permission.subject_department")}
              </TabsTrigger>
              <TabsTrigger value="user_group" disabled={!canAddNonUserSubjects}>
                {localize("com_permission.subject_user_group")}
              </TabsTrigger>
            </TabsList>
            {subjectType === "department" && (
              <label className="flex items-center gap-2 text-body text-text-2">
                <Checkbox
                  checked={includeChildren}
                  onCheckedChange={(checked) =>
                    handleIncludeChildrenChange(checked === true)
                  }
                />
                {localize("com_permission.include_children")}
              </label>
            )}
          </div>
          <TabsContent value="user" className="mt-4 min-h-0 flex-1">
            <SubjectSearchUser {...searchProps} />
          </TabsContent>
          <TabsContent value="department" className="mt-4 min-h-0 flex-1">
            <SubjectSearchDepartment
              {...searchProps}
              includeChildren={includeChildren}
            />
          </TabsContent>
          <TabsContent value="user_group" className="mt-4 min-h-0 flex-1">
            <SubjectSearchUserGroup {...searchProps} />
          </TabsContent>
        </Tabs>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            {localize("com_unified_permission.cancel")}
          </Button>
          <Button
            disabled={subjects.length === 0}
            onClick={() => {
              onConfirm(subjects);
              onOpenChange(false);
            }}
          >
            {localize("com_unified_permission.add_authorization")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
