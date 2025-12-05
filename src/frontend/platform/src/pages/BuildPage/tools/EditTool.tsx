import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"
import { Button } from "@/components/bs-ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog"
import { Input, Textarea } from "@/components/bs-ui/input"
import { Label } from "@/components/bs-ui/label"
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/bs-ui/popover"
import { RadioGroup, RadioGroupItem } from "@/components/bs-ui/radio"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "@/components/bs-ui/select"
import { Sheet, SheetContent, SheetFooter, SheetHeader, SheetTitle } from "@/components/bs-ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/bs-ui/table"
import { useToast } from "@/components/bs-ui/toast/use-toast"
import { QuestionTooltip } from "@/components/bs-ui/tooltip"
import { userContext } from "@/contexts/userContext"
import { createTool, deleteTool, downloadToolSchema, testToolApi, updateTool } from "@/controllers/API/tools"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { Plus } from "lucide-react"
import { forwardRef, useContext, useEffect, useImperativeHandle, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

interface TestDialogProps {
    tool: any;
    formState: any;
}

export const TestDialog = forwardRef<{
    open: (item, tool, formState) => void
}, TestDialogProps>((props: any, ref) => {
    const { t } = useTranslation()
    const [testShow, setTestShow] = useState(false)
    const [apiData, setApiData] = useState<any>({})
    const toolRef = useRef<any>({})

    const formRef = useRef<{
        values: Record<string, string>;
        rules: Record<string, boolean>;
        state?: any;
    }>({ values: {}, rules: {} });

    useImperativeHandle(ref, () => ({
        open: (item, tool, formState) => {
            toolRef.current = tool
            formRef.current.state = formState
            setResult('')
            setApiData(item)
            setTestShow(true)
            // fill form
            item.api_params.forEach(param => {
                formRef.current.values[param.name] = ''
                formRef.current.rules[param.name] = param.required
            });
        }
    }))
    // reset
    useEffect(() => {
        if (!testShow) {
            formRef.current.values = {}
            formRef.current.rules = {}
        }
    }, [testShow])

    const { message } = useToast()
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState('')
    const handleTest = async () => {
        // validation
        const errors = []
        Object.keys(formRef.current.values).forEach(key => {
            if (formRef.current.rules[key] && formRef.current.values[key] === '') {
                errors.push(key + t('report.isRequired'))
            }
        })
        if (errors.length > 0) {
            return message({
                description: errors,
                variant: 'warning'
            })
        }

        setLoading(true)

        const { server_host, children, auth_method, parameter_name } = toolRef.current
        const { apiKey, apiLocation, authMethod, authType, parameter } = formRef.current.state

        await captureAndAlertRequestErrorHoc(testToolApi({
            server_host,
            extra: children.find(el => el.name === apiData.name).extra,
            auth_method: authMethod === 'apikey' ? 1 : 0,
            auth_type: authType,
            api_key: apiKey,
            request_params: formRef.current.values,
            api_location: apiLocation || 'query',
            parameter_name: parameter || parameter_name
        }).then(setResult))
        setLoading(false)
    }

    return <Dialog open={testShow} onOpenChange={setTestShow}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>{apiData.name}</DialogTitle>
            </DialogHeader>
            {testShow && <div className="flex flex-col gap-8 py-6">
                <div className="max-h-[600px] overflow-y-auto scrollbar-hide">
                    <label htmlFor="name" className="bisheng-label">{t('test.parametersAndValues')}</label>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-[100px]">{t('test.parameter')}</TableHead>
                                <TableHead >{t('test.value')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {
                                apiData.api_params.map((param) =>
                                    <TableRow key={param.id}>
                                        <TableCell>{param.name}{param.required && <span className="text-red-500">*</span>}</TableCell>
                                        <TableCell>
                                            <Input onChange={(e) => {
                                                formRef.current.values[param.name] = e.target.value;
                                            }}></Input>
                                        </TableCell>
                                    </TableRow>
                                )
                            }
                            {
                                apiData.api_params.length === 0 && <TableRow>
                                    <TableCell colSpan={2}>None</TableCell>
                                </TableRow>
                            }
                        </TableBody>
                    </Table>
                </div>
                <Button onClick={handleTest} disabled={loading}>{t('test.test')}</Button>
                <div className="">
                    <label htmlFor="desc" className="bisheng-label">{t('test.result')}</label>
                    <Textarea id="desc" name="desc" value={result} placeholder={t('test.outResultPlaceholder')} readOnly className="mt-2" />
                </div>
            </div>}
        </DialogContent>
    </Dialog>
})

const formData = {
    toolName: "",
    schemaContent: `{
        "openapi": "3.1.0",
        "info": {
          "title": "Untitled",
          "description": "Your OpenAPI specification",
          "version": "v1.0.0"
        },
        "servers": [
          {
            "url": ""
          }
        ],
        "paths": {},
        "components": {
          "schemas": {}
        }
      }`,
    authType: "basic",
    apiKey: "",
    authMethod: "none",
    customHeader: "",
    apiLocation: "query",
    parameter: ""
}

const EditTool = forwardRef((props: any, ref) => {
    const [editShow, setShow] = useState(false)
    const setEditShow = (bln) => {
        if (!bln) {
            // init data when close
            setFormState({ ...formData })
            setTableData([])
        }
        setShow(bln)
    }
    const [delShow, setDelShow] = useState(false)

    const schemaUrl = useRef('')
    const [formState, setFormState] = useState({ ...formData });
    const fromDataRef = useRef<any>({}) // same as formState
    const { user } = useContext(userContext);
    const [isSelf, setIsSelf] = useState(false);

    const [tableData, setTableData] = useApiTableData()
    const [isWrite, setIsWrite] = useState(false)

    useImperativeHandle(ref, () => ({
        open: () => {
            setEditShow(true)
            setDelShow(false)
        }, edit: (tool) => {
            fromDataRef.current = tool
            setFormState({
                toolName: tool.name,
                schemaContent: tool.openapi_schema,
                authType: tool.auth_type,
                apiKey: tool.api_key,
                authMethod: tool.auth_method === 1 ? 'apikey' : 'none',
                customHeader: "",
                apiLocation: tool.api_location || "query",
                parameter: tool.parameter_name || ""
            })
            setIsWrite(tool.write)

            setIsSelf(tool.user_id === user.user_id);
            setEditShow(true)
            setDelShow(true)

            setTableData(tool.children)
        }
    }));

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormState(prevState => ({
            ...prevState,
            [name]: value
        }));
    };

    // sendRequest to backend to get Schema
    const handleImportSchema = () => {
        // http://192.168.106.120:3002/openapi-test.json
        captureAndAlertRequestErrorHoc(downloadToolSchema({ download_url: schemaUrl.current })).then(res => {
            schemaUrl.current = ''
            if (!res) return
            fromDataRef.current = { ...res, id: fromDataRef.current.id }
            const fetchedSchema = res.openapi_schema; // replace with the template
            setFormState(prevState => ({
                ...prevState,
                schemaContent: fetchedSchema,
                authMethod: res.auth_method === 1 ? 'apikey' : 'none',
                authType: res.auth_type,
                apiLocation: res.api_location,
                parameter: res.parameter_name
            }))

            setTableData(res.children)
        })
    };

    // set schemaContent
    const handleSelectTemplate = (key = '') => {
        if (!editShow) return

        const file_content = key ? Example[key] : formState.schemaContent
        file_content && captureAndAlertRequestErrorHoc(downloadToolSchema({ file_content })).then(res => {
            schemaUrl.current = ''
            if (!res) return
            fromDataRef.current = { ...res, id: fromDataRef.current.id }
            const fetchedSchema = res.openapi_schema; // replace with the template
            setFormState(prevState => ({
                ...prevState,
                schemaContent: fetchedSchema,
                authMethod: res.auth_method === 1 ? 'apikey' : 'none',
                authType: res.auth_type,
                apiLocation: res.api_location,
                parameter: res.parameter_name
            }));

            setTableData(res.children)
        })
    };

    const { message } = useToast()
    // save api
    const handleSave = () => {
        const errors = [];

        if (!formState.toolName) {
            errors.push(t('tools.toolNameCannotBeEmpty'));
        }
        if (!formState.schemaContent) {
            errors.push(t('tools.schemaCannotBeEmpty'));
        }
        if (formState.authMethod === "apikey") {
            if (!formState.apiKey?.trim()) {
                errors.push(t('tools.apiKeyCannotBeEmpty'));
            } else if (formState.apiKey.length > 1000) {
                errors.push(t('tools.apiKeyMaxLengthExceeded'));
            }

            if (formState.authType === 'custom') {
                if (!formState.parameter) {
                    errors.push(t('tools.parameterNameCannotBeEmpty'));
                } else if (formState.parameter.length > 1000) {
                    errors.push(t('tools.parameterNameMaxLengthExceeded'));
                }
            }
        }

        if (errors.length > 0) {
            return message({
                description: errors,
                variant: "warning"
            });
        }


        const fromData = fromDataRef.current
        // merge formState
        const data = {
            ...fromData,
            api_key: formState.apiKey || fromData.api_key,
            auth_method: formState.authMethod === 'apikey' ? 1 : 0,
            auth_type: formState.authType,
            name: formState.toolName,
            openapi_schema: formState.schemaContent,
            api_location: formState.apiLocation,
            parameter_name: formState.parameter
        }

        const methodApi = delShow ? updateTool : createTool
        captureAndAlertRequestErrorHoc(methodApi(data)).then(res => {
            if (!res) return
            // save
            setEditShow(false)
            props.onReload()
            message({
                description: t('skills.saveSuccessful'),
                variant: "success"
            })
        })
    };

    // del tool
    const handleDelete = () => {
        bsConfirm({
            title: t('prompt'),
            desc: t('skills.deleteSure'),
            onOk(next) {
                // api
                captureAndAlertRequestErrorHoc(deleteTool(fromDataRef.current.id)).then(res => {
                    if (res === false) return
                    props.onReload()
                    setEditShow(false)
                    next()
                })
            }
        })
    }

    // test
    const testDialogRef = useRef(null)
    const handleTest = (obj) => {
        testDialogRef.current.open(obj)
    }
    const { t } = useTranslation()

    return <div>
        <Sheet open={editShow} onOpenChange={setEditShow}>
            <SheetContent className="w-[800px] sm:max-w-[800px] p-4 bg-background-login">
                <SheetHeader>
                    <SheetTitle>{delShow ? t('edit') : t('create')}{t('tools.createCustomTool')}</SheetTitle>
                </SheetHeader>
                <div className="mt-4 overflow-y-auto h-screen pb-40">
                    {/* name */}
                    <label htmlFor="open" className="px-6">{t('tools.name')}</label>
                    <div className="px-6 mb-4" >
                        <Input
                            id="toolName"
                            name="toolName"
                            className="mt-2"
                            placeholder={t('tools.enterToolName')}
                            value={formState.toolName}
                            onChange={handleInputChange}
                        />
                    </div>
                    {/* schema */}
                    <div className="px-6 flex items-center justify-between">
                        <label htmlFor="open">OpenAPI Schema</label>
                        <div className="flex gap-2">
                            <Popover>
                                <PopoverTrigger asChild>
                                    <Button variant="outline" className="dark:bg-[#282828]"><Plus /> {t('tools.importFromUrl')}</Button>
                                </PopoverTrigger>
                                <PopoverContent className="w-80" align="end">
                                    <div className="flex items-center gap-4">
                                        <Input
                                            id="schemaUrl"
                                            name="schemaUrl"
                                            placeholder="https://"
                                            onChange={(e) => schemaUrl.current = e.target.value}
                                        />
                                        <PopoverClose>
                                            <Button size="sm" className="w-16" onClick={handleImportSchema}>{t('skills.import')}</Button>
                                        </PopoverClose>
                                    </div>
                                </PopoverContent>
                            </Popover>
                            <Select value="1" onValueChange={(k) => handleSelectTemplate(k)}>
                                <SelectTrigger >
                                    <span>{t('tools.examples')}</span>
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectGroup>
                                        <SelectItem value="json">{t('tools.weatherJson')}</SelectItem>
                                        <SelectItem value="yaml">{t('tools.petShopYaml')}</SelectItem>
                                    </SelectGroup>
                                </SelectContent>
                            </Select>
                        </div>
                    </div>
                    <div className="px-6 mb-4" >
                        <Textarea
                            id="schemaContent"
                            name="schemaContent"
                            placeholder={t('tools.enterOpenAPISchema')}
                            className="mt-2 min-h-52"
                            value={formState.schemaContent}
                            onChange={handleInputChange}
                            onBlur={() => handleSelectTemplate()}
                        />
                    </div>
                    <label htmlFor="open" className="px-6">{t('tools.authenticationType')}</label>
                    <div className="px-6">
                        <div className="px-6 mb-4" >
                            <label htmlFor="open" className="bisheng-label">{t('tools.authType')}</label>
                            <RadioGroup
                                id="authMethod"
                                name="authMethod"
                                value={formState.authMethod}
                                className="flex mt-2 gap-4"
                                onValueChange={(value) => setFormState(prevState => ({ ...prevState, authMethod: value }))}
                            >
                                <div className="flex items-center space-x-2">
                                    <RadioGroupItem value="none" id="r1" />
                                    <Label htmlFor="r1">{t('tools.none')}</Label>
                                </div>
                                <div className="flex items-center space-x-2">
                                    <RadioGroupItem value="apikey" id="r2" />
                                    <Label htmlFor="r2">{t('tools.apiKey')}</Label>
                                </div>
                            </RadioGroup>
                        </div>
                        {formState.authMethod === "apikey" && (<>
                            <div className="px-6 mb-4" >
                                <Label htmlFor="open" className="bisheng-label flex items-center gap-1">
                                    {t('tools.authTypeLabel')}
                                    <QuestionTooltip content={<div>
                                        <p>{t('tools.basicBearerDescription')}</p>
                                        <p>{t('tools.customDescription')}</p>
                                    </div>} />
                                </Label>
                                <RadioGroup
                                    id="authType"
                                    name="authType"
                                    value={formState.authType}
                                    className="flex mt-2 gap-4"
                                    onValueChange={(value) => setFormState(prevState => ({ ...prevState, authType: value }))}
                                >
                                    <div className="flex items-center space-x-2">
                                        <RadioGroupItem value="basic" id="r4" />
                                        <Label htmlFor="r4">{t('tools.basic')}</Label>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <RadioGroupItem value="bearer" id="r5" />
                                        <Label htmlFor="r5">{t('tools.bearer')}</Label>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <RadioGroupItem value="custom" id="r6" />
                                        <Label htmlFor="r6">{t('tools.custom')}</Label>
                                    </div>
                                </RadioGroup>
                            </div>
                            {formState.authType === "custom" && <>
                                <div className="px-6 mb-4" >
                                    <Label htmlFor="apiLocation" className="bisheng-label flex items-center gap-1">
                                        {t('tools.apiLocationLabel')}
                                        <QuestionTooltip content={<div>
                                            <p>{t('tools.headerDescription')}</p>
                                            <p>{t('tools.queryDescription')}</p>
                                        </div>} />
                                    </Label>
                                    <RadioGroup
                                        id="apiLocation"
                                        name="apiLocation"
                                        value={formState.apiLocation}
                                        className="flex mt-2 gap-4"
                                        onValueChange={(value) => setFormState(prevState => ({
                                            ...prevState, apiLocation: value
                                        }))}
                                    >
                                        <div className="flex items-center space-x-2">
                                            <RadioGroupItem value="header" id="r7" />
                                            <Label htmlFor="r7">{t('tools.header')}</Label>
                                        </div>
                                        <div className="flex items-center space-x-2">
                                            <RadioGroupItem value="query" id="r8" />
                                            <Label htmlFor="r8">{t('tools.query')}</Label>
                                        </div>
                                    </RadioGroup>
                                </div>
                                <div className="px-6 mb-4">
                                    <Label className="bisheng-label" htmlFor="parameter">
                                        <span className="text-red-500">*</span> {t('tools.parameterName')}
                                    </Label>
                                    <Input
                                        id="parameter"
                                        name="parameter"
                                        className="mt-2"
                                        placeholder={t('tools.parameterPlaceholder')}
                                        value={formState.parameter}
                                        onChange={handleInputChange}
                                    />
                                </div>
                            </>}
                            <div className="px-6 mb-4">
                                <Label className="bisheng-label" htmlFor="apiKey">
                                    <span className="text-red-500">*</span> {t('tools.apiKeyLabel')}
                                </Label>
                                <Input
                                    id="apiKey"
                                    name="apiKey"
                                    className="mt-2"
                                    placeholder={t('tools.apiKeyPlaceholder')}
                                    value={formState.apiKey}
                                    onChange={handleInputChange}
                                />
                            </div>
                        </>)}
                    </div>
                    <label htmlFor="open" className="px-6">{t('tools.availableTools')}</label>
                    <div className="px-6 mb-4" >
                        <Table>
                            <TableHeader>
                                <TableRow>
                                    <TableHead className="w-[100px]">{t('tools.name')}</TableHead>
                                    <TableHead >{t('tools.description')}</TableHead>
                                    <TableHead >{t('tools.method')}</TableHead>
                                    <TableHead >{t('tools.path')}</TableHead>
                                    <TableHead >{t('operations')}</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {
                                    tableData.length ? tableData.map((item, index) =>
                                        <TableRow key={index}>
                                            <TableCell>{item.name}</TableCell>
                                            <TableCell>{item.desc}</TableCell>
                                            <TableCell>{item.extra.method}</TableCell>
                                            <TableCell>{item.extra.path}</TableCell>
                                            <TableCell>
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    className="dark:bg-[#666]"
                                                    onClick={() => {
                                                        testDialogRef.current.open(item, fromDataRef.current, formState)
                                                    }
                                                    }
                                                >{t('test.test')}</Button>
                                            </TableCell>
                                        </TableRow>
                                    ) :
                                        <TableRow>
                                            <TableCell colSpan={5}>{t('tools.none')}</TableCell>
                                        </TableRow>
                                }
                            </TableBody>
                        </Table>
                    </div>
                </div>
                <label htmlFor="open" className="px-6">{t('tools.authenticationType')}</label>
                <div className="px-6">
                    <div className="px-6 mb-4" >
                        <label htmlFor="open" className="bisheng-label">{t('tools.authType')}</label>
                        <RadioGroup
                            id="authMethod"
                            name="authMethod"
                            defaultValue="none"
                            className="flex mt-2 gap-4"
                            onValueChange={(value) => setFormState(prevState => ({ ...prevState, authMethod: value }))}
                        >
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="none" id="r1" />
                                <Label htmlFor="r1">{t('tools.none')}</Label>
                            </div>
                            <div className="flex items-center space-x-2">
                                <RadioGroupItem value="apikey" id="r2" />
                                <Label htmlFor="r2">{t('tools.apiKey')}</Label>
                            </div>
                        </RadioGroup>
                    </div>
                    {formState.authMethod === "apikey" && (
                        <div className="px-6 mb-4">
                            <label htmlFor="apiKey">{t('tools.apiKey')}</label>
                            <Input
                                id="apiKey"
                                name="apiKey"
                                className="mt-2"
                                value={formState.apiKey}
                                onChange={handleInputChange}
                            />
                        </div>
                    )}
                </div>
                <SheetFooter className="absolute bottom-0 right-0 w-full px-6 py-4">
                    {delShow && (user.role === 'admin' || isSelf || isWrite) && (
                        <Button
                            size="sm"
                            variant="destructive"
                            className="absolute left-6"
                            onClick={handleDelete}
                        >{t('tools.delete')}</Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => setEditShow(false)}>{t('tools.cancel')}</Button>
                    <Button size="sm" className="text-[white]" onClick={handleSave}>{t('tools.save')}</Button>
                </SheetFooter>
            </SheetContent>
        </Sheet >
        {/* test dialog */}
        <TestDialog ref={testDialogRef} />
    </div>
})

export default EditTool

const useApiTableData = () => {
    const [tableData, setTableData] = useState([])

    const setData = (objs) => {
        const newObjs = objs.map(obj => {
            return {
                ...obj,
                extra: JSON.parse(obj.extra)
            }
        })

        setTableData(newObjs)
    }

    return [
        tableData,
        setData
    ] as const
}


// 示例
const Example = {
    'json': `{
        "openapi": "3.1.0",
        "info": {
          "title": "Get weather data",
          "description": "Retrieves current weather data for a location.",
          "version": "v1.0.0"
        },
        "servers": [
          {
            "url": "https://weather.example.com"
          }
        ],
        "paths": {
          "/location": {
            "get": {
              "summary": "",
              "description": "Get temperature for a specific location",
              "operationId": "GetCurrentWeather",
              "parameters": [
                {
                  "name": "location",
                  "in": "query",
                  "description": "The city and state to retrieve the weather for",
                  "required": true,
                  "schema": {
                    "type": "string"
                  }
                }
              ],
              "deprecated": false
            }
          }
        },
        "components": {
          "schemas": {}
        }
      }`,
    'yaml': `# Taken from https://github.com/OAI/OpenAPI-Specification/blob/main/examples/v3.0/petstore.yaml

    openapi: "3.0.0"
    info:
      version: 1.0.0
      title: Swagger Petstore
      license:
        name: MIT
    servers:
      - url: https://petstore.swagger.io/v1
    paths:
      /pets:
        get:
          summary: List all pets
          operationId: listPets
          tags:
            - pets
          parameters:
            - name: limit
              in: query
              description: How many items to return at one time (max 100)
              required: false
              schema:
                type: integer
                maximum: 100
                format: int32
          responses:
            '200':
              description: A paged array of pets
              headers:
                x-next:
                  description: A link to the next page of responses
                  schema:
                    type: string
              content:
                application/json:    
                  schema:
                    $ref: "#/components/schemas/Pets"
            default:
              description: unexpected error
              content:
                application/json:
                  schema:
                    $ref: "#/components/schemas/Error"
        post:
          summary: Create a pet
          operationId: createPets
          tags:
            - pets
          responses:
            '201':
              description: Null response
            default:
              description: unexpected error
              content:
                application/json:
                  schema:
                    $ref: "#/components/schemas/Error"
      /pets/{petId}:
        get:
          summary: Info for a specific pet
          operationId: showPetById
          tags:
            - pets
          parameters:
            - name: petId
              in: path
              required: true
              description: The id of the pet to retrieve
              schema:
                type: string
          responses:
            '200':
              description: Expected response to a valid request
              content:
                application/json:
                  schema:
                    $ref: "#/components/schemas/Pet"
            default:
              description: unexpected error
              content:
                application/json:
                  schema:
                    $ref: "#/components/schemas/Error"
    components:
      schemas:
        Pet:
          type: object
          required:
            - id
            - name
          properties:
            id:
              type: integer
              format: int64
            name:
              type: string
            tag:
              type: string
        Pets:
          type: array
          maxItems: 100
          items:
            $ref: "#/components/schemas/Pet"
        Error:
          type: object
          required:
            - code
            - message
          properties:
            code:
              type: integer
              format: int32
            message:
              type: string`,
}