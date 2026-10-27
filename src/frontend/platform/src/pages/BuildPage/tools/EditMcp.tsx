// @ts-strict-ignore
import { Button, Dropdown, DropdownChevron, DropdownItem, Input, Textarea, toast } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Dialog,DialogContent,DialogHeader,DialogTitle } from "@/components/bs-ui/dialog";

import { Sheet,SheetContent,SheetFooter,SheetHeader,SheetTitle } from "@/components/bs-ui/sheet";
import { Table,TableBody,TableCell,TableHead,TableHeader,TableRow } from "@/components/bs-ui/table";

import { createTool,deleteTool,getMcpServeByConfig,testMcpApi,updateTool } from "@/controllers/API/tools";
import { handleUiRequest, showApiError } from "@/controllers/request";
import { isValidJSON } from "@/util/utils";
import { forwardRef,useEffect,useImperativeHandle,useMemo,useRef,useState } from "react";
import { useTranslation } from "react-i18next";

// test chat
const TestDialog = forwardRef((props, ref) => {
    const [testShow, setTestShow] = useState(false);
    const [toolData, setToolData] = useState(null);
    const [params, setParams] = useState({});
    const [result, setResult] = useState("");
    const [loading, setLoading] = useState(false);

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
        // validate params
        // const requiredParams = Object.entries(toolData.inputSchema.properties)
        //     .filter(([_, schema]) => schema.required)
        //     .map(([name]) => name);
        const requiredParams = toolData.inputSchema.required

        const errors = requiredParams.filter(name => !params[name]);
        if (errors.length > 0) {
            return toast.show({ type: "warning", message: (errors.map(n => `${n} ${t('required')}`)).filter(Boolean).join('\n') });
        }

        setLoading(true);
        try {
            console.log('toolData :>> ', toolData);
            const { server_host, children, auth_method, auth_type, api_key } = serverRef.current

            const res = await testMcpApi({
                    server_host,
                    extra: children.find(el => el.name === toolData.name).extra,
                    auth_method,
                    auth_type,
                    api_key,
                    request_params: params,
                    openapi_schema: openapiSchemaRef.current
                }).then(setResult);
            console.log('res :>> ', res);
            // setResult(JSON.stringify(res, null, 2));
        } catch (error) {
            showApiError(error);
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
                                            <Input placeholder={t('test.inputTypeValue', { type: schema.type || 'string' })} onChange={(e) => setParams(prev => ({
                                                    ...prev,
                                                    [name]: e.target.value
                                                }))} />
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </div>
                    <Button onClick={handleTest} disabled={loading}>{t('test.test')}</Button>
                    <Textarea value={result} placeholder={t('test.outResultPlaceholder')} readOnly textareaClassName={"mt-2 min-h-[100px]"} />
                </div>
            </DialogContent>
        </Dialog>
    );
});

