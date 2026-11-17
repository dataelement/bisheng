import { addMetadata, deleteMetadataFields, updateMetadataFields } from "@/controllers/API";
import { Button, Input, Modal } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { Hash } from "lucide-react";
import { Fragment, useEffect, useId, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { KnowledgeHint, KnowledgeTooltip } from "./KnowledgeTooltip";

type MetadataType = "String" | "Number" | "Time"

interface Metadata {
    id: string
    name: string
    type: MetadataType
    createdAt: Date
    updatedAt: Date
}

interface BuiltInMetadata {
    name: string
    type: MetadataType

}

const BUILT_IN_METADATA: BuiltInMetadata[] = [
    { name: "document_id", type: "Number" },
    { name: "document_name", type: "String" },
    { name: "upload_time", type: "Time" },
    { name: "update_time", type: "Time" },
    { name: "uploader", type: "String" },
    { name: "updater", type: "String" },
    { name: "abstract", type: "String" },
    { name: "chunk_index", type: "Number" },
    { name: "bbox", type: "String" },
    { name: "page", type: "Number" },
    { name: "knowledge_id", type: "Number" },
    { name: "user_metadata", type: "String" },
]

const TYPE_ICONS = {
    String: <Outlined.FontSize />,
    Number: <Hash />,
    Time: <Outlined.Time />,
}

type MetadataView =
    | { kind: "list" }
    | { kind: "create" }
    | { kind: "rename"; field: Metadata }
    | { kind: "delete"; field: Metadata };

interface MetadataManagementDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSave?: (metadata: Metadata[]) => void;
    hasManagePermission?: boolean;
    id: string;
    placeholder?: ReactNode;
    children?: ReactNode;
    mutations?: {
        add: (name: string, type: string) => Promise<void>;
        rename: (name: string, next: string) => Promise<void>;
        remove: (name: string) => Promise<void>;
    };
    initialMetadata?: Array<{ field_name: string; field_type: string; updated_at?: number }>;
}

