import { Tabs, TabsContent } from "@/components/bs-ui/tabs";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { checkPermission } from "@/controllers/API/permission";
import axios from "@/controllers/request";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import Files from "./components/Files";
import Header from "./components/Header";
import { KnowledgeBreadcrumb } from "./components/KnowledgeBreadcrumb";
import { KnowledgeTree } from "./components/KnowledgeTree";
import Paragraphs from "./components/Paragraphs";
import { useKnowledgeStore } from "./useKnowledgeStore";

/**
 * Reads the knowledge_space.tree_structured_directory_display flag from
 * GET /api/v1/config. Defaults to true (optimistic) if the field is absent
 * or the request fails.
 */
function useTreeLayoutFlag(): boolean {
    const [enabled, setEnabled] = useState<boolean>(true);
    useEffect(() => {
        axios
            .get("/api/v1/config")
            .then((data: any) => {
                const flag = data?.knowledge_space?.tree_structured_directory_display;
                // Treat undefined / missing key as enabled (our default)
                setEnabled(flag !== false);
            })
            .catch(() => setEnabled(true));
    }, []);
    return enabled;
}

/** Legacy tab layout — preserved exactly as it was before this refactor. */
function LegacyTabLayout({
    knowledgeId,
    canEditKb,
    canDeleteKb,
}: {
    knowledgeId: string;
    canEditKb: boolean;
    canDeleteKb: boolean;
}) {
    const [value, setValue] = useState("file");
    const [fileId, setFileId] = useState("");
    const [fileTitle, setFileTitle] = useState(true);

    const onPreview = (id: string) => {
        setFileId(id);
        setValue("chunk");
        setFileTitle(false);
    };
    const handleBackFromChunk = () => {
        if (value === "chunk") {
            setValue("file");
            setFileId("");
            setFileTitle(true);
        }
    };

    return (
        <Tabs
            value={value}
            onValueChange={(v) => {
                setValue(v);
                setFileId("");
                if (v === "file") {
                    setFileTitle(true);
                } else {
                    setFileTitle(false);
                }
            }}
        >
            <TabsContent value="file" className="mt-0">
                <div className="flex justify-between w-1/2 pt-4">
                    <Header fileTitle={fileTitle} showBackButton={true} />
                </div>
                <Files
                    onPreview={onPreview}
                    canEditKb={canEditKb}
                    canDeleteKb={canDeleteKb}
                />
            </TabsContent>
            <TabsContent value="chunk" className="mt-0">
                <Paragraphs
                    fileId={fileId}
                    onBack={handleBackFromChunk}
                    canEditKb={canEditKb}
                    canDeleteKb={canDeleteKb}
                />
            </TabsContent>
        </Tabs>
    );
}

export default function FilesPage() {
    const [permissionChecked, setPermissionChecked] = useState(false);
    const [canEditKb, setCanEditKb] = useState(false);
    const [canDeleteKb, setCanDeleteKb] = useState(false);
    const { id: knowledgeId } = useParams();
    const navigate = useNavigate();
    const { message } = useToast();
    const { t } = useTranslation("knowledge");

    const treeEnabled = useTreeLayoutFlag();

    const { currentParentId, breadcrumbPath, setCurrentParent, setSelectedFile } =
        useKnowledgeStore();

    // Derive space name from the window/localStorage shortcut that Header already uses
    const spaceName: string =
        (window as any).libname?.[0] || localStorage.getItem("libname") || "";

    useEffect(() => {
        const guardByPermission = async () => {
            if (!knowledgeId) {
                setPermissionChecked(true);
                navigate("/filelib");
                return;
            }
            const [result, editResult, deleteResult] = await Promise.all([
                captureAndAlertRequestErrorHoc(
                    checkPermission("knowledge_library", String(knowledgeId), "can_read", "view_kb")
                ),
                captureAndAlertRequestErrorHoc(
                    checkPermission("knowledge_library", String(knowledgeId), "can_edit", "edit_kb")
                ),
                captureAndAlertRequestErrorHoc(
                    checkPermission(
                        "knowledge_library",
                        String(knowledgeId),
                        "can_delete",
                        "delete_kb"
                    )
                ),
            ]);
            const allowed = !!result?.allowed;
            setCanEditKb(!!editResult?.allowed);
            setCanDeleteKb(!!deleteResult?.allowed);
            setPermissionChecked(true);
            if (!allowed) {
                message({ variant: "warning", description: t("noOperationPermission") });
                navigate("/filelib");
            }
        };
        guardByPermission();
    }, [knowledgeId]);

    return (
        <div className="size-full px-2 relative bg-background-login">
            {!permissionChecked && (
                <div className="absolute inset-0 z-20 flex items-center justify-center bg-background/60">
                    <LoadingIcon />
                </div>
            )}

            {!treeEnabled ? (
                // Feature flag off — render the original Tab layout unchanged
                <LegacyTabLayout
                    knowledgeId={knowledgeId}
                    canEditKb={canEditKb}
                    canDeleteKb={canDeleteKb}
                />
            ) : (
                // Feature flag on — new left-sidebar + breadcrumb layout
                <div className="flex flex-col h-full">
                    <header className="flex items-center px-4 py-2 border-b">
                        <Header fileTitle={true} showBackButton={true} />
                        <div className="ml-4">
                            <KnowledgeBreadcrumb
                                spaceName={spaceName}
                                path={breadcrumbPath}
                                onNavigate={(id, index) => {
                                    if (id === null) {
                                        setCurrentParent(null, []);
                                    } else {
                                        setCurrentParent(id, breadcrumbPath.slice(0, index + 1));
                                    }
                                }}
                            />
                        </div>
                    </header>
                    <div className="flex flex-1 overflow-hidden">
                        <aside className="w-64 border-r overflow-y-auto p-2 shrink-0">
                            <KnowledgeTree
                                knowledgeId={Number(knowledgeId)}
                                onSelectFolder={(folder) =>
                                    setCurrentParent(folder.id, [
                                        ...breadcrumbPath,
                                        folder,
                                    ])
                                }
                            />
                        </aside>
                        <main className="flex-1 overflow-y-auto p-2 relative">
                            <Files
                                parentId={currentParentId}
                                onSelectFolder={(folder) =>
                                    setCurrentParent(folder.id, [
                                        ...breadcrumbPath,
                                        folder,
                                    ])
                                }
                                onSelectFile={(fileId) => setSelectedFile(fileId)}
                                canEditKb={canEditKb}
                                canDeleteKb={canDeleteKb}
                            />
                        </main>
                    </div>
                </div>
            )}
        </div>
    );
}
