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
import { useParams } from 'react-router-dom';


const ApiAccessFlow = () => {
    const { t } = useTranslation()
    const { id } = useParams()
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

    const firstCode = `import requests
import json

url = "${location.origin}/api/v2/workflow/invoke"

payload = json.dumps({
   "workflow_id": "${id}",
   "stream": False, # 为空或者不传，都会请求流式返回工作流事件。本示例为了直观展示返回结果，所以改
为非流式请求，真实场景下为了用户体验建议请求流式。
})

headers = {
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)# 输出工作流的响应`


    return (
        <section className='max-w-[1600px] flex-grow'>
            <Card className="mb-8">
                <CardHeader>
                    <CardTitle id="guide-t1">接口基本信息</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className='py-2' id="guide-word">1. 工作流请求执行接口</h3>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>{location.origin}/api/v2/workflow/invoke</span>
                    </h3>
                    <h3 className='py-2' id="guide-word">2. 工作流停止运行接口</h3>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>{location.origin}/api/v2/workflow/stop</span>
                    </h3>
                </CardContent>
            </Card>

            <Card className="mb-8">
                <CardHeader>
                    <CardTitle id="guide-t2">整体调用流程</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className='w-[700px] mx-auto'><img src={`${__APP_ENV__.BASE_URL}/assets/api/flow.png`} className='size-full' alt="" /></div>
                    <p className='bisheng-label pb-2'>如时序图所示，在对接工作流 API 时，一般会经历以下步骤：</p>
                    <p className="bisheng-label pb-2"><span className="font-semibold">1. 第一步：</span>发起工作流执行。通过/invoke 接口让工作流从开始节点开始运行：</p>
                    <div className='relative  max-w-[80vw]'>
                        <button
                            className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                            onClick={() => copyToClipboard(firstCode)}
                        >
                            {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                        </button>
                        <SyntaxHighlighter
                            className="w-full overflow-auto custom-scroll text-sm"
                            language={'json'}
                            style={oneDark}
                        >
                            {firstCode}
                        </SyntaxHighlighter>
                    </div>
                    <p className="bisheng-label py-2"><span className="font-semibold">2. 第二步：</span>获取并解析工作流返回的事件。（一定要保留 session_id 等上下文信息，以便后续继续请求）</p>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll text-sm"
                        language={'json'}
                        style={oneDark}
                    >
                        {`{
    "status_code": 200,
    "status_message": "SUCCESS",
    "data": {
        "session_id": "d4347ab8e8cd48c48ac9920dbb5a9b35_async_task_id",
        "events": [
            {
                "event": "guide_word",
                "message_id": null,
                "status": "end",
                "node_id": "start_553b9",
                "node_execution_id": "ce9a73b376c647159b1b2de1806129cf",
                "output_schema": {
                    "message": "您好，请问想聊些什么呢？",
                    "reasoning_content": null,
                    "output_key": null,
                    "files": null,
                    "source_url": null,
                    "extra": null
                },
                "input_schema": null
            },
            {
                "event": "input",
                "message_id": "387216",
                "status": "end",
                "node_id": "input_2775b",
                "node_execution_id": null,
                "output_schema": null,
                "input_schema": {
                    "input_type": "dialog_input",
                    "value": [
                        {
                            "key": "user_input",
                            "type": "text",
                            "value": null,
                            "label": null,
                            "multiple": false,
                            "required": true,
                            "options": null
                        }
                    ]
                }
            }
        ]
    }
}`}
                    </SyntaxHighlighter>
                    <div className="mb-6">
                        <p className="bisheng-label py-2"><span className="font-semibold">3. 第三步：</span>根据事件类型渲染前端，并收集用户输入。</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>如果事件是 <strong>普通输出</strong>（比如 <code className="bg-gray-200 py-1 rounded">event="output_msg"</code>），则直接展示内容。</li>
                            <li className='mt-2 leading-6'>如果事件是 <strong>等待用户交互输入</strong>（比如 <code className="bg-gray-200 p-1 rounded">event="input"</code> 或 <code className="bg-gray-200 p-1 rounded">event="output_with_input_msg"</code> 或 <code class="bg-gray-200 p-1 rounded">event="output_with_choose_msg"</code>），则需要渲染对应的界面（对话框、表单等）。</li>
                        </ul>
                    </div>
                    <p className="bisheng-label py-2"><span className="font-semibold">4. 第四步：</span>带着用户输入再次调用 <code className="bg-gray-200 p-1 rounded">/invoke</code> 接口。</p>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll text-sm"
                        language={'json'}
                        style={oneDark}
                    >
                        {`payload = json.dumps({
    "workflow_id": "7481368b-dd1c-43ef-a254-dce219ee53e8",
    "stream": False,  # 启用流式传输
    "input": {"input_2775b": {  # 事件里的节点ID
        "user_input": "贵州茅台股价情况"  # 使用从文件中读取的文本
    }},
    "message_id": "387216",
    "session_id": "1fc60fe0edb44219bbef5f8870dd4639_async_task_id"
})
`}
                    </SyntaxHighlighter>
                    <p className="bisheng-label py-2"><span className="font-semibold">5. 第五步：</span>继续获取并解析返回的事件……直到返回 <code className="bg-gray-100 p-1 rounded">close</code> 事件（非必须）结束工作流运行，也可调用 <code className="bg-gray-100 p-1 rounded">POST /workflow/stop</code> 接口手动终止工作流。</p>
                </CardContent>
            </Card>

            {/* <Card className="mb-8">
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
            </Card> */}


            <Card className="mb-8">
                <CardHeader>
                    <CardTitle id="guide-t3">返回事件类型与处理方式</CardTitle>
                </CardHeader>
                <CardContent className='relative'>
                    <p className='bisheng-label py-2'>工作流返回的响应 JSON 通常包含一个或多个事件对象（数组形式），每个事件的字段可能不一样，以下枚举全部字段情况（非真实值，仅供参考）：</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='min-w-[600px]'>{t('api.dataStructure')}</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
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
                                        <JsonItem line name="reasoning_content" type="str" desc="推理模型的思考过程内容"></JsonItem>
                                        <JsonItem line name="output_key" type="str" desc="输出内容对应的变量key" example="output"></JsonItem>
                                        <JsonItem line name="files" type="JsonArray" desc="文件列表">
                                            <JsonItem line name="path" type="str" desc="文件路径" example="http://minio:9000/xxx.png?aa=xxx"></JsonItem>
                                            <JsonItem line name="name" type="str" desc="文件名称" example="测试图片.png"></JsonItem>
                                        </JsonItem>
                                        <JsonItem line name="source_url" type="str" desc="溯源url" example=""></JsonItem>
                                        <JsonItem line name="extra" type="str" desc="QA知识库溯源内容" example='{"qa": "本答案来源于已有问答库: QA 知识库", "url": null}'></JsonItem>
                                    </JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "guide_word",  
  # 表示当前事件类型，例如 guide_word（开场白事件）、guide_question（引导问题事件）、input（等待输入事件）、output_msg（输出事件）、close（结束事件）……
  
  "node_id": "input_xxxx",  
  # 当前事件是由哪个工作流节点触发的。对于需要输入的事件（如 event="input"），必须在后续请求中携带此 node_id ，以告诉后端对哪个节点进行输入。 
  
  "message_id": "xxxxxxx",  
  # 消息在数据库中的唯一ID
  
  "node_execution_id": "xxxxx",  
  # 此节点时的唯一执行ID。由于同一个节点可能在运行过程中执行多次，该字段用于唯一标识某次节点执行，在流式输出事件中，需要用它来区分多条流式消息。
  
  "input_schema": {   # input_schema ：需要用户输入的schema，此字段不为空 则需要给用户渲染对应的输入UI
    "input_type": "form_input",  
    # input_type：输入类型。取值范围包括：1) form_input：表单形式的输入；2) dialogue_input：对话框形式的用户输入；3)message_inline_input：需要用户输入的消息;4)需要用户选择的消息。
    
    "value": [  # 需要用户输入哪些字段信息，随着 input_type 类型不同，需要填写不同的字段
      {
        "key": "category",  # 字段的唯一key，拼接用户输入时，使用此key
        "type": "select",  # 字段类型，1）text：文本输入框；2）file：文件上传；3）select：下拉框
        "value": "",  # 字段的默认值
        "multiple": True,  # type=select时，通过此字段指定下拉框是否可多选
        "label": "请选择接下来要进行的操作",  # 字段的前端展示名称
        "options": [  # 如果 type=select，则在这里列出可选值的 id、text 等信息
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
  "output_schema": {# 需要在用户会话界面展示的数据
    "message": "输出内容",  # 直接展示给用户的文本输出内容。
    "reasoning_content"："思考过程内容" # R1 等推理模型的思考过程内容
    "output_key": "output",  # 输出内容对应的变量标识
    "files": [  # 文件文件列表，每个文件包含 path 和 name 信息。前端可据此展示文件列表，允许用户下载或者预览。
      {
        "path": "http://minio:9000/xxx.png?aa=xxx",
        "name": "测试图片.png"
      }
    ],
    "source_url": "",  # 知识库问答溯源页面地址，需要自己拼接毕昇的前端地址。具体是否支持溯源请参考产品文档
    "extra": "{\"qa\": \"本答案来源于已有问答库: QA 知识库\", \"url\": null}"  # QA知识库溯源内容
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
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#000] mr-2'></span><a href="#guide-t1">接口基本信息</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#000] mr-2'></span><a href="#guide-t2">整体调用流程</a></Badge>
                            <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#000] mr-2'></span><a href="#guide-t3">返回事件类型与处理方式</a></Badge>
                            <div className='pl-4 flex flex-col gap-2'>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-2">引导问题事件</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-primary mr-2'></span><a href="#guide-3">等待输入事件-对话框形式</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-primary mr-2'></span><a href="#guide-5">等待输入事件-表单形式</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-6">输出事件</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-7">输出事件-需输入类型</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-8">输出事件-选择类型</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-9">流式输出事件-输出中</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-10">流式输出事件-结束</a></Badge>
                                <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-red-400 mr-2'></span><a href="#guide-11">结束事件</a></Badge>
                            </div>
                        </PopoverContent>
                    </Popover>
                    <h3 className='mt-8' id="guide-1">开场白事件</h3>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'><img src={`${__APP_ENV__.BASE_URL}/assets/api/chat1.png`} className='size-full' alt="" /></div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "event": "guide_word",  # 开场白事件
  "node_id": "start_xxx",  # 节点ID，
  "node_execution_id": "xxxxxxxx",  # 执行此节点的唯一标识
  "output_schema": {  # output
    "message": "本工作流可以解决xxxx等问题"
  }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                    <p className='bisheng-label mt-2'>处理逻辑：将 output_schema.message 展示给用户即可。</p>

                    <h3 className='mt-8' id="guide-2">引导问题事件</h3>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'><img src={`${__APP_ENV__.BASE_URL}/assets/api/chat2.png`} className='size-full' alt="" /></div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
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
                            </TableRow>
                        </TableBody>
                    </Table>
                    <p className='bisheng-label mt-2'>处理逻辑：向用户展示引导问题列表，将用户选中的问题作为输入，继续调用工作流接口。</p>


                    <h3 className='mt-8' id="guide-3">等待输入事件-对话框形式</h3>
                    <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                        <p className='bisheng-label'>当工作流返回 <span className="bg-orange-50">event="input"</span> 且 <span className="bg-orange-50">input_type="dialog_input"</span>时，表示后端希望前端在对话框中接收用户输入以及上传文件（非必须）。</p>
                        <p className='bisheng-label mt-2'>下一次请求 <span className="bg-orange-50">/invoke</span> 接口必带的关键字段是 <span className="bg-orange-50">node_id</span>,<span className="bg-orange-50">message_id</span>,<span className="bg-orange-50">session_id</span> 以及对话框输入。</p>
                    </div>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'><img src={`${__APP_ENV__.BASE_URL}/assets/api/chat3.png`} className='size-full' alt="" /></div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "event": "input",# 等待输入事件
    "node_id": "input_xxxx",
    "node_execution_id": "xxxxx",
    "input_schema": {
        "input_type": "dialog_input",# 对话框形式
        "value": [
            {
                "key": "user_input",
                "type": "text"
            },
            {
                "key": "dialog_files_content", # 需要用户上传文件
                "type": "dialog_file"
            },
            {
                "key": "dialog_file_accept",  # 上传文件的格式限制
                "type": "dialog_file_accept",
                "value": "all"  # 允许的文件类型
            }
        ]
    }
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑：</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>绘制对话框，接收用户输入内容</li>
                            <li className='mt-2 leading-6'>携带 <code className="bg-gray-200 p-1 rounded">node_id</code>、<code className="bg-gray-200 p-1 rounded">session_id</code>、<code className="bg-gray-200 p-1 rounded">message_id</code> 再次请求 /workflow/invoke</li>
                            <li className='mt-2 leading-6'>如果用户没有在对话框内上传文件，请求示例如下</li>
                        </ul>
                    </div>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`payload = json.dumps({
    "workflow_id": "c90bb7f2-b7d1-49bf-9fb6-3ab60ff8e414",
    "session_id": "d4347ab8e8cd48c48ac9920dbb5a9b35_async_task_id",  # 上次返回的 session_id
    "message_id": "385140",
    "input": {
        "input_2775b": {  # 这里对应返回事件里的 node_id
            # input_schema.value中元素的 key 以及对应要传入的值
            "user_input": "你好"
        }
    }
})`}
                    </SyntaxHighlighter>

                    <div className="mb-6">
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>如果用户在对话框内上传了文件</li>
                            <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                                <li className='mt-2 leading-6'>如果有文件类型，调用毕昇文件上传接口获取到文件url，示例如下：</li>
                            </ul>
                        </ul>
                    </div>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`import requests
def upload_file(local_path: str):
    server = "http://ip:port"
    url = server + '/api/v1/knowledge/upload'
    headers = {}
    files = {'file': open(local_path, 'rb')}
    res = requests.post(url, headers=headers, files=files)
    file_path = res.json()['data'].get('file_path', '')
    return file_path
    
 financeA = upload_file("caibao.pdf")
 financeB = upload_file("caibao2.pdf")`}
                    </SyntaxHighlighter>

                    <div className="mb-6">
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                                <li className='mt-2 leading-6'>成功获取用户的输入和上传文件的url后，拼接为如下格式的接口入参</li>
                            </ul>
                        </ul>
                    </div>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`payload = json.dumps({
    "workflow_id": "c90bb7f2-b7d1-49bf-9fb6-3ab60ff8e414",
    "session_id": "d4347ab8e8cd48c48ac9920dbb5a9b35_async_task_id",  # 上次返回的 session_id
    "message_id": "385140",
    "input": {
        "input_2775b": {  # 这里对应返回事件里的 node_id
            # input_schema.value中元素的 key 以及对应要传入的值
            "user_input": "你好",
            # 上传文件后获取到的文件url列表
            "dialog_files_content": ["minio://127.0.0.1:9000/xxxx"]
        }
    }
})
`}
                    </SyntaxHighlighter>


                    <h3 className='mt-8' id="guide-5">等待输入事件-表单形式</h3>
                    <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                        <p className='bisheng-label'>当工作流返回 <span className="bg-orange-50">event="input"</span> 且 <span className="bg-orange-50">input_type="form_input"</span>时，后端希望前端渲染一个表单，让用户填写内容。</p>
                        <p className='bisheng-label mt-2'>下一次请求 <span className="bg-orange-50">/invoke</span> 接口必带的字段是 <span className="bg-orange-50">node_id</span>, <span className="bg-orange-50">message_id</span>, <span className="bg-orange-50">session_id</span> 以及用户填写的表单值。</p>
                    </div>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'><img src={`${__APP_ENV__.BASE_URL}/assets/api/chat4.png`} className='size-full' alt="" /></div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
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
                            </TableRow>
                        </TableBody>
                    </Table>
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑：</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>解析<code className="bg-gray-200 p-1 rounded">input_schema.value</code> 中的表单元素，在前端渲染表单样式</li>
                            <li className='mt-2 leading-6'>如果有文件类型，调用毕昇文件上传接口获取到文件url，示例如下：</li>
                        </ul>
                    </div>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`import requests
def upload_file(local_path: str):
    server = "http://ip:port"
    url = server + '/api/v1/knowledge/upload'
    headers = {}
    files = {'file': open(local_path, 'rb')}
    res = requests.post(url, headers=headers, files=files)
    file_path = res.json()['data'].get('file_path', '')
    return file_path
    
 financeA = upload_file("caibao.pdf")
 financeB = upload_file("caibao2.pdf")`}
                    </SyntaxHighlighter>
                    <p className='mt-4 bisheng-label'>3. 提交时，JSON 中要和返回的 <code className="bg-gray-200 p-1 rounded">key</code> 对应，并带上 <code className="bg-gray-200 p-1 rounded">session_id</code>、<code className="bg-gray-200 p-1 rounded">message_id</code>、<code className="bg-gray-200 p-1 rounded">node_id</code> 等必备信息。</p>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "xxxxx",
    "input": {
        "input_xxx": {  # 事件里的 node_id
            # key是input_schema.value中元素的 key 以及对应要传入的值
            "text_input": "用户输入的内容",
            "file": ["minio://127.0.0.1:9000/xxxx"] # 用户上传文件获取到的文件url, 允许多选就是多个url
            "category": "选项2" # 将选项内容赋值给变量。当允许多选时，多个选项内容通过逗号分隔。
        }
    }
}`}
                    </SyntaxHighlighter>



                    <h3 className='mt-8' id="guide-6">输出事件</h3>
                    <p className="bisheng-label py-2">事件数据示例</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'>
                                        <img src={`${__APP_ENV__.BASE_URL}/assets/api/chat5.png`} className='size-full' alt="" />
                                        <img src={`${__APP_ENV__.BASE_URL}/assets/api/chat6.png`} className='size-full' alt="" />
                                    </div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
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
                            </TableRow>
                        </TableBody>
                    </Table>
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑：</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>将 <code className="bg-gray-200 p-1 rounded">output_schema.message</code> 展示给用户</li>
                            <li className='mt-2 leading-6'>如果 <code className="bg-gray-200 p-1 rounded">files</code> 不为空，则提供文件下载按钮或预览功能</li>
                            <li className='mt-2 leading-6'><code className="bg-gray-200 p-1 rounded">source_url</code> 基于毕昇服务根路径，需要拼接毕昇访问地址才可访问</li>
                        </ul>
                    </div>


                    <h3 className='mt-8' id="guide-7">输出事件-需输入类型</h3>
                    <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                        <p className='bisheng-label'>此时工作流处于待输入状态</p>
                    </div>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'>
                                        <img src={`${__APP_ENV__.BASE_URL}/assets/api/chat6.png`} className='size-full' alt="" />
                                    </div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
    "event": "output_with_input_msg",
    "node_id": "output_ 123",
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
                            </TableRow>
                        </TableBody>
                    </Table>
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑：</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>展示 <code className="bg-gray-200 p-1 rounded">output_schema</code> 内容</li>
                            <li className='mt-2 leading-6'>根据 <code className="bg-gray-200 p-1 rounded">input_schema</code> 在消息体中绘制输入框，<code className="bg-gray-200 p-1 rounded">input_schema.value.value</code> 为输入框内的默认值，用户可在其基础上二次编辑</li>
                            <li className='mt-2 leading-6'>用户编辑或确认后，再次调用 API 提交。示例如下：</li>
                        </ul>
                    </div>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "消息的唯一ID",
    "input": {
        "output_123": {  # 事件里的节点ID
            # key是input_schema.value中元素的key
            "output_result": "用户输入的内容"
        }
    }
}`}
                    </SyntaxHighlighter>




                    <h3 className='mt-8' id="guide-8">输出事件-选择类型</h3>
                    <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                        <p className='bisheng-label'>此时工作流处于待输入状态</p>
                    </div>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[300px]'>样式预览</TableHead>
                                <TableHead className=''>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top'>
                                    <div className='max-w-[300px]'>
                                        <img src={`${__APP_ENV__.BASE_URL}/assets/api/chat7.png`} className='size-full' alt="" />
                                    </div>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
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
                            </TableRow>
                        </TableBody>
                    </Table>
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑：</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>展示 <code className="bg-gray-200 p-1 rounded">output_schema</code> 内容</li>
                            <li className='mt-2 leading-6'>根据 <code className="bg-gray-200 p-1 rounded">input_schema</code> 在消息体中绘制选项</li>
                            <li className='mt-2 leading-6'>接收到用户选择动作后，拼接接口的入参，再次调用 API，示例如下：</li>
                        </ul>
                    </div>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
                        language={'json'}
                        style={oneDark}
                    >
                        {`{
    "workflow_id": "xxxxx",
    "session_id": "使用接口返回的session_id",
    "message_id": "xxxxxx",
    "input": {
        "output_xxx": {  # 事件里的节点ID
            # key是input_schema.value中元素的key
            "output_result": "e2107f75"  # 用户选择选项对应的id
        }
    }
}`}
                    </SyntaxHighlighter>




                    <h3 className='mt-8' id='guide-9'>流式输出事件-输出中</h3>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
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
                    <div className="mb-6">
                        <p className="bisheng-label py-2">调用方处理示例</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'><code className="bg-gray-200 p-1 rounded">status="stream"</code> 代表当处于流式输出中，需要根据 <code className="bg-gray-200 p-1 rounded">node_execution_id</code> 和 <code className="bg-gray-200 p-1 rounded">output_schema.output_key</code> 来确定流式内容是否属于同一条消息（节点批量运行模式下，会共用同一个 <code className="bg-gray-200 p-1 rounded">node_execution_id</code>，所以需要根据 <code className="bg-gray-200 p-1 rounded">output_key</code> 来区分是否是不同的消息）。</li>
                            <li className='mt-2 leading-6'>如果找到对应的消息，则将 <code className="bg-gray-200 p-1 rounded">message</code> 内容添加到对应的消息里。</li>
                            <li className='mt-2 leading-6'>如果未找到对应的消息，则开启一条新的消息，并将 <code className="bg-gray-200 p-1 rounded">message</code> 和后续此消息的 <code className="bg-gray-200 p-1 rounded">message</code> 拼接在一起。</li>
                        </ul>
                    </div>


                    <h3 className='mt-8' id="guide-10">流式输出事件-结束</h3>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
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
    "source_url": "" # 是否支持溯源请参考产品文档
  }
}`}
                    </SyntaxHighlighter>
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>1. <code className="bg-gray-200 p-1 rounded">status="end"</code>代表流式输出完成，此时根据 node_execution_id 和 output_schema.output_key 找到对应的<code className="bg-gray-200 p-1 rounded">message</code></li>
                            <li className='mt-2 leading-6'>2. 使用 <code className="bg-gray-200 p-1 rounded">message</code> 内容覆盖之前流式输出的结果，显示最终完整答案</li>
                        </ul>
                    </div>



                    <h3 className='mt-8' id="guide-11">结束事件</h3>
                    <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                        <p className='bisheng-label'>当接收到 <span className="bg-orange-50">event="close"</span> 时，代表工作流已运行结束</p>
                    </div>
                    <p className='bisheng-label mt-2'>事件数据示例</p>
                    <SyntaxHighlighter
                        className="w-full overflow-auto custom-scroll"
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
                    <div className="mb-6">
                        <p className="bisheng-label py-2">处理逻辑</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>判断message是否为空，为空则告知用户工作流运行结束</li>
                            <li className='mt-2 leading-6'>如果message不为空，则告知用户工作流运行失败，并把报错信息抛出给用户或者自行处理</li>
                        </ul>
                    </div>



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
10532: 工作流版本已升级，请联系创建者重新编排
10540: 服务器线程数已满，请稍候再试`}
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
