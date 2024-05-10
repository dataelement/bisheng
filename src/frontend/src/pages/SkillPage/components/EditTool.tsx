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
import { createTool, deleteTool, downloadToolSchema, updateTool } from "@/controllers/API/tools"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { PlusIcon } from "@radix-ui/react-icons"
import { forwardRef, useImperativeHandle, useRef, useState } from "react"
import { useTranslation } from "react-i18next"

const TestDialog = forwardRef((props: any, ref) => {
    const [testShow, setTestShow] = useState(false)
    useImperativeHandle(ref, () => ({
        open: (item) => {
            setTestShow(true)
        }
    }))

    return <Dialog open={testShow} onOpenChange={setTestShow}>
        <DialogContent className="sm:max-w-[625px]">
            <DialogHeader>
                <DialogTitle>测试【名称】</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-8 py-6">
                <div className="">
                    <label htmlFor="name" className="bisheng-label">参数和值</label>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className="w-[100px]">参数</TableHead>
                                <TableHead >值</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {
                                new Array(2).fill(0).map((item, index) =>
                                    <TableRow key={index}>
                                        <TableCell>woeid</TableCell>
                                        <TableCell>
                                            <Input></Input>
                                        </TableCell>
                                    </TableRow>
                                )
                            }
                        </TableBody>
                    </Table>
                </div>
                <Button>测试</Button>
                <div className="">
                    <label htmlFor="desc" className="bisheng-label">测试结果</label>
                    <Textarea id="desc" name="desc" placeholder="点击按钮，输出结果" readOnly className="mt-2" />
                </div>
            </div>
        </DialogContent>
    </Dialog>
})

const formData = {
    toolName: "",
    schemaContent: "",
    authType: "basic",
    apiKey: "",
    authMethod: "none",
    customHeader: ""
}

const EditTool = forwardRef((props: any, ref) => {
    const [editShow, setShow] = useState(false)
    const setEditShow = (bln) => {
        if (!bln) {
            // 关闭弹窗初始化数据
            setFormState({ ...formData })
            setTableData([])
        }
        setShow(bln)
    }
    const [delShow, setDelShow] = useState(false)

    const schemaUrl = useRef('')
    const [formState, setFormState] = useState({ ...formData });
    const fromDataRef = useRef<any>({})

    // 表格数据（api接口列表）
    const [tableData, setTableData] = useApiTableData()

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
                customHeader: ""
            })
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

    // 发送请求给后端获取Schema
    const handleImportSchema = () => {
        // http://192.168.106.120:3002/openapi-test.json
        captureAndAlertRequestErrorHoc(downloadToolSchema({ download_url: schemaUrl.current })).then(res => {
            schemaUrl.current = ''
            if (!res) return
            fromDataRef.current = res
            const fetchedSchema = res.openapi_schema; // 替换为后端返回的Schema
            setFormState(prevState => ({
                ...prevState,
                schemaContent: fetchedSchema
            }))

            setTableData(res.children)
        })
    };

    // 根据模板设置Schema内容
    const handleSelectTemplate = (key = '') => {
        const file_content = key ? Example[key] : formState.schemaContent
        file_content && captureAndAlertRequestErrorHoc(downloadToolSchema({ file_content })).then(res => {
            schemaUrl.current = ''
            if (!res) return
            fromDataRef.current = res
            const fetchedSchema = res.openapi_schema; // 替换为后端返回的Schema
            setFormState(prevState => ({
                ...prevState,
                schemaContent: fetchedSchema
            }));

            setTableData(res.children)
        })
    };

    const { message } = useToast()
    // 发送数据给后端保存
    const handleSave = () => {
        // console.log("保存数据:", formState, fromDataRef.current);
        const fromData = fromDataRef.current
        // 参数合并
        const data = {
            ...fromData,
            api_key: formState.apiKey || fromData.api_key,
            auth_method: formState.authMethod === 'apikey' ? 1 : 0,
            auth_type: formState.authType,
            name: formState.toolName || fromData.name
        }

        const methodApi = delShow ? updateTool : createTool
        captureAndAlertRequestErrorHoc(methodApi(data)).then(res => {
            if (!res) return
            // 保存成功
            setEditShow(false)
            props.onReload()
            message({
                description: t('skills.saveSuccessful'),
                variant: "success"
            })
        })
    };

    // 删除工具
    const handleDelete = () => {
        bsConfirm({
            title: t('prompt'),
            desc: t('skills,deleteSure'),
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
            <SheetContent className="w-[800px] sm:max-w-[800px] p-4">
                <SheetHeader>
                    <SheetTitle>{t('tools.createCustomTool')}</SheetTitle>
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
                                    <Button variant="outline"><PlusIcon /> {t('tools.importFromUrl')}</Button>
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
                                            <Button size="sm" className="w-16" onClick={handleImportSchema}>{t('tools.import')}</Button>
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
                                defaultValue={formState.authMethod}
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
                            <div className="px-6 mb-4">
                                <label htmlFor="apiKey">API Key</label>
                                <Input
                                    id="apiKey"
                                    name="apiKey"
                                    className="mt-2"
                                    value={formState.apiKey}
                                    onChange={handleInputChange}
                                />
                            </div>

                            <div className="px-6 mb-4" >
                                <label htmlFor="open" className="bisheng-label">Auth Type</label>
                                <RadioGroup
                                    id="authType"
                                    name="authType"
                                    defaultValue={formState.authType}
                                    className="flex mt-2 gap-4"
                                    onValueChange={(value) => setFormState(prevState => ({ ...prevState, authType: value }))}
                                >
                                    <div className="flex items-center space-x-2">
                                        <RadioGroupItem value="basic" id="r4" />
                                        <Label htmlFor="r4">Basic</Label>
                                    </div>
                                    <div className="flex items-center space-x-2">
                                        <RadioGroupItem value="bearer" id="r5" />
                                        <Label htmlFor="r5">Bearer</Label>
                                    </div>
                                    {/* <div className="flex items-center space-x-2">
                                    <RadioGroupItem value="custom" id="r6" />
                                    <Label htmlFor="r6">Custom</Label>
                                </div> */}
                                </RadioGroup>
                            </div>
                        </>)}
                        {/* {formState.authMethod === "custom" && (
                            <div className="px-6 mb-4">
                                <label htmlFor="customHeader">Custom Header Name</label>
                                <Input
                                    id="customHeader"
                                    name="customHeader"
                                    className="mt-2"
                                    value={formState.customHeader}
                                    onChange={handleInputChange}
                                />
                            </div>
                        )} */}
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
                                    {/* <TableHead >操作</TableHead> */}
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
                                            {/* <TableCell>
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    onClick={() => testDialogRef.current.open(item)}
                                                >测试</Button>
                                            </TableCell> */}
                                        </TableRow>
                                    ) :
                                        <TableRow>
                                            <TableCell colSpan={4}>{t('tools.none')}</TableCell>
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
                <SheetFooter className="absolute bottom-0 right-0 w-full px-6 py-4 bg-[#fff]">
                    {delShow && <Button
                        size="sm"
                        variant="destructive"
                        className="absolute left-6"
                        onClick={handleDelete}
                    >{t('tools.delete')}</Button>}
                    <Button size="sm" variant="outline" onClick={() => setEditShow(false)}>{t('tools.cancel')}</Button>
                    <Button size="sm" onClick={handleSave}>{t('tools.save')}</Button>
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