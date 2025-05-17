import { LoadIcon } from "@/components/bs-icons";
import { Accordion } from "@/components/bs-ui/accordion";
import { Button } from "@/components/bs-ui/button";
import { SearchInput } from "@/components/bs-ui/input";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { getAssistantMcpApi, getAssistantToolsApi, refreshAssistantMcpApi } from "@/controllers/API/assistant";
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
    '发送邮件', '飞书消息'
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

    const loadData = (_type = "custom") => {
        getAssistantToolsApi(_type).then((res) => {
            setAllData(res);
            setKeyword("");
        });
    };
    const loadMcpData = () => {
        getAssistantMcpApi().then((res) => {
            setAllData(res);
            setKeyword("");
        });
    }
    useEffect(() => {
        if (type === 'mcp') return loadMcpData()
        loadData(type === "" ? "default" : "custom");
    }, [type]);

    const options = useMemo(() => {
        return allData.filter((el) => {
            // 搜索范围：工具名称、工具描述、工具api名称、工具api描述
            const targetStr = `${el.name}-${el.description}-${el.children?.map((el) => {
                // mcp 搜索包含参数名 参数描述
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
    const { loading, refresh } = useMcpRefrensh()

    return (
        <div className="flex h-full relative" onClick={(e) => e.stopPropagation()}>
            <div className="relative w-full flex h-full overflow-y-scroll scrollbar-hide bg-background-main border-t">
                <div className="relative w-fit p-6">
                    {/* <h1>{t("tools.addTool")}</h1> */}
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
                            <span>MCP工具</span>
                        </div>
                    </div>
                    <div className="absolute bottom-0 left-0 flex h-16 w-full items-center justify-betwee px-2">
                        <p className="text-sm text-muted-foreground break-all">
                            {t("tools.manageCustomTools")}
                        </p>
                    </div>
                </div>
                <div className="h-full w-full flex-1 overflow-auto bg-background-login p-5 pb-20 pt-2 scrollbar-hide">
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
                            添加 MCP 服务器
                        </Button>}
                        {type === 'mcp' && <Button
                            variant="outline"
                            disabled={loading}
                            className="mt-4 ml-4"
                            onClick={async () => {
                                await refresh()
                                loadMcpData()
                            }}
                        >
                            {loading && <LoadIcon className="text-gray-800" />}
                            刷新
                        </Button>}
                    </div>
                    <Accordion type="single" collapsible className="w-full">
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
                </div>
            </div>

            <EditTool
                onReload={() => {
                    // 切换自定义工具 并 刷新
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

            {/* 内置工具设置 */}
            <ToolSet ref={toolsetRef} onChange={() => loadData("default")} />
        </div>
    );
}

// 刷新mcp服务
export const useMcpRefrensh = () => {
    const [loading, setLoading] = useState(false);
    const { message } = useToast()

    return {
        loading,
        async refresh() {
            setLoading(true);
            // api
            const res = await captureAndAlertRequestErrorHoc(refreshAssistantMcpApi())
            // console.log('刷新 :>> ', res);
            if (res) {
                message({
                    variant: "success",
                    description: "刷新成功"
                })
            }
            setLoading(false);
        }
    }
}

// 处理跳转参数,默认弹出创建工具
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