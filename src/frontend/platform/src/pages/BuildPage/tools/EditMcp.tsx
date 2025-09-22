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
import { useTranslation } from "react-i18next";

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
        // const requiredParams = Object.entries(toolData.inputSchema.properties)
        //     .filter(([_, schema]) => schema.required)
        //     .map(([name]) => name);
        const requiredParams = toolData.inputSchema.required

        const errors = requiredParams.filter(name => !params[name]);
        if (errors.length > 0) {
            return message({ description: errors.map(n => `${n} ${t('required')}`), variant: "warning" });
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

    const { t } = useTranslation();

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
                                    <TableHead>{t('test.parameter')}</TableHead>
                                    <TableHead>{t('test.value')}</TableHead>
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
                    <Button onClick={handleTest} disabled={loading}>{t('test.test')}</Button>
                    <Textarea
                        value={result}
                        placeholder={t('test.outResultPlaceholder')}
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

    const { t } = useTranslation();

    // 示例配置
    const exampleConfigs = {
        gaode1: JSON.stringify({
            "mcpServers": {
                "amap-sse": {
                    "type": "sse",
                    "name": "高德地图",
                    "description": "提供全场景覆盖的地图服务，包括地理编码、逆地理编码、IP 定位、天气查询、骑行路径规划、步行路径规划、驾车路径规划、公交路径规划、距离测量、关键词搜索、周边搜索、详情搜索等。",
                    "url": "https://mcp.amap.com/sse?key=yourapikey"
                }
            }
        }, null, 2),
        gaode2: JSON.stringify({
            "mcpServers": {
                "amap-streamable": {
                    "type": "streamable",
                    "name": "高德地图",
                    "description": "提供全场景覆盖的地图服务，包括地理编码、逆地理编码、IP 定位、天气查询、骑行路径规划、步行路径规划、驾车路径规划、公交路径规划、距离测量、关键词搜索、周边搜索、详情搜索等。",
                    "url": "https://mcp.amap.com/mcp?key=yourapikey"
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
            return message({ description: t('tools.configFormatError'), variant: "warning" });
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
            errors.push(t('tools.nameRequired'));
        } else if (
            existingNames.some(
                n => n.toLowerCase() === name.toLowerCase() &&
                    n !== originalName.current
            )
        ) {
            errors.push(t('tools.nameExists'));
        }

        // Schema校验
        if (!schema) {
            errors.push(t('tools.configRequired'));
        } else if (!isValidJSON(schema)) {
            errors.push(t('tools.configFormatError'));
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
                message({ description: t('skills.saveSuccessful'), variant: "success" });
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
            title: t('prompt'),
            desc: t('tools.confirmDeleteMcp'),
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
                        <SheetTitle>{isEditMode ? t('edit') : t('add')} {t('mcpServer')}</SheetTitle>
                    </SheetHeader>

                    <div className="mt-4 space-y-6 px-6 overflow-y-auto h-[calc(100vh-200px)]">
                        {/* 名称输入 */}
                        <div>
                            <label className="">{t('tools.name')}</label>
                            <Input
                                value={formData.name}
                                className="mt-2"
                                placeholder={t('tools.enterMcpName')}
                                onChange={(e) => setFormData(prev => ({
                                    ...prev,
                                    name: e.target.value
                                }))}
                            />
                        </div>

                        {/* 配置输入 */}
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <label className="">{t('tools.mcpServerConfig')}</label>
                                <Select value={'1'} onValueChange={handleExampleSelect}>
                                    <SelectTrigger className="w-[180px]">
                                        <span>{t('tools.examples')}</span>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value="gaode1">高德地图（SSE 协议）</SelectItem>
                                            <SelectItem value="gaode2">高德地图（streamable 协议）</SelectItem>
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                            <Textarea
                                ref={textareaRef}
                                value={formData.openapiSchema}
                                placeholder={t('tools.enterOpenAPISchema')}
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
                                <label>{t('tools.availableTools')}</label>
                                <Button variant="outline" disabled={isLoading} onClick={() => loadToolsFromSchema(formData.openapiSchema)}>
                                    {t('build.refresh')}
                                </Button>
                            </div>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>{t('tools.name')}</TableHead>
                                        <TableHead>{t('tools.description')}</TableHead>
                                        <TableHead>{t('operations')}</TableHead>
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
                                                >{t('test.test')}</Button>
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
                                {t('delete')}
                            </Button>
                        )}
                        <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
                            {t('cancel')}
                        </Button>
                        <Button disabled={isLoading} onClick={handleSubmit}>
                            {isLoading && <LoadIcon className="mr-1" />}
                            {t('save')}
                        </Button>
                    </SheetFooter>
                </SheetContent>
            </Sheet>
            <TestDialog ref={testToolDialogRef} />
        </div>
    );
});

export default McpServerEditorDialog;
