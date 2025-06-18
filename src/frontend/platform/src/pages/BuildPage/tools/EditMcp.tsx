import { LoadIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { userContext } from "@/contexts/userContext";
import { createTool, deleteTool, getMcpServeByConfig, testMcpApi, updateTool } from "@/controllers/API/tools";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { isValidJSON } from "@/util/utils";
import { forwardRef, useContext, useEffect, useImperativeHandle, useRef, useState } from "react";

// 测试对话框组件
const TestDialog = forwardRef((props, ref) => {
    const [testShow, setTestShow] = useState(false);
    const [toolData, setToolData] = useState(null);
    const [params, setParams] = useState({});
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);
    const { message } = useToast();
    const serverRef = useRef({});
    const openapiSchemaRef = useRef('')

    useImperativeHandle(ref, () => ({
        open: (tool, config, _serverRef) => {
            openapiSchemaRef.current = config
            const openapiSchema = JSON.parse(config)
            setToolData({ ...tool, openapiSchema });
            setParams({});
            setResult("");
            setTestShow(true);
            serverRef.current = _serverRef;
        }
    }));

    const handleTest = async () => {
        // 校验必填参数
        const requiredParams = Object.entries(toolData.inputSchema.properties)
            .filter(([_, schema]) => schema.required)
            .map(([name]) => name);

        const errors = requiredParams.filter(name => !params[name]);
        if (errors.length > 0) {
            return message({ description: `以下参数必填：${errors.join(", ")}`, variant: "warning" });
        }

        setLoading(true);
        try {
            console.log('toolData :>> ', toolData);
            const { server_host, children, auth_method, auth_type, api_key } = serverRef.current

            const res = await captureAndAlertRequestErrorHoc(
                testMcpApi({
                    server_host,
                    extra: children.find(el => el.name === toolData.name).extra,
                    auth_method,
                    auth_type,
                    api_key,
                    request_params: params,
                    openapi_schema: openapiSchemaRef.current
                }).then(setResult)
            );
            console.log('res :>> ', res);
            // setResult(JSON.stringify(res, null, 2));
        } finally {
            setLoading(false);
        }
    };

    return (
        <Dialog open={testShow} onOpenChange={setTestShow}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{toolData?.name}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-8 py-6">
                    <div className="max-h-[600px] overflow-y-auto">
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead>参数</TableHead>
                                    <TableHead>值</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {Object.entries(toolData?.inputSchema?.properties || {}).map(([name, schema]) => (
                                    <TableRow key={name}>
                                        <TableCell>
                                            {name}
                                            {toolData?.inputSchema.required?.includes(name) && <span className="text-red-500">*</span>}
                                        </TableCell>
                                        <TableCell>
                                            <Input
                                                placeholder={`输入${schema.type || 'string'}类型值`}
                                                onChange={(e) => setParams(prev => ({
                                                    ...prev,
                                                    [name]: e.target.value
                                                }))}
                                            />
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                    <Button onClick={handleTest} disabled={loading}>测试</Button>
                    <Textarea
                        value={result}
                        placeholder="点击按钮，输出测试结果"
                        readOnly
                        className="mt-2 min-h-[100px]"
                    />
                </div>
            </DialogContent>
        </Dialog>
    );
});

// 主组件  TODO(重构,状态混乱)
const McpServerEditorDialog = forwardRef(({ existingNames = [], onReload }, ref) => {
    const [isDialogOpen, setIsDialogOpen] = useState(false);
    const [isEditMode, setIsEditMode] = useState(false);
    const [availableTools, setAvailableTools] = useState([]);

    const initialFormState = {
        name: "",
        openapiSchema: ""
    };
    const [formData, setFormData] = useState(initialFormState);
    const serverRef = useRef(initialFormState);
    const originalName = useRef("");
    const { message } = useToast();
    const testToolDialogRef = useRef(null);
    const { user } = useContext(userContext);
    const [isSelf, setIsSelf] = useState(false);
    // 解析标记
    const textareaRef = useRef(null);
    const [isLoading, setIsLoading] = useState(false); // 加载状态
    const latestFormData = useRef(initialFormState); // 存储最新表单数据
    const parseBeforeSaveRef = useRef(false); // 保存前需要解析
    useEffect(() => {
        latestFormData.current = formData;
    }, [formData]);

    // 示例配置
    const exampleConfigs = {
        gaode: JSON.stringify({
            "mcpServers": {
                "amap-sse": {
                    "name": "高德地图",
                    "description": "提供全场景覆盖的地图服务，包括地理编码、逆地理编码、IP 定位、天气查询、骑行路径规划、步行路径规划、驾车路径规划、公交路径规划、距离测量、关键词搜索、周边搜索、详情搜索等。",
                    "url": "https://mcp.amap.com/sse?key=yourapikey"
                }
            }
        }, null, 2)
    };

    // 暴露方法给父组件
    useImperativeHandle(ref, () => ({
        open: (serverData = null) => {
            if (serverData) {
                const newFormData = {
                    ...serverData,
                    openapiSchema: serverData.openapi_schema
                };
                setFormData(newFormData);
                latestFormData.current = newFormData;
                serverRef.current = serverData;
                setIsSelf(serverData.user_id === user.user_id);
                originalName.current = serverData.name;
                setIsEditMode(true);
                loadToolsFromSchema(serverData.openapi_schema);
            } else {
                resetFormState();
                setIsEditMode(false);
            }
            setIsDialogOpen(true);
            setIsLoading(false);
        }
    }));


    // 重置表单
    const resetFormState = () => {
        setFormData(initialFormState);
        latestFormData.current = initialFormState;
        serverRef.current = initialFormState;
        setAvailableTools([]);
    };

    const loadToolsFromSchema = async (schemaContent) => {
        if (!schemaContent.trim()) return;

        if (!isValidJSON(schemaContent)) {
            setAvailableTools([]);
            return message({
                description: "配置格式错误，请检查JSON格式是否正确",
                variant: "warning"
            });
        }

        // setIsLoading(true);
        try {
            const tools = await captureAndAlertRequestErrorHoc(
                getMcpServeByConfig({ file_content: schemaContent }),
                (res) => {
                    serverRef.current.children = [];
                    setAvailableTools([]);
                }
            );

            if (tools) {
                serverRef.current = tools;
                const parsedApis = tools.children.map(item => JSON.parse(item.extra));
                setAvailableTools(parsedApis);

                // 更新表单数据和ref
                const newFormData = {
                    ...latestFormData.current,
                    children: tools.children
                };
                setFormData(newFormData);
                latestFormData.current = newFormData;
            }
        } finally {
            // setIsLoading(false);
            parseBeforeSaveRef.current = false;
        }
    };

    const validateForm = () => {
        const errors = [];
        const name = latestFormData.current.name.trim();
        const schema = latestFormData.current.openapiSchema.trim();

        // 名称校验
        if (!name) {
            errors.push("名称不能为空");
        } else if (
            existingNames.some(
                n => n.toLowerCase() === name.toLowerCase() &&
                    n !== originalName.current
            )
        ) {
            errors.push("名称已存在，请修改");
        }

        // Schema校验
        if (!schema) {
            errors.push("配置不能为空");
        } else if (!isValidJSON(schema)) {
            errors.push("配置格式错误，请检查JSON格式是否正确");
        }

        return errors;
    };

    // 表单提交
    const handleSubmit = async () => {
        if (parseBeforeSaveRef.current) {
            setIsLoading(true);
            await loadToolsFromSchema(textareaRef.current.value)
            parseBeforeSaveRef.current = false
            setTimeout(() => {
                handleSubmit()
            }, 0);
        }

        // 使用latestFormData.current获取最新数据
        const validationErrors = validateForm();
        if (validationErrors.length > 0) {
            return message({
                description: validationErrors,
                variant: "warning"
            });
        }

        setIsLoading(true);
        try {
            const apiMethod = isEditMode ? updateTool : createTool;
            const { openapiSchema, ...other } = latestFormData.current;

            await captureAndAlertRequestErrorHoc(apiMethod({
                ...serverRef.current,
                ...other,
                description: serverRef.current.description,
                openapi_schema: openapiSchema,
                is_preset: 2
            })).then((res) => {
                if (!res) return;
                message({ description: "保存成功", variant: "success" });
                setIsDialogOpen(false);
                onReload();
            });
        } finally {
            setIsLoading(false);
        }
    };

    // 删除服务器（保持不变）
    const handleServerDelete = () => {
        bsConfirm({
            title: "提示",
            desc: "确认删除该 MCP 服务器？",
            onOk(closeDialog) {
                captureAndAlertRequestErrorHoc(
                    deleteTool(formData.id)
                ).then(() => {
                    setIsDialogOpen(false);
                    onReload();
                    closeDialog();
                });
            }
        });
    };

    const handleExampleSelect = (exampleKey) => {
        const exampleSchema = exampleConfigs[exampleKey];
        setFormData(prev => ({
            ...prev,
            openapiSchema: exampleSchema
        }));
        loadToolsFromSchema(exampleSchema);
    };
    return (
        <div>
            <Sheet open={isDialogOpen} onOpenChange={setIsDialogOpen}>
                <SheetContent className="w-[800px] sm:max-w-[800px] p-4 bg-background-login">
                    <SheetHeader>
                        <SheetTitle>{isEditMode ? "编辑" : "添加"} MCP 服务器</SheetTitle>
                    </SheetHeader>

                    <div className="mt-4 space-y-6 px-6 overflow-y-auto h-[calc(100vh-200px)]">
                        {/* 名称输入 */}
                        <div>
                            <label className="">名称</label>
                            <Input
                                value={formData.name}
                                className="mt-2"
                                placeholder="输入MCP 服务名称"
                                onChange={(e) => setFormData(prev => ({
                                    ...prev,
                                    name: e.target.value
                                }))}
                            />
                        </div>

                        {/* 配置输入 */}
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <label className="">MCP服务器配置</label>
                                <Select value={'1'} onValueChange={handleExampleSelect}>
                                    <SelectTrigger className="w-[180px]">
                                        <span>示例</span>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value="gaode">高德地图</SelectItem>
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                            <Textarea
                                ref={textareaRef}
                                value={formData.openapiSchema}
                                placeholder="输入您的 MCP 服务器配置 json"
                                className="min-h-[200px] font-mono"
                                onChange={(e) => {
                                    setFormData(prev => ({
                                        ...prev,
                                        openapiSchema: e.target.value
                                    }))
                                    parseBeforeSaveRef.current = true;
                                }}
                                onBlur={() => loadToolsFromSchema(formData.openapiSchema)}
                            />
                        </div>

                        {/* 工具列表 */}
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <label>可用工具</label>
                                <Button variant="outline" disabled={isLoading} onClick={() => loadToolsFromSchema(formData.openapiSchema)}>
                                    刷新
                                </Button>
                            </div>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>名称</TableHead>
                                        <TableHead>描述</TableHead>
                                        <TableHead>操作</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {availableTools.map((tool) => (
                                        <TableRow key={tool.name}>
                                            <TableCell>{tool.name}</TableCell>
                                            <TableCell>{tool.description}</TableCell>
                                            <TableCell>
                                                <Button
                                                    variant="outline"
                                                    onClick={() => testToolDialogRef.current.open(
                                                        tool,
                                                        formData.openapiSchema,
                                                        serverRef.current
                                                    )}
                                                >
                                                    测试
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </div>

                    {/* 底部操作按钮 */}
                    <SheetFooter className="absolute bottom-0 right-0 w-full px-6 py-4">
                        {isEditMode && (user.role === 'admin' || isSelf) && (
                            <Button
                                variant="destructive"
                                className="mr-auto"
                                onClick={handleServerDelete}
                            >
                                删除
                            </Button>
                        )}
                        <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
                            取消
                        </Button>
                        <Button disabled={isLoading} onClick={handleSubmit}>
                            {isLoading && <LoadIcon className="mr-1" />}
                            保存
                        </Button>
                    </SheetFooter>
                </SheetContent>
            </Sheet>
            <TestDialog ref={testToolDialogRef} />
        </div>
    );
});

export default McpServerEditorDialog;
