import { LoadIcon } from "@/components/bs-icons";
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Accordion } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { getAssistantMcpApi, getAssistantToolsWithManageApi, refreshAssistantMcpApi } from "@/controllers/API/assistant";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { CpuIcon, Star, User } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import McpServerDialog from "./EditMcp";
import EditTool from "./EditTool";
import ToolItem from "./ToolItem";
import ToolSet from "./ToolSet";

const MANAGED_TOOLS = [
    'Dalle3绘画', 'Bing web搜索', '天眼查',
    'Firecrawl', 'Jina AI', 'SiliconFlow',
    '发送邮件', '飞书消息', '联网搜索', '代码执行器'
];

interface TabToolsProps {
    select?: any;
    onSelect: (tool: any) => void;
}

const TabTools = ({ select = null, onSelect }: TabToolsProps) => {
    const [keyword, setKeyword] = useState(" ");
    const [allData, setAllData] = useState([]);
    const { t } = useTranslation()

    const { user } = useContext(userContext)

    const [type, setType] = useState("");
    const editRef = useRef(null);
    const mcpDialogRef = useRef(null);

    useToolType(setType)
    const [loading, setLoading] = useState(false)

    const loadData = async (_type = "custom") => {
        await getAssistantToolsWithManageApi(_type).then((res) => {
            setAllData(res);
        });
        setLoading(false)
    };
    const loadMcpData = async () => {
        await getAssistantMcpApi().then((res) => {
            setAllData(res);
        });
        setLoading(false)
    }
    useEffect(() => {
        setLoading(true)
        if (type === 'mcp') {
            loadMcpData()
        } else {
            loadData(type === "" ? "default" : "custom");
        }
    }, [type]);

    const options = useMemo(() => {
        return allData.filter((el) => {
            // Search in tool name, description, API name, and API description
            const targetStr = `${el.name}-${el.description}-${el.children?.map((el) => {
                // For MCP, search includes parameter names and descriptions
                const param = type === 'mcp' ? (el.api_params.map((param) => param.name + param.description).join("-") || '') : ''
                return el.name + el.desc + param
            }).join("-") || ''}`
            return targetStr.toLowerCase().includes(keyword.trim().toLowerCase());
        });
    }, [keyword, type, allData]);

    const hasSet = (name) => {
        if (user.role !== 'admin') return false
        return MANAGED_TOOLS.includes(name)
    }

    const toolsetRef = useRef(null)
    const { loading: btnLoading, refresh } = useMcpRefrensh(t)

    return (
        <div className="flex h-full relative" onClick={(e) => e.stopPropagation()}>
            <div className="relative w-full flex h-full overflow-y-scroll scrollbar-hide bg-background-main border-t">
                <div className="relative w-fit p-6">
                    <SearchInput
                        placeholder={t("tools.search")}
                        className="mt-6"
                        onChange={(e) => setKeyword(e.target.value)}
                    />
                    <div className="mt-4">
                        <div
                            className={`flex cursor-pointer items-center gap-2 rounded-md px-4 py-2 transition-all duration-200 hover:bg-muted-foreground/10 ${type === "" && "bg-muted-foreground/10"
                                }`}
                            onClick={() => setType("")}
                        >
                            <User />
                            <span>{t("tools.builtinTools")}</span>
                        </div>
                        <div
                            className={`mt-1 flex cursor-pointer items-center gap-2 rounded-md px-4 py-2 transition-all duration-200 hover:bg-muted-foreground/10 ${type === "edit" && "bg-muted-foreground/10"
                                }`}
                            onClick={() => setType("edit")}
                        >
                            <Star />
                            <span>{t("tools.customTools")}</span>
                        </div>
                        <div
                            className={`mt-1 flex cursor-pointer items-center gap-2 rounded-md px-4 py-2 transition-all duration-200 hover:bg-muted-foreground/10 ${type === "mcp" && "bg-muted-foreground/10"
                                }`}
                            onClick={() => setType("mcp")}
                        >
                            <CpuIcon />
                            <span>{t("tools.mcpTools")}</span>
                        </div>
                    </div>
                    <div className="absolute bottom-0 left-0 flex h-16 w-full items-center justify-betwee px-2">
                        <p className="text-sm text-muted-foreground break-all">
                            {t("tools.manageCustomTools")}
                        </p>
                    </div>
                </div>
                <div className="h-full w-full flex-1 overflow-auto bg-background-login p-5 pb-20 pt-2 scrollbar-hide">
                    {
                        loading && <div className="absolute top-0 left-0 w-full h-full flex items-center justify-center bg-primary/5 z-10">
                            <LoadingIcon className="size-24" />
                        </div>
                    }
                    <div className="mb-4">
                        {type === 'edit' && <Button
                            id="create-apitool"
                            className="mt-4  text-[white]"
                            onClick={() => editRef.current.open()}
                        >
                            {t('create')}{t("tools.createCustomTool")}
                        </Button>}
                        {type === 'mcp' && <Button
                            id="create-mcptool"
                            className="mt-4  text-[white]"
                            onClick={() => mcpDialogRef.current.open()}
                        >
                            {t("tools.addMcpServer")}
                        </Button>}
                        {type === 'mcp' && <Button
                            variant="outline"
                            disabled={btnLoading}
                            className="mt-4 ml-4"
                            onClick={async () => {
                                await refresh()
                                loadMcpData()
                            }}
                        >
                            {btnLoading && <LoadIcon className="text-gray-800" />}
                            {t("tools.refresh")}
                        </Button>}
                    </div>
                    {
                        !loading && <Accordion type="single" collapsible className="w-full">
                            {options.length ? (
                                options.map((el) => (
                                    <ToolItem
                                        key={el.id}
                                        type={type}
                                        select={select}
                                        data={el}
                                        onSelect={onSelect}
                                        onSetClick={hasSet(el.name) ? () => toolsetRef.current.edit(el) : null}
                                        onEdit={(id) => {
                                            type === 'mcp' ? mcpDialogRef.current.open(el) :
                                                editRef.current.edit(el)
                                        }}
                                    ></ToolItem>
                                ))
                            ) : (
                                <div className="mt-2 pt-40 text-center text-sm text-muted-foreground">
                                    {t("tools.empty")}
                                </div>
                            )}
                        </Accordion>
                    }
                </div>
            </div>

            <EditTool
                onReload={() => {
                    setType('edit');
                    type === 'edit' && loadData();
                }}
                ref={editRef}
            />

            <McpServerDialog
                ref={mcpDialogRef}
                existingNames={options.map((el) => el.name)}
                onReload={loadMcpData}
                onSuccess={() => { }}
            />

            <ToolSet ref={toolsetRef} onChange={() => loadData("default")} />
        </div>
    );
}

export const useMcpRefrensh = (t) => {
    const [loading, setLoading] = useState(false);
    const { message } = useToast()

    return {
        loading,
        async refresh() {
            setLoading(true);
            const res = await captureAndAlertRequestErrorHoc(refreshAssistantMcpApi())
            message({
                variant: "success",
                description: t("refreshSuccess")
            })
            setLoading(false);
        }
    }
}

const useToolType = (setType) => {
    const [searchParams, setSearchParams] = useSearchParams();
    useEffect(() => {
        const type = searchParams.get('c');
        setSearchParams({})
        if (!type) return

        setType(type === 'mcp' ? type : 'edit')
        setTimeout(() => {
            document.getElementById(type === 'mcp' ? 'create-mcptool' : 'create-apitool')?.click()
        }, 100)
    }, [searchParams])
}

export default TabTools;
