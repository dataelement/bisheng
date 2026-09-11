import { Badge } from '@/components/bs-ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";

import { ApiRequestExamples } from './ApiRequestExamples';

interface JsonItemProps {
    name: string;
    type: string;
    desc: string;
    required?: boolean;
    example?: string;
    remark?: string;
    children?: ReactNode;
    line?: boolean;
}

export function JsonItem({ name, type, desc, required = false, example = '', remark = '', children = null, line = false }: JsonItemProps) {
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

export function ApiAccess() {

    const { t } = useTranslation()
    const { id: assisId } = useParams()

    return (
        <section className='max-w-[1600px] flex-grow'>
            <ApiRequestExamples kind="assistant" applicationId={assisId ?? ''} />

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
                                        <JsonItem name="content" type="string" desc="" required example={t("api.assistantDoc.hello")} line></JsonItem>
                                    </JsonItem>
                                    <JsonItem name="temperature" type="number" desc={t('api.temperature')} ></JsonItem>
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
      "content": "${t("api.assistantDoc.hello")}"
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
        "content": "${t("api.assistantDoc.answer")}"
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
}