export function MetadataManagementDialog({
    open,
    onOpenChange,
    onSave,
    hasManagePermission = true,
    id,
    initialMetadata,
    mutations,
    placeholder,
    children,
}: MetadataManagementDialogProps) {
    const { t } = useTranslation("knowledge");
    const [metadataList, setMetadataList] = useState<Metadata[]>([]);
    const [view, setView] = useState<MetadataView>({ kind: "list" });
    const [discarding, setDiscarding] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [newName, setNewName] = useState("");
    const [newType, setNewType] = useState<MetadataType>("String");
    const [error, setError] = useState("");
    const fieldNameId = useId();
    const returnFocusTo = useRef<HTMLButtonElement | null>(null);
    const createButton = useRef<HTMLButtonElement | null>(null);

    useEffect(() => {
        if (!open) return;
        setMetadataList((initialMetadata ?? []).map((item) => ({
            id: `meta_${item.field_name}`,
            name: item.field_name,
            type: (item.field_type.charAt(0).toUpperCase() + item.field_type.slice(1)) as MetadataType,
            createdAt: new Date(),
            updatedAt: item.updated_at ? new Date(item.updated_at * 1000) : new Date(),
        })));
    }, [open, initialMetadata]);

    useEffect(() => {
        if (view.kind !== "list" || !returnFocusTo.current) return;
        const target = returnFocusTo.current.isConnected ? returnFocusTo.current : createButton.current;
        target?.focus({ preventScroll: true });
        returnFocusTo.current = null;
    }, [view.kind]);

    const showAction = (event: MouseEvent<HTMLButtonElement>, nextView: MetadataView) => {
        returnFocusTo.current = event.currentTarget;
        setNewName(nextView.kind === "rename" ? nextView.field.name : "");
        setNewType("String");
        setError("");
        setView(nextView);
    };

    const returnToList = () => {
        setDiscarding(false);
        setError("");
        setView({ kind: "list" });
    };

    const validateName = (name: string) => {
        if (BUILT_IN_METADATA.some((field) => field.name === name)) return t("builtInNameError");
        if (!name.trim()) return t("nameRequired");
        if (name.length > 255) return t("nameTooLong");
        if (!/^[a-z][a-z0-9_]*$/.test(name)) return t("nameFormatError");
        const currentId = view.kind === "rename" ? view.field.id : undefined;
        if (metadataList.some((field) => field.name === name && field.id !== currentId)) {
            return t("nameExists");
        }
        return "";
    };

    const handleSave = async () => {
        if (isLoading || !hasManagePermission || view.kind === "list") return;
        if (!id) {
            setError(t("knowledgeIdMissing"));
            return;
        }
        if (view.kind !== "delete") {
            const validationError = validateName(newName);
            if (validationError) {
                setError(validationError);
                return;
            }
        }
        if (view.kind === "rename" && view.field.name === newName) {
            returnToList();
            return;
        }

        setIsLoading(true);
        setError("");
        try {
            if (view.kind === "create") {
                const type = newType.toLowerCase();
                if (mutations) {
                    await mutations.add(newName, type);
                } else {
                    await addMetadata(id, [{ field_name: newName, field_type: type }]);
                    const createdAt = new Date();
                    setMetadataList((previous) => [
                        { id: `meta_${newName}`, name: newName, type: newType, createdAt, updatedAt: createdAt },
                        ...previous,
                    ]);
                }
            } else if (view.kind === "rename") {
                if (mutations) {
                    await mutations.rename(view.field.name, newName);
                } else {
                    await updateMetadataFields(id, [{ old_field_name: view.field.name, new_field_name: newName }]);
                    setMetadataList((previous) => previous.map((field) =>
                        field.id === view.field.id ? { ...field, name: newName, updatedAt: new Date() } : field,
                    ));
                }
            } else if (view.kind === "delete") {
                if (mutations) {
                    await mutations.remove(view.field.name);
                } else {
                    await deleteMetadataFields(id, [view.field.name]);
                    setMetadataList((previous) => previous.filter((field) => field.id !== view.field.id));
                }
            }
            returnToList();
            onSave?.(metadataList);
        } catch (err) {
            const failureMessage = {
                create: "createFailed",
                rename: "renameFailed",
                delete: "deleteFailed",
            }[view.kind];
            setError(err instanceof Error && err.message ? err.message : t(failureMessage));
        } finally {
            setIsLoading(false);
        }
    };

    const creating = view.kind === "create";
    const editing = creating || view.kind === "rename";
    const deleting = view.kind === "delete";
    const draftChanged = creating
        ? newName !== "" || newType !== "String"
        : view.kind === "rename" && newName !== view.field.name;
    const handleBeforeClose = () => {
        if (view.kind === "list") return true;
        if (discarding) setDiscarding(false);
        else if (editing && draftChanged) setDiscarding(true);
        else {
            returnToList();
            return creating;
        }
        return false;
    };

    const sortedMetadata = [...metadataList].sort((a, b) => a.updatedAt.getTime() - b.updatedAt.getTime());
    const errorMessage = error && <p role="alert" className="text-body-sm text-danger">{error}</p>;
    const discardMessage = t("flow.unsavedChangesConfirmation", { ns: "bs" });
    const editor = discarding ? (
        <div className="space-y-4">
            <p>{discardMessage}</p>
            <div className="flex justify-end gap-3">
                <Button type="button" variant="outlined" color="default" autoFocus onClick={() => setDiscarding(false)}>
                    {t("cancel")}
                </Button>
                <Button
                    type="button"
                    color="primary"
                    onClick={() => {
                        returnToList();
                        if (creating) onOpenChange(false);
                    }}
                >
                    {t("confirm")}
                </Button>
            </div>
        </div>
    ) : (
        <form
            aria-label={t(creating ? "createMetadata" : "rename")}
            className="space-y-4"
            onSubmit={(event) => { event.preventDefault(); void handleSave(); }}
        >
            {creating && (
                <div className="space-y-2">
                    <span className="block font-medium">{t("type")}</span>
                    <div className="flex gap-2" role="group" aria-label={t("type")}>
                        {(["String", "Number", "Time"] as const).map((type) => (
                            <Button
                                key={type}
                                type="button"
                                className="min-w-0 flex-1"
                                variant={newType === type ? "solid" : "outlined"}
                                color={newType === type ? "primary" : "default"}
                                aria-pressed={newType === type}
                                disabled={isLoading}
                                onClick={() => setNewType(type)}
                            >
                                {type}
                            </Button>
                        ))}
                    </div>
                </div>
            )}
            <div className="space-y-2">
                <label className="block font-medium" htmlFor={fieldNameId}>
                    {t("metadatainfor.name")}
                </label>
                <Input
                    id={fieldNameId}
                    value={newName}
                    onChange={(event) => { setNewName(event.target.value); setError(""); }}
                    placeholder={t("pleaseEnter")}
                    autoComplete="off"
                    autoFocus
                    disabled={isLoading}
                    status={error ? "error" : undefined}
                />
                {errorMessage}
            </div>
            <div className="flex justify-end gap-3">
                <Button type="button" variant="outlined" color="default" disabled={isLoading} onClick={returnToList}>
                    {t("cancel")}
                </Button>
                <Button type="submit" color="primary" loading={isLoading} disabled={!hasManagePermission}>
                    {t("save")}
                </Button>
            </div>
        </form>
    );

    return (
        <Modal
            open={open}
            onOpenChange={onOpenChange}
            size={deleting ? "small" : "medium"}
            title={t(deleting ? "delete" : "metaData")}
            description={deleting ? t("confirmDeleteMetadata") : undefined}
            closeLabel={t("close", { ns: "bs" })}
            closable={!discarding && !deleting}
            submitting={isLoading}
            beforeClose={handleBeforeClose}
            footer={deleting && (
                <>
                    <Button
                        type="button"
                        variant="outlined"
                        color="default"
                        disabled={isLoading}
                        onClick={returnToList}
                        autoFocus
                    >
                        {t("cancel")}
                    </Button>
                    <Button
                        type="button"
                        loading={isLoading}
                        color="danger"
                        onClick={() => { void handleSave(); }}
                    >
                        {t("confirm")}
                    </Button>
                </>
            )}
        >
            <div hidden={deleting} className="space-y-6 pb-4">
                {children}
                {placeholder ?? (
                    <div className="space-y-6">
                        <div hidden={creating}>
                            <Button
                                ref={createButton}
                                type="button"
                                variant="filled"
                                color="default"
                                className="w-full"
                                disabled={!hasManagePermission || isLoading || editing}
                                onClick={(event) => showAction(event, { kind: "create" })}
                            >
                                <Outlined.Plus aria-hidden />
                                {t("createMetadata")}
                            </Button>
                        </div>
                        {creating && editor}
                        {sortedMetadata.length > 0 && (
                            <div className="space-y-2">
                                {sortedMetadata.map((field) => (
                                    <Fragment key={field.id}>
                                        <div className="flex min-w-0 items-center gap-3 rounded-lg bg-fill-1 p-3">
                                            <span className="shrink-0 text-lg">{TYPE_ICONS[field.type]}</span>
                                            <span className="shrink-0 text-text-3">{field.type}</span>
                                            <div className="min-w-0 flex-1 font-medium">
                                                <KnowledgeTooltip content={field.name}>
                                                    <span className="block truncate">{field.name}</span>
                                                </KnowledgeTooltip>
                                            </div>
                                            <Button
                                                type="button"
                                                variant="text"
                                                size="small"
                                                color="default"
                                                iconOnly
                                                aria-label={t("rename")}
                                                disabled={!hasManagePermission || isLoading || editing}
                                                onClick={(event) => showAction(event, { kind: "rename", field })}
                                            >
                                                <Outlined.Edit aria-hidden />
                                            </Button>
                                            <Button
                                                type="button"
                                                variant="text"
                                                size="small"
                                                color="default"
                                                iconOnly
                                                aria-label={t("delete")}
                                                disabled={!hasManagePermission || isLoading || editing}
                                                onClick={(event) => showAction(event, { kind: "delete", field })}
                                            >
                                                <Outlined.Delete aria-hidden />
                                            </Button>
                                        </div>
                                        {view.kind === "rename" && view.field.id === field.id && editor}
                                    </Fragment>
                                ))}
                            </div>
                        )}
                        <div className="space-y-3">
                            <div className="flex items-center gap-2">
                                <h3 className="font-medium">{t("builtInMetadata")}</h3>
                                <KnowledgeHint content={t("builtInMetadataTooltip")} />
                            </div>
                            <div className="space-y-2">
                                {BUILT_IN_METADATA.slice(0, 6).map((field) => (
                                    <div key={field.name} className="flex min-w-0 items-center gap-3 rounded-lg bg-fill-1 p-3">
                                        <span className="shrink-0 text-lg">{TYPE_ICONS[field.type]}</span>
                                        <span className="shrink-0 text-text-3">{field.type}</span>
                                        <span className="min-w-0 truncate font-medium">{field.name}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
            </div>
            {deleting && errorMessage}
        </Modal>
    );
}
