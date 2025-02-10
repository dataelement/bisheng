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
                    <CardTitle>返回数据</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Button variant='link' onClick={() => window.open('https://dataelem.feishu.cn/wiki/ZjIywYGZliClIgkg2jFcP4xunjh?chunked=false', '_blank')}>点击查看飞书文档</Button>
                        {/* <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>https://dataelem.feishu.cn/wiki/ZjIywYGZliClIgkg2jFcP4xunjh?chunked=false</span> */}
                    </h3>
                </CardContent>
            </Card>
        </section>

    );
};

export default ApiAccessFlow;
