import { Badge } from '@/components/bs-ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/bs-ui/tabs';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { copyText } from '@/utils';
import { Check, Clipboard } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";

export const JsonItem = ({ name, type, desc, required = false, example = '', remark = '', children = null, line = false }) => {
    const { t } = useTranslation()
    return <div className='pl-6 mb-4'>
        <div className='relative flex justify-between mb-2'>
            <div className='flex gap-x-4 gap-y-1 flex-wrap'>
                <Badge variant='outline' className='bg-primary/15 text-primary'>{name}</Badge>
                <div>{type}</div>
                <div className='text-gray-500'>{desc}</div>
            </div>
            {required ? <span className='text-red-500 min-w-12'>{t('api.required')}</span> : <span className='text-gray-500 min-w-12'>{t('api.optional')}</span>}
            {line && <div className='absolute bg-input w-6 h-[1px] -left-8 top-2.5'></div>}
        </div>
        {example && <div className='mb-2'>{t('api.exampleValue')}：<span className='text-gray-500'>{example}</span></div>}
        {remark && <div className='mb-4 text-orange-500'>{remark}</div>}
        {children && <div className='border-l border-dashed border-input pl-2'>{children}</div>}
    </div>
}

const ApiAccess = ({ }) => {

    const { t } = useTranslation()
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

    return (

        <section className='max-w-[1600px] flex-grow'>
            <Card className="mb-8">
                <CardHeader>
                    <CardTitle>{t('api.apiRequestExample')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge>
                        <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>/api/v2/assistant/chat/completions</span>
                    </h3>
                    <p className='mt-2'>
                        {t('api.sdkNote')}
                    </p>
                    <p className='my-2'>{t('api.exampleCode')}：</p>
                    <Tabs defaultValue="curl" className="w-full mb-[40px]">
                        <TabsList>
                            <TabsTrigger value="curl">cURL</TabsTrigger>
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
                    <CardTitle>{t('api.requestParams')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>
                                    {t('api.bodyParams')} <span className='bg-secondary px-2 py-1 rounded-md text-sm'>application/json</span>
                                </TableHead>
                                <TableHead>{t('api.example')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            <TableRow>
                                <TableCell className='align-top pt-6'>
                                    <JsonItem name="model" type="string" desc={t('api.assistantId')} required example={assisId}></JsonItem>
                                    <JsonItem name="messages" type="array [object {2}] " desc={t('api.messageList')} required>
                                        <JsonItem name="role" type="string" desc="" required example="user" line></JsonItem>
                                        <JsonItem name="content" type="string" desc="" required example="你好" line></JsonItem>
                                    </JsonItem>
                                    <JsonItem name="temperature" type="integer" desc={t('api.temperature')} ></JsonItem>
                                    <JsonItem name="stream" type="boolean" desc={t('api.stream')} ></JsonItem>
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
                    <CardTitle>{t('api.responseData')}</CardTitle>
                </CardHeader>
                <CardContent>
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead className='w-[60%]'>{t('api.dataStructure')}</TableHead>
                                <TableHead>{t('api.example')}</TableHead>
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