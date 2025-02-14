import { Badge } from '@/components/bs-ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/bs-ui/tabs';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { getCurlCode, getPythonApiCode } from '@/constants';
import { TabsContext } from '@/contexts/tabsContext';
import { copyText } from '@/utils';
import { Check, Clipboard } from 'lucide-react';
import { useContext, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { JsonItem } from './ApiAccess';
import { Button } from '@/components/bs-ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';


const ApiAccessFlow = () => {
    const { t } = useTranslation()
    // const { flow, getTweak, tabsState } = useContext(TabsContext);
    // const curl_code = getCurlCode(flow, getTweak, tabsState);
    // const pythonCode = getPythonApiCode(flow, getTweak, tabsState);

    const { message } = useToast()
    const handleCopyLink = (e) => {
        copyText(e.target).then(() => {
            message({ variant: 'success', description: t('api.copySuccess') })
        })
    }

    const [isCopied, setIsCopied] = useState<Boolean>(false);
    const copyToClipboard = (code: string) => {
        setIsCopied(true);
        copyText(code).then(() => {
            setTimeout(() => {
                setIsCopied(false);
            }, 2000);
        })
    }

    const scrollToSection = (params) => {

    }

    return (
        <section className='max-w-[1600px] flex-grow'>
            <Card className="mb-8">
                <CardHeader>
                    <CardTitle>{t('api.apiRequestExample')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>/api/v2/workflow/invoke</span>
                    </h3>
                    {/* <p className='my-2'>{t('api.exampleCode')}：</p> */}
                    {/* <Tabs defaultValue="curl" className="w-full mb-[40px]">
                        <TabsList className="">
                            <TabsTrigger value="curl" className="">cURL</TabsTrigger>
                            <TabsTrigger value="python">Python API</TabsTrigger>
                        </TabsList>

                        <TabsContent value="curl" className='relative'>
                            <button
                                className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                                onClick={() => copyToClipboard('xxxx')}
                            >
                                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                            </button>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'bash'}
                                style={oneDark}
                            >
                                {'xxxx'}
                            </SyntaxHighlighter>
                        </TabsContent>
                        <TabsContent value="python" className='relative'>
                            <button
                                className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                                onClick={() => copyToClipboard('xxxxx')}
                            >
                                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                            </button>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'python'}
                                style={oneDark}
                            >
                                {'xxxx'}
                            </SyntaxHighlighter>
                        </TabsContent>
                    </Tabs> */}
                </CardContent>
            </Card>

            <Card className="mb-8">
                <CardHeader>
                    <CardTitle>请求参数</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.dataStructure')}</TableHead>
                                <TableHead className='w-[40%]'>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <JsonItem name="workflow_id" required type="string" desc={'工作流唯一ID'}></JsonItem>
                                    <JsonItem name="stream" type="boolean" desc={'是否流式'}>
                                        <p className='text-gray-500'>默认值: false</p>
                                    </JsonItem>
                                    <JsonItem name="input" type="object" desc={'用户输入'}>
                                        <p className='text-gray-500'>用户输入，在workflow是待输入状态时传入用户输入的内容</p>
                                    </JsonItem>
                                    <JsonItem name="message_id" type="string" desc={'消息唯一ID'}>
                                        <p className='text-gray-500'>用户输入时需要传消息ID</p>
                                    </JsonItem>
                                    <JsonItem name="session_id" type="string" desc={'一次调用的唯一ID'}>
                                        <p className='text-gray-500'>workflow运行期间唯一的标识，首次不用传后续传此参数。不传此参数默认是更新运行workflow</p>
                                    </JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "workflow_id": "string",
  "stream": true,
  "input": {},
  "message_id": "string",
  "session_id": "string"
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>


            <Card className="mb-8">
                <CardHeader>
                    <CardTitle>返回数据全字段说明</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.dataStructure')}</TableHead>
                                <TableHead className='w-[40%]'>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <JsonItem name="event" required type="str" desc="事件名称"></JsonItem>
                                    <JsonItem name="node_id" required type="str" desc="触发事件的节点ID"></JsonItem>
                                    <JsonItem name="message_id" required type="str" desc="消息在数据库中的唯一ID"></JsonItem>
                                    <JsonItem name="node_execution_id" required type="str" desc="执行此节点时的唯一ID"></JsonItem>
                                    <JsonItem name="input_schema" required type="Json" desc="需要用户输入的schema">
                                        <JsonItem line name="input_type" type="str" desc="输入类型" example="form_input" remark="输入方式"></JsonItem>
                                        <JsonItem line name="value" type="JsonArray" desc="需要用户输入的字段信息">
                                            <JsonItem line name="key" type="str" desc="字段的唯一key" example="category"></JsonItem>
                                            <JsonItem line name="type" type="str" desc="字段类型" example="select"></JsonItem>
                                            <JsonItem line name="value" type="str" desc="字段的默认值" example=""></JsonItem>
                                            <JsonItem line name="multiple" type="boolean" desc="是否支持多选" example="True"></JsonItem>
                                            <JsonItem line name="label" type="str" desc="字段的展示名称" example="请选择接下来要进行的操作"></JsonItem>
                                            <JsonItem line name="options" type="JsonArray" desc="下拉框类型的选项列表">
                                                <JsonItem line name="id" type="str" desc="选项的唯一ID" example="0b8a2fe9"></JsonItem>
                                                <JsonItem line name="text" type="str" desc="选项的文本" example="操作1"></JsonItem>
                                                <JsonItem line name="type" type="str" desc="选项类型" example=""></JsonItem>
                                            </JsonItem>
                                            <JsonItem line name="required" type="boolean" desc="是否必填" example="True"></JsonItem>
                                        </JsonItem>
                                    </JsonItem>
                                    <JsonItem name="output_schema" required type="Json" desc="输出schema">
                                        <JsonItem line name="message" type="str" desc="输出的内容"></JsonItem>
                                        <JsonItem line name="output_key" type="str" desc="输出内容对应的变量key" example="output"></JsonItem>
                                        <JsonItem line name="files" type="JsonArray" desc="文件列表">
                                            <JsonItem line name="path" type="str" desc="文件路径" example="http://minio:9000/xxx.png?aa=xxx"></JsonItem>
                                            <JsonItem line name="name" type="str" desc="文件名称" example="测试图片.png"></JsonItem>
                                        </JsonItem>
                                        <JsonItem line name="source_url" type="str" desc="溯源url" example=""></JsonItem>
                                    </JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "xxx",  # 事件名称
  "node_id": "input_xxxx",  # 触发事件的节点ID。结束事件是空值，用户输入时需要用到节点ID
  "message_id": "xxxxxxx",  # 消息在数据库中的唯一ID
  "node_execution_id": "xxxxx",  # 执行此节点时的唯一ID，因为一个节点可能循环多次执行，所以需要区分
  "input_schema": {  # 需要用户输入的schema，此字段不为空 则需要给用户渲染对应的输入UI
    "input_type": "form_input",  # 是什么类型的输入，dialogue_input：对话框形式的输入，
    # form_input：表单形式的输入；message_inline_input: message_inline_option
    "value": [  # 需要用户输入哪些字段信息，随着 input_type 类型不同，需要填写不同的字段
      {
        "key": "category",  # 字段的唯一key，拼接用户输入时，使用此key
        "type": "select",  # 字段类型，text：输入框；file：文件；select：下拉框
        "value": "",  # 字段的默认值
        "multiple": True,  # 是否支持多选
        "label": "请选择接下来要进行的操作",  # 字段的展示名称
        "options": [  # 下拉框类型的选项列表
          {
            "id": "0b8a2fe9",
            "text": "操作1",
            "type": ""
          },
          {
            "id": "eb5f4ade",
            "text": "操作2",
            "type": ""
          }
        ],  
        "required": True  # 是否必填
      }
    ]
  },
  "output_schema": {
    "message": "输出内容",  # 输出的内容
    "output_key": "output",  # 输出内容对应的变量key
    "files": [  # 文件列表，输出节点和报告节点可能会返回文件
      {
        "path": "http://minio:9000/xxx.png?aa=xxx",
        "name": "测试图片.png"
      }
    ],
    "source_url": "",  # 溯源url，需要自己拼接毕昇的前端地址。具体是否支持溯源请参考产品文档
  },
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>


                    <Popover>
                        <PopoverTrigger asChild>
                            <Button className="fixed top-20 right-10 z-10 size-11 rounded-full">导航</Button>
                        </PopoverTrigger>
                        <PopoverContent className="p-4 shadow-lg flex flex-col gap-2">
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-word">开场白事件数据示例</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-question">引导问题事件数据示例</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-primary mr-2'></span><a href="#guide-form">等待输入事件数据示例-表单形式</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-primary mr-2'></span><a href="#guide-dialog">等待输入事件数据示例-对话框形式</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-msg">输出事件数据示例</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-inputmsg">输出事件数据示例-需输入类型</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-selectmsg">输出事件数据示例-选择类型</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-stream">流式输出数据示例-输出中</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-red-400 mr-2'></span><a href="#guide-event">结束事件数据示例</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-codes">错误码说明</a></Badge>
                        </PopoverContent>
                    </Popover>
                    <h3 className='mt-8' id="guide-word">开场白事件数据示例</h3>
                    <p className='bisheng-label mt-2'>将output_schema中的message展示给用户，如有特殊展示可根据开场白事件来特殊处理</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "guide_word",  # 事件名称
  "node_id": "start_xxx",  # 执行节点ID，
  "node_execution_id": "xxxxxxxx",  # 执行此节点的唯一标识
  "output_schema": {  # output
    "message": "本工作流可以解决xxxx等问题"
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>

                    <h3 className='mt-8' id="guide-question">引导问题事件数据示例</h3>
                    <p className='bisheng-label mt-2'>可以在收到收到【输入事件-对话框形式】时，展示引导问题列表给用户选择</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "guide_question",
  "node_id": "start_xxx",
  "node_execution_id": "xxxxxxxx",
  "output_schema": {
    "message": [
      "引导问题1",
      "引导问题2"
    ]
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>


                    <h3 className='mt-8' id="guide-form">等待输入事件数据示例-表单形式</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>1. 解析input_schema.value中的表单元素，绘制表单给到用户</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "event": "input",
    "node_id": "input_xxxx",
    "node_execution_id": "xxxxx",
    "input_schema": {
        "input_type": "form_input",
        "value": [
            {
                "key": "text_input",
                "type": "text",
                "value": "文本输入类型",
                "label": "文本输入类型",
                "options": [],
                "required": true
            },
            {
                "key": "file",
                "type": "file",
                "value": "",
                "label": "文件类型的输入",
                "options": [],
                "required": true
            },
            {
                "key": "category",
                "type": "select",
                "value": "",
                "label": "下拉框类型",
                "required": true,
                "multiple": false,
                "options": [
                    {
                        "id": "0b8a2fe9",
                        "text": "选项1",
                        "type": ""
                    },
                    {
                        "id": "eb5f4ade",
                        "text": "选项2",
                        "type": ""
                    }
                ]
            }
        ]
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>2. 如果是文件类型，调用毕昇的文件上传接口（参考技能对外发布API）获取到文件的url</p>
                                    <p className='bisheng-label mt-2'>3. 用户处理完成后拼接用户输入为接口入参，再次调用API，示例如下</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "xxxxx",
    "input": {
        "input_xxx": {  # 事件里的节点ID
            # key是input_schme.value中元素的 key 以及对应要传入的值
            "text_input": "用户输入的内容",
            "file": ["minio://127.0.0.1:9000/xxxx"] # 用户上传文件获取到的文件url, 允许多选就是多个url
            "category": "选项2" # 将选项内容赋值给变量。当允许多选时，多个选项内容通过逗号分隔。
        }
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>


                    <h3 className='mt-8' id="guide-dialog">等待输入事件数据示例-对话框形式</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>1. 绘制对话框给到用户，让用户输入内容</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "event": "input",
    "node_id": "input_xxxx",
    "node_execution_id": "xxxxx",
    "input_schema": {
        "input_type": "dialog_input",
        "value": [
            {
                "key": "user_input",
                "type": "text"
            }
        ]
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>2. 接收到到用户输入后拼接接口的入参，再次调用API，入参示例如下</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "xxxxx",
    "input": {
        "input_xxx": {  # 事件里的节点ID
            # input_schme.value中元素的 key 以及对应要传入的值
            "user_input": "用户输入的内容"
        }
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>


                    <h3 className='mt-8' id="guide-msg">输出事件数据示例</h3>
                    <p className='bisheng-label mt-2'>1. 将output_schema中message展示给用户</p>
                    <p className='bisheng-label mt-2'>2. 如果files不为空则提供给用户下载按钮</p>
                    <p className='bisheng-label mt-2'>3. source_url是基于毕昇服务根路径，需要拼接上毕昇的访问地址</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "output_msg",
  "node_id": "output_xxx",
  "node_execution_id": "xxxxxxxxx",
  "output_schema": {
    "message": "输出内容",
    "output_key": "output",
    "files": [
      {
        "path": "http://minio:9000/xxx.png?aa=xxx",
        "name": "测试图片.png"
      }
    ],
    "source_url": ""
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>


                    <h3 className='mt-8' id="guide-inputmsg">输出事件数据示例-需输入类型</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>1. output_schema和输出事件的处理逻辑一样</p>
                                    <p className='bisheng-label mt-2'>2. 根据input_schema绘制输入框给到用户输出，input_schem.value.value为默认值</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "event": "output_with_input_msg",
    "node_id": "output_xxx",
    "node_execution_id": "xxxxxxxxx",
    "message_id": "xxxxx",
    "output_schema": {
        "message": "输出内容",
        "output_key": "output",
        "files": [
            {
                "path": "http://minio:9000/xxx.png?aa=xxx",
                "name": "测试图片.png"
            }
        ],
        "source_url": ""
    },
    "input_schema": {
        "input_type": "message_inline_input",
        "value": [
            {
                "key": "output_result",
                "type": "text",
                "value": "以下是AI生成的的草稿：XXXX"
            }
        ]
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>3. 接受到用户的输入后拼接接口的入参，再次调用API，示例如下</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "消息的唯一ID",
    "input": {
        "output_xxx": {  # 事件里的节点ID
            # key是input_schme.value中元素的key
            "output_result": "用户输入的内容"
        }
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>



                    <h3 className='mt-8' id="guide-selectmsg">输出事件数据示例-选择类型</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>1. output_schema和输出事件的处理逻辑一样</p>
                                    <p className='bisheng-label mt-2'>2. 根据input_schema绘制下拉框给到用户选择</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "event": "output_with_choose_msg",
    "node_id": "output_xxx",
    "node_execution_id": "xxxxxxxxx",
    "message_id": "xxxxx",
    "output_schema": {
        "message": "输出内容",
        "output_key": "output",
        "files": [
            {
                "path": "http://minio:9000/xxx.png?aa=xxx",
                "name": "测试图片.png"
            }
        ],
        "source_url": ""
    },
    "input_schema": {
        "input_type": "message_inline_option",
        "value": [
            {
                "key": "output_result",
                "type": "select",
                "value": "",
                "options": [
                    {
                        "id": "e2107f75",
                        "label": "选项1",
                        "value": ""
                    },
                    {
                        "id": "790c36f9",
                        "label": "选项2",
                        "value": ""
                    }
                ]
            }
        ]
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>3. 接受到用户的输入后拼接接口的入参，再次调用API，示例如下</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "xxxxxx",
    "input": {
        "output_xxx": {  # 事件里的节点ID
            # key是input_schme.value中元素的key
            "output_result": "e2107f75"  # 用户选择选项对应的id
        }
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>


                    <h3 className='mt-8' id='guide-stream'>流式输出数据示例-输出中</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>1. 根据 node_execution_id 和 output_schema.output_key 来确定流式内容是否属于同一条消息（节点批量运行模式下，共用同一个 node_execution_id，所以需要根据 output_key 来区分是否是不同的消息）。</p>
                                    <p className='bisheng-label mt-2'>2. 如果找到了对应的消息，则将message添加到对应的消息里</p>
                                    <p className='bisheng-label mt-2'>3. 如果未找到对应的消息，则开启一条新的消息，并将message和后续此消息的message添加到此消息里</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "stream_msg",
  "node_id": "llm_xxx",
  "node_execution_id": "xxxxxx",
  "status": "stream",
  "output_schema": {
    "message": "你",
    "reasoning_content": "",  # 深度思考的内容，message内容不为空代表深度思考结束
    "output_key": "output_1" # output_1 是节点中的输出变量名
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <p className='bisheng-label mt-2'>1. 根据node_execution_id和output_schema.output_key找到对应的消息</p>
                                    <p className='bisheng-label mt-2'>2. 中止对应消息的打字机效果，并将message内容覆盖之前流式的结果</p>
                                </TableCell>
                                <TableCell className='align-top'></TableCell>
                            </TableRow>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "stream_msg",
  "node_id": "llm_xxx",
  "node_execution_id": "xxxxxx",
  "status": "end",  # end表示流式事件结束了
  "output_schema": {
    "message": "你好，这是流式完成后最终的答案",
    "reasoning_content": "",  # 深度思考的内容，message内容不为空代表深度思考结束
    "output_key": "output_1",
    "source_url": "" # 具体是否支持溯源请参考产品文档
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>



                    <h3 className='mt-8' id="guide-event">结束事件数据示例</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.example')}</TableHead>
                                <TableHead className='w-[40%]'>样式预览</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full max-w-[40vw] overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "close",
  "unique_id": "xxxxxx",
  "status": "end",
  "output_schema": {
    "message": {
        "code": "500",
        "message": "报错内容"
    }# 如果为空表示工作流正常结束；如果不为空则表示执行出错，内容就是错误信息
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                                <TableCell className='align-top'>
                                    图略...
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>

                    <h3 className='mt-8' id="guide-codes">错误码说明</h3>
                    <p className='bisheng-label mt-2'>1. 判断message是否为空，为空则告知用户工作流运行结束</p>
                    <p className='bisheng-label mt-2'>2. 如果message不为空，则告知用户工作流运行失败，并把报错信息抛出给用户或者自行处理</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[100%]'>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`500: 服务端异常，查看后端日志解决
10527: 工作流等待用户输入超时
10528: 节点执行超过最大次数
10531: <节点名称>功能已升级，需删除后重新拖入。
10532: 工作流版本已升级，请联系创建者重新编排`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card >


        </section >

    );
};

export default ApiAccessFlow;
