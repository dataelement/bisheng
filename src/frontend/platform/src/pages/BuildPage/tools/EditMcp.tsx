import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "@/components/bs-ui/select";
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table";
import { useToast } from "@/components/bs-ui/toast/use-toast";
// import { createMcpServer, deleteMcpServer, getMcpTools, testMcpTool, updateMcpServer } from "@/controllers/API/mcp";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { Plus } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

// 测试对话框组件
const TestDialog = forwardRef((props, ref) => {
    const [testShow, setTestShow] = useState(false);
    const [toolData, setToolData] = useState(null);
    const [params, setParams] = useState({});
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);
    const { message } = useToast();

    useImperativeHandle(ref, () => ({
        open: (tool, config) => {
            setToolData({ ...tool, config });
            setParams({});
            setResult("");
            setTestShow(true);
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
            // const res = await captureAndAlertRequestErrorHoc(
            //     testMcpTool({
            //         config: toolData.config,
            //         toolName: toolData.name,
            //         params
            //     })
            // );
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
                                            {schema.required && <span className="text-red-500">*</span>}
                                        </TableCell>
                                        <TableCell>
                                            <Input
                                                placeholder={`输入${schema.type}类型值`}
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

// 主组件
const McpServerDialog = forwardRef(({ existingNames = [], onReload }, ref) => {
    const [open, setOpen] = useState(false);
    const [isEdit, setIsEdit] = useState(false);
    const [tools, setTools] = useState([]);
    const initialData = {
        name: "",
        config: "{}"
    };
    const [formData, setFormData] = useState(initialData);
    const serverRef = useRef(initialData);
    const { message } = useToast();
    const testDialogRef = useRef();

    // 示例配置
    const examples = {
        tavily: JSON.stringify({
            base_url: "https://api.tavily.com",
            api_key: "YOUR_API_KEY"
        }, null, 2)
    };

    // 暴露方法给父组件
    useImperativeHandle(ref, () => ({
        open: (server = null) => {
            if (server) {
                setFormData(server);
                serverRef.current = server;
                setIsEdit(true);
                fetchTools(server.config);
            } else {
                resetForm();
                setIsEdit(false);
            }
            setOpen(true);
        }
    }));

    // 重置表单
    const resetForm = () => {
        setFormData(initialData);
        serverRef.current = initialData;
        setTools([]);
    };

    // 获取工具列表
    const fetchTools = async (config) => {
        try {
            const jsonConfig = JSON.parse(config);
            console.log('jsonConfig :>> ', jsonConfig);
            // const tools = await captureAndAlertRequestErrorHoc(getMcpTools(jsonConfig));
            // setTools(tools || []);
            setTools([{
                name: 'xxx',
                description: 'yyyyy',
                inputSchema: {
                    type: "object",
                    properties: {
                        name: {
                            type: "string",
                            required: true
                        }
                    }
                }
            }]);
        } catch (error) {
            message({ description: "配置解析失败，请检查JSON格式", variant: "warning" });
            setTools([]);
        }
    };

    // 表单提交
    const handleSubmit = () => {
        // 校验逻辑
        const errors = [];
        if (!formData.name.trim()) errors.push("名称不能为空");
        if (!formData.config.trim()) errors.push("配置不能为空");

        // 名称唯一性校验（不区分大小写）
        const nameLower = formData.name.toLowerCase();
        if (existingNames.some(n => n.toLowerCase() === nameLower && n !== serverRef.current.name)) {
            errors.push("名称已存在，请修改");
        }

        // JSON格式校验
        try {
            JSON.parse(formData.config);
        } catch {
            errors.push("配置格式错误，请检查JSON格式是否正确");
        }

        if (errors.length > 0) {
            return message({ description: errors, variant: "warning" });
        }

        // 提交数据
        // const apiMethod = isEdit ? updateMcpServer : createMcpServer;
        // captureAndAlertRequestErrorHoc(apiMethod({
        //     ...serverRef.current,
        //     ...formData,
        //     config: JSON.parse(formData.config) // 确保存储的是对象
        // })).then(() => {
        //     message({ description: "保存成功", variant: "success" });
        //     setOpen(false);
        // });
    };

    // 删除服务器
    const handleDelete = () => {
        bsConfirm({
            title: "确认删除",
            desc: "确认删除该 MCP 服务器？",
            onOk(next) {
                // captureAndAlertRequestErrorHoc(deleteMcpServer(serverRef.current.id)).then(() => {
                //     setOpen(false);
                // onReload()
                //     next();
                // });
            }
        });
    };

    return (
        <div>
            <Sheet open={open} onOpenChange={setOpen}>
                <SheetContent className="w-[800px] sm:max-w-[800px] p-4 bg-background-login">
                    <SheetHeader>
                        <SheetTitle>{isEdit ? "编辑" : "添加"} MCP 服务器</SheetTitle>
                    </SheetHeader>

                    <div className="mt-4 space-y-6 px-6 overflow-y-auto h-[calc(100vh-200px)]">
                        {/* 名称输入 */}
                        <div>
                            <Label className="bisheng-label">名称</Label>
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
                                <Label className="bisheng-label">MCP服务器配置</Label>
                                <Select onValueChange={(v) => setFormData(prev => {
                                    fetchTools(examples[v])
                                    return {
                                        ...prev,
                                        config: examples[v]
                                    }
                                })
                                }>
                                    <SelectTrigger className="w-[180px]">
                                        <span>配置示例</span>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectGroup>
                                            <SelectItem value="tavily">Tavily 搜索</SelectItem>
                                        </SelectGroup>
                                    </SelectContent>
                                </Select>
                            </div>
                            <Textarea
                                value={formData.config}
                                placeholder="输入您的 MCP 服务器配置 json"
                                className="min-h-[200px] font-mono"
                                onChange={(e) => setFormData(prev => ({
                                    ...prev,
                                    config: e.target.value
                                }))}
                                onBlur={() => fetchTools(formData.config)}
                            />
                        </div>

                        {/* 工具列表 */}
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <Label>可用工具</Label>
                                <Button variant="outline" onClick={() => fetchTools(formData.config)}>
                                    刷新列表
                                </Button>
                            </div>
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>工具名称</TableHead>
                                        <TableHead>描述</TableHead>
                                        <TableHead>操作</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {tools.map((tool) => (
                                        <TableRow key={tool.name}>
                                            <TableCell>{tool.name}</TableCell>
                                            <TableCell>{tool.description}</TableCell>
                                            <TableCell>
                                                <Button
                                                    variant="outline"
                                                    onClick={() => testDialogRef.current.open(
                                                        tool,
                                                        JSON.parse(formData.config)
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
                        {isEdit && (
                            <Button
                                variant="destructive"
                                className="mr-auto"
                                onClick={handleDelete}
                            >
                                删除
                            </Button>
                        )}
                        <Button variant="outline" onClick={() => setOpen(false)}>
                            取消
                        </Button>
                        <Button onClick={handleSubmit}>保存</Button>
                    </SheetFooter>
                </SheetContent>
            </Sheet>
            <TestDialog ref={testDialogRef} />
        </div>
    );
});

export default McpServerDialog;