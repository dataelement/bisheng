import { Badge } from '@/components/bs-ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/bs-ui/tabs';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { copyText } from '@/utils';
import { Check, Clipboard } from 'lucide-react';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";

export const JsonItem = ({ name, type, desc, required = false, example = '', remark = '', children = null, line = false }) => {

    return <div className='pl-6 mb-4'>
        <div className='relative flex justify-between mb-2'>
            <div className='flex gap-x-4 gap-y-1 flex-wrap'>
                <Badge variant='outline' className='bg-primary/15 text-primary'>{name}</Badge>
                <div>{type}</div>
                <div className='text-gray-500'>{desc}</div>
            </div>
            {required ? <span className='text-red-500 min-w-12'>必需</span> : <span className='text-gray-500 min-w-12'>可选</span>}
            {line && <div className='absolute bg-input w-6 h-[1px] -left-8 top-2.5'></div>}
        </div>
        {example && <div className='mb-2'>示例值：<span className='text-gray-500'>{example}</span></div>}
        {remark && <div className='mb-4 text-orange-500'>{remark}</div>}
        {children && <div className='border-l border-dashed border-input pl-2'>{children}</div>}
    </div>
}

const ApiAccess = ({ }) => {

    const { id: assisId } = useParams()

    const curl = () => {
        return `curl -X POST "${window.location.protocol}//${window.location.host}/api/v2/assistant/chat/completions" \\
-H "User-Agent: Apifox/1.0.0 (https://apifox.com)" \\
-H "Content-Type: application/json" \\
-d '{
  "model": "${assisId}",
  "messages": [
    {
      "role": "user",
      "content": "你好"
    }
  ],
  "temperature": 0,
  "stream": True
}'
`
    }

    const python = () => {
        return `import requests
import json

url = "${window.location.protocol}//${window.location.host}/api/v2/assistant/chat/completions"

payload = json.dumps({
   "model": "${assisId}",
   "messages": [
      {
         "role": "user",
         "content": "你好"
      }
   ],
   "temperature": 0,
   "stream": True
})
headers = {
   'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)

print(response.text)`
    }

    const { message } = useToast()
    const handleCopyLink = (e) => {
        copyText(e.target).then(() => {
            message({ variant: 'success', description: '复制成功' })
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

    return (
        <section className='max-w-[1600px] flex-grow'>
            <Card className="mb-8">
                <CardHeader>
                    <CardTitle >API 请求示例</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>/api/v2/assistant/chat/completions</span>
                    </h3>
                    <p className='mt-2'>
                        可以直接使用OpenAI官方SDK中的ChatOpenAI组件去使用助手（只支持文档内有的参数。官方组件里其他的例如n、top_p、max_token等参数暂不支持）
                    </p>
                    <p className='my-2'>示例代码如下：</p>
                    <Tabs defaultValue="curl" className="w-full mb-[40px]">
                        <TabsList className="">
                            <TabsTrigger value="curl" className="">cURL</TabsTrigger>
                            <TabsTrigger value="python">Python API</TabsTrigger>
                        </TabsList>
                        <TabsContent value="curl" className='relative'>
                            <button
                                className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                                onClick={() => copyToClipboard(curl())}
                            >
                                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                            </button>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'bash'}
                                style={oneDark}
                            >
                                {curl()}
                            </SyntaxHighlighter>
                        </TabsContent>
                        <TabsContent value="python" className='relative'>
                            <button
                                className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                                onClick={() => copyToClipboard(python())}
                            >
                                {isCopied ? <Check size={18} /> : <Clipboard size={15} />}
                            </button>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'python'}
                                style={oneDark}
                            >
                                {python()}
                            </SyntaxHighlighter>
                        </TabsContent>
                    </Tabs>
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
                                <TableHead className='w-[60%]'>Body 参数: <span className='bg-secondary px-2 py-1 rounded-md text-sm'>application/json</span></TableHead>
                                <TableHead>示例</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top pt-6'>
                                    <JsonItem name="model" type="string" desc="要使用的助手ID" required example={assisId}></JsonItem>
                                    <JsonItem name="messages" type="array [object {2}] " desc="至今为止对话所包含的消息列表。不支持system类型，system使用助手本身的prompt" required>
                                        <JsonItem name="role" type="string" desc="" required example="user" line></JsonItem>
                                        <JsonItem name="content" type="string" desc="" required example="你好" line></JsonItem>
                                    </JsonItem>
                                    <JsonItem name="temperature" type="integer" desc="使用什么采样温度，介于 0 和 2 之间。非0值会覆盖助手配置"></JsonItem>
                                    <JsonItem name="stream" type="boolean" desc="默认为 false 如果设置,则像在 ChatGPT 中一样会发送部分消息增量。标记将以仅数据的服务器发送事件的形式发送,这些事件在可用时,并在 data: [DONE] 消息终止流。"></JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`{
  "model": "${assisId}",
  "messages": [
    {
      "role": "user",
      "content": "你好"
    }
  ],
  "temperature": 0,
  "stream": true
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>

            <Card>
                <CardHeader>
                    <CardTitle>返回响应</CardTitle>
                </CardHeader>
                <CardContent>
                    {/* <h3 className="text-lg font-medium mb-2">成功响应 (200)</h3> */}
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>数据结构</TableHead>
                                <TableHead>示例</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top pt-6'>
                                    <JsonItem name="id" type="string" desc='' required></JsonItem>
                                    <JsonItem name="object" type="string" desc='' required></JsonItem>
                                    <JsonItem name="created" type="integer" desc='' required></JsonItem>
                                    <JsonItem name="choices" type="array [object {3}]" desc='' required>
                                        <JsonItem name="index" type="integer" desc='' line></JsonItem>
                                        <JsonItem name="message" type="object" desc='' line>
                                            <JsonItem name="role" type="string" desc="" required line></JsonItem>
                                            <JsonItem name="content" type="string" desc="" required line></JsonItem>
                                        </JsonItem>
                                        <JsonItem name="finish_reason" type="string" desc='' line></JsonItem>
                                    </JsonItem>
                                    <JsonItem name="usage" type="object " desc='' required>
                                        <JsonItem name="prompt_tokens" type="integer" desc='' required line></JsonItem>
                                        <JsonItem name="completion_tokens" type="integer" desc='' required line></JsonItem>
                                        <JsonItem name="total_tokens" type="integer" desc='' required line></JsonItem>
                                    </JsonItem>
                                </TableCell>
                                <TableCell className='align-top'>
                                    <SyntaxHighlighter
                                        className="w-full overflow-auto custom-scroll"
                                        language={'json'}
                                        style={oneDark}
                                    >
                                        {`
{
  "id": "148964adf7ec439f87a6240289735740",
  "object": "chat.completion",
  "created": 1720755036,
  "model": "a31d044d-af13-43da-b715-d87a29569809",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好，有什么可以帮你的？"
      },
      "finish_reason": "stop"
    }
  ]
}`}
                                    </SyntaxHighlighter>
                                </TableCell>
                            </TableRow>
                        </TableBody>
                    </Table>
                </CardContent>
            </Card>
        </section>
    );
};

export default ApiAccess;