// Main component  TODO(refactor, state confusion)
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

    const testToolDialogRef = useRef(null);
    // Parse flag
    const textareaRef = useRef(null);
    const [isLoading, setIsLoading] = useState(false); // Loading state
    const latestFormData = useRef(initialFormState); // Store latest form data
    const parseBeforeSaveRef = useRef(false); // Need to parse before saving
    const [canDelete, setCanDelete] = useState(false)
    useEffect(() => {
        latestFormData.current = formData;
    }, [formData]);

    const { t } = useTranslation();

    // Example configurations
    const exampleConfigs = useMemo(() => ({
        gaode1: JSON.stringify({
            "mcpServers": {
                "amap-sse": {
                    "type": "sse",
                    "name": t('tools.gaodeMap'),
                    "description": t('tools.gaodeMapDesc'),
                    "url": "https://mcp.amap.com/sse?key=yourapikey"
                }
            }
        }, null, 2),
        gaode2: JSON.stringify({
            "mcpServers": {
                "amap-streamable": {
                    "type": "streamable",
                    "name": t('tools.gaodeMap'),
                    "description": t('tools.gaodeMapDesc'),
                    "url": "https://mcp.amap.com/mcp?key=yourapikey"
                }
            }
        }, null, 2)
    }), [t]);

    // Expose methods to parent component
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
                setCanDelete(serverData.delete)
                originalName.current = serverData.name;
                setIsEditMode(true);
                void loadToolsFromSchema(serverData.openapi_schema).catch(showApiError);
            } else {
                resetFormState();
                setIsEditMode(false);
            }
            setIsDialogOpen(true);
            setIsLoading(false);
        }
    }));


    // Reset form
    const resetFormState = () => {
        setFormData(initialFormState);
        latestFormData.current = initialFormState;
        serverRef.current = initialFormState;
        setAvailableTools([]);
        setCanDelete(false);
    };

    const loadToolsFromSchema = async (schemaContent) => {
        if (!schemaContent.trim()) return;

        if (!isValidJSON(schemaContent)) {
            setAvailableTools([]);
            return toast.show({ type: "warning", message: String(t('tools.configFormatError') ?? '') });
        }

        // setIsLoading(true);
        try {
            const tools = await getMcpServeByConfig({ file_content: schemaContent });

            if (tools && typeof tools === 'object') {
                serverRef.current = tools;
                const parsedApis = tools.children.map(item => JSON.parse(item.extra));
                setAvailableTools(parsedApis);

                // Update form data and ref
                const newFormData = {
                    ...latestFormData.current,
                    children: tools.children
                };
                setFormData(newFormData);
                latestFormData.current = newFormData;
            }
        } catch (error) {
            serverRef.current.children = [];
            setAvailableTools([]);
            throw error;
        } finally {
            // setIsLoading(false);
            parseBeforeSaveRef.current = false;
        }
    };

    const validateForm = () => {
        const errors = [];
        const name = latestFormData.current.name.trim();
        const schema = latestFormData.current.openapiSchema.trim();

        // Name validation
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

        // Schema validation
        if (!schema) {
            errors.push(t('tools.configRequired'));
        } else if (!isValidJSON(schema)) {
            errors.push(t('tools.configFormatError'));
        }

        return errors;
    };

    // Form submission
    const handleSubmit = async () => {
        setIsLoading(true);
        try {
        if (parseBeforeSaveRef.current) {
            await loadToolsFromSchema(textareaRef.current.value)
            parseBeforeSaveRef.current = false
        }

        // Use latestFormData.current to get latest data
        const validationErrors = validateForm();
        if (validationErrors.length > 0) {
            return toast.show({ type: "warning", message: String(validationErrors ?? '') });
        }

            const apiMethod = isEditMode ? updateTool : createTool;
            const { openapiSchema, ...other } = latestFormData.current;

            await apiMethod({
                ...serverRef.current,
                ...other,
                description: serverRef.current.description,
                openapi_schema: openapiSchema,
                is_preset: 2
            }).then((res) => {
                if (!res) return;
                toast.show({ type: "success", message: String(t('skills.saveSuccessful') ?? '') });
                setIsDialogOpen(false);
                onReload();
            });
        } catch (error) {
            showApiError(error);
        } finally {
            setIsLoading(false);
        }
    };

    // Delete server (keep unchanged)
    const handleServerDelete = () => {
        bsConfirm({
            title: t('prompt'),
            desc: t('tools.confirmDeleteMcp'),
            onOk(closeDialog) {
                return deleteTool(formData.id).then(() => {
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
        void loadToolsFromSchema(exampleSchema).catch(showApiError);
    };
    return (
        <div>
            <Sheet open={isDialogOpen} onOpenChange={setIsDialogOpen}>
                <SheetContent className="w-[800px] sm:max-w-[800px] p-4 bg-background-login">
                    <SheetHeader>
                        <SheetTitle>{isEditMode ? t('edit') : t('add')} {t('mcpServer')}</SheetTitle>
                    </SheetHeader>

                    <div className="mt-4 space-y-6 px-6 overflow-y-auto h-[calc(100vh-200px-var(--license-banner-h,0px))]">
                        {/* Name input */}
                        <div>
                            <label className="">{t('tools.name')}</label>
                            <Input value={formData.name} placeholder={t('tools.enterMcpName')} onChange={(e) => setFormData(prev => ({
                                    ...prev,
                                    name: e.target.value
                                }))} className={"mt-2"} />
                        </div>

                        {/* Configuration input */}
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <label className="">{t('tools.mcpServerConfig')}</label>
                                {/* Inserting an example is an action (the trigger never shows a value), so this is a menu, not a Select. */}
                                <Dropdown
                                    align="end"
                                    menu={<>
                                        <DropdownItem onSelect={() => handleExampleSelect('gaode1')}>{t('tools.gaodeMapSSE')}</DropdownItem>
                                        <DropdownItem onSelect={() => handleExampleSelect('gaode2')}>{t('tools.gaodeMapStreamable')}</DropdownItem>
                                    </>}
                                >
                                    <Button type="button" variant="outlined" color="default">
                                        {t('tools.examples')}
                                        <DropdownChevron />
                                    </Button>
                                </Dropdown>
                            </div>
                            <Textarea ref={textareaRef} value={formData.openapiSchema} placeholder={t('tools.enterOpenAPISchema')} onChange={(e) => {
                                    setFormData(prev => ({
                                        ...prev,
                                        openapiSchema: e.target.value
                                    }))
                                    parseBeforeSaveRef.current = true;
                                }} onBlur={handleUiRequest(() => loadToolsFromSchema(formData.openapiSchema))} textareaClassName={"min-h-[200px] font-mono"} />
                        </div>

                        {/* Tool list */}
                        <div>
                            <div className="flex justify-between items-center mb-2">
                                <label>{t('tools.availableTools')}</label>
                                <Button variant="outlined" disabled={isLoading} onClick={handleUiRequest(() => loadToolsFromSchema(formData.openapiSchema))} color="default">
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
                                                <Button variant="outlined" onClick={() => testToolDialogRef.current.open(
                                                        tool,
                                                        formData.openapiSchema,
                                                        serverRef.current
                                                    )} color="default">{t('test.test')}</Button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </div>

                    {/* footer buttons */}
                    <SheetFooter className="absolute bottom-0 right-0 w-full px-6 py-4">
                        {isEditMode && canDelete && (
                            <Button variant="solid" className="mr-auto" onClick={handleServerDelete} color="danger">
                                {t('delete')}
                            </Button>
                        )}
                        <Button variant="outlined" onClick={() => setIsDialogOpen(false)} color="default">
                            {t('cancel')}
                        </Button>
                        <Button disabled={isLoading} onClick={handleSubmit}>
                            {isLoading && <Outlined.Loading className="animate-spin mr-1" />}
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
