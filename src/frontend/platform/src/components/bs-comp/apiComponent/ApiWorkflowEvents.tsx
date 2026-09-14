import { Badge } from '@/components/bs-ui/badge';
import { Button } from '@/components/bs-ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/bs-ui/table';
import { useTranslation } from 'react-i18next';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/cjs/styles/prism';
import { JsonItem } from './ApiAccess';

export function ApiWorkflowEvents() {
    const { t } = useTranslation()
    const brand = t('bisheng') === 'BISHENG' ? '' : t('bisheng')

    return (
    <Card className="mb-8">
        <CardHeader>
            <CardTitle id="guide-t3">{t("api.workflowDoc.event_reference")}</CardTitle>
        </CardHeader>
        <CardContent className='relative'>
            <p className='bisheng-label py-2'>{t("api.workflowDoc.event_schema_intro")}</p>
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
                            <JsonItem name="event" required type="str" desc={t("api.workflowDoc.event_name")}></JsonItem>
                            <JsonItem name="node_id" required type="str" desc={t("api.workflowDoc.node_id")}></JsonItem>
                            <JsonItem name="message_id" required type="str" desc={t("api.workflowDoc.message_id")}></JsonItem>
                            <JsonItem name="node_execution_id" required type="str" desc={t("api.workflowDoc.execution_id")}></JsonItem>
                            <JsonItem name="input_schema" required type="Json" desc={t("api.workflowDoc.input_schema")}>
                                <JsonItem line name="input_type" type="str" desc={t("api.workflowDoc.input_type")} example="form_input" remark={t("api.workflowDoc.input_method")}></JsonItem>
                                <JsonItem line name="value" type="JsonArray" desc={t("api.workflowDoc.input_fields")}>
                                    <JsonItem line name="key" type="str" desc={t("api.workflowDoc.field_key")} example="category"></JsonItem>
                                    <JsonItem line name="type" type="str" desc={t("api.workflowDoc.field_type")} example="select"></JsonItem>
                                    <JsonItem line name="value" type="str" desc={t("api.workflowDoc.field_default")} example=""></JsonItem>
                                    <JsonItem line name="multiple" type="boolean" desc={t("api.workflowDoc.multiple_selection")} example="True"></JsonItem>
                                    <JsonItem line name="label" type="str" desc={t("api.workflowDoc.field_label")} example={t("api.workflowDoc.choose_action")}></JsonItem>
                                    <JsonItem line name="options" type="JsonArray" desc={t("api.workflowDoc.select_options")}>
                                        <JsonItem line name="id" type="str" desc={t("api.workflowDoc.option_id")} example="0b8a2fe9"></JsonItem>
                                        <JsonItem line name="text" type="str" desc={t("api.workflowDoc.option_text")} example={t("api.workflowDoc.action_one")}></JsonItem>
                                        <JsonItem line name="type" type="str" desc={t("api.workflowDoc.option_type")} example=""></JsonItem>
                                    </JsonItem>
                                    <JsonItem line name="required" type="boolean" desc={t("api.workflowDoc.required_field")} example="True"></JsonItem>
                                </JsonItem>
                            </JsonItem>
                            <JsonItem name="output_schema" required type="Json" desc={t("api.workflowDoc.output_schema")}>
                                <JsonItem line name="message" type="str" desc={t("api.workflowDoc.output_content")}></JsonItem>
                                <JsonItem line name="reasoning_content" type="str" desc={t("api.workflowDoc.reasoning_content")}></JsonItem>
                                <JsonItem line name="output_key" type="str" desc={t("api.workflowDoc.output_key")} example="output"></JsonItem>
                                <JsonItem line name="files" type="JsonArray" desc={t("api.workflowDoc.file_list")}>
                                    <JsonItem line name="path" type="str" desc={t("api.workflowDoc.file_path")} example="http://minio:9000/xxx.png?aa=xxx"></JsonItem>
                                    <JsonItem line name="name" type="str" desc={t("api.workflowDoc.file_name")} example={t("api.workflowDoc.image_example")}></JsonItem>
                                </JsonItem>
                                <JsonItem line name="extra" type="str" desc={t("api.workflowDoc.qa_reference")} example={t("api.workflowDoc.qa_example")}></JsonItem>
                            </JsonItem>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.event_schema_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>

            <Popover>
                <PopoverTrigger asChild>
                    <Button className="fixed top-20 right-10 z-10 size-11 rounded-full">{t("api.workflowDoc.navigation")}</Button>
                </PopoverTrigger>
                <PopoverContent className="p-4 shadow-lg flex flex-col gap-2">
                    <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#000] mr-2'></span><a href="#guide-t1">{t("api.workflowDoc.basic_info")}</a></Badge>
                    <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#000] mr-2'></span><a href="#guide-t2">{t("api.workflowDoc.call_sequence")}</a></Badge>
                    <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#000] mr-2'></span><a href="#guide-t3">{t("api.workflowDoc.event_reference")}</a></Badge>
                    <div className='pl-4 flex flex-col gap-2'>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-2">{t("api.workflowDoc.guide_question_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-primary mr-2'></span><a href="#guide-3">{t("api.workflowDoc.dialog_input_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-primary mr-2'></span><a href="#guide-5">{t("api.workflowDoc.form_input_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-6">{t("api.workflowDoc.output_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-7">{t("api.workflowDoc.inline_input_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#BBDBFF] mr-2'></span><a href="#guide-8">{t("api.workflowDoc.choice_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-9">{t("api.workflowDoc.stream_chunk_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-[#FFD89A] mr-2'></span><a href="#guide-10">{t("api.workflowDoc.stream_end_event")}</a></Badge>
                        <Badge variant='gray' className='p-2'><span className='size-2 rounded-full bg-red-400 mr-2'></span><a href="#guide-11">{t("api.workflowDoc.close_event")}</a></Badge>
                    </div>
                </PopoverContent>
            </Popover>
            <h3 className='mt-8' id="guide-1">{t("api.workflowDoc.guide_word_event")}</h3>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top relative'>
                            {brand && <div className='absolute w-40 top-4 left-4 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                            <div className='max-w-[300px]'><img src={__APP_ENV__.BASE_URL + '/assets/api/chat1.png'} className='size-full min-w-72' alt="" /></div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.guide_word_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.show_message")}</p>

            <h3 className='mt-8' id="guide-2">{t("api.workflowDoc.guide_question_event")}</h3>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top relative'>
                            {brand && <div className='absolute w-40 top-4 left-4 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                            <div className='max-w-[300px]'><img src={__APP_ENV__.BASE_URL + '/assets/api/chat2.png'} className='size-full min-w-72' alt="" /></div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.guide_question_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.handle_questions")}</p>

            <h3 className='mt-8' id="guide-3">{t("api.workflowDoc.dialog_input_event")}</h3>
            <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                <p className='bisheng-label'>{t("api.workflowDoc.when_workflow_returns")}<span className="bg-orange-50">event="input"</span>{t("api.workflowDoc.and_condition")}<span className="bg-orange-50">input_type="dialog_input"</span>{t("api.workflowDoc.show_dialog")}</p>
                <p className='bisheng-label mt-2'>{t("api.workflowDoc.next_request")}<span className="bg-orange-50">/invoke</span>{t("api.workflowDoc.required_keys")}<span className="bg-orange-50">node_id</span>,<span className="bg-orange-50">message_id</span>,<span className="bg-orange-50">session_id</span>{t("api.workflowDoc.and_dialog_input")}</p>
            </div>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top relative'>
                            {brand && <div className='absolute w-40 top-4 left-4 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                            <div className='max-w-[300px]'><img src={__APP_ENV__.BASE_URL + '/assets/api/output.png'} className='size-full min-w-72' alt="" /></div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.dialog_input_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_label")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.render_dialog")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.include_fields")}<code className="bg-gray-200 p-1 rounded">node_id</code>、<code className="bg-gray-200 p-1 rounded">session_id</code>、<code className="bg-gray-200 p-1 rounded">message_id</code>{t("api.workflowDoc.invoke_again")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.without_files")}</li>
                </ul>
            </div>
            <SyntaxHighlighter
                className="w-full max-w-[80vw] overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.dialog_submit_example")}
            </SyntaxHighlighter>

            <div className="mb-6">
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.with_files")}</li>
                    <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                        <li className='mt-2 leading-6'>{t("api.workflowDoc.upload_intro")}</li>
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
                        <li className='mt-2 leading-6'>{t("api.workflowDoc.combine_input_files")}</li>
                    </ul>
                </ul>
            </div>
            <SyntaxHighlighter
                className="w-full overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.dialog_files_submit_example")}
            </SyntaxHighlighter>

            <h3 className='mt-8' id="guide-5">{t("api.workflowDoc.form_input_event")}</h3>
            <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                <p className='bisheng-label'>{t("api.workflowDoc.when_workflow_returns")}<span className="bg-orange-50">event="input"</span>{t("api.workflowDoc.and_condition")}<span className="bg-orange-50">input_type="form_input"</span>{t("api.workflowDoc.show_form")}</p>
                <p className='bisheng-label mt-2'>{t("api.workflowDoc.next_request")}<span className="bg-orange-50">/invoke</span>{t("api.workflowDoc.required_fields")}<span className="bg-orange-50">node_id</span>, <span className="bg-orange-50">message_id</span>, <span className="bg-orange-50">session_id</span>{t("api.workflowDoc.and_form_values")}</p>
            </div>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top relative'>
                            {brand && <div className='absolute w-40 top-4 left-4 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                            <div className='max-w-[300px]'><img src={__APP_ENV__.BASE_URL + '/assets/api/chat4.png'} className='size-full min-w-72' alt="" /></div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.form_input_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_label")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.parse_fields")}<code className="bg-gray-200 p-1 rounded">input_schema.value</code>{t("api.workflowDoc.render_form_fields")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.upload_intro")}</li>
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
            <p className='mt-4 bisheng-label'>{t("api.workflowDoc.submission_keys")}<code className="bg-gray-200 p-1 rounded">key</code>{t("api.workflowDoc.include_context")}<code className="bg-gray-200 p-1 rounded">session_id</code>、<code className="bg-gray-200 p-1 rounded">message_id</code>、<code className="bg-gray-200 p-1 rounded">node_id</code>{t("api.workflowDoc.required_context")}</p>
            <SyntaxHighlighter
                className="w-full max-w-[80vw] overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.form_submit_example")}
            </SyntaxHighlighter>

            <h3 className='mt-8' id="guide-6">{t("api.workflowDoc.output_event")}</h3>
            <p className="bisheng-label py-2">{t("api.workflowDoc.event_example")}</p>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top'>
                            <div className='max-w-[300px] relative'>
                                {brand && <div className='absolute w-40 top-1 left-2 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                                <img src={__APP_ENV__.BASE_URL + '/assets/api/chat5.png'} className='size-full min-w-72' alt="" />
                                {!brand && <img src={__APP_ENV__.BASE_URL + '/assets/api/chat6.png'} className='size-full' alt="" />}
                            </div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.output_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_label")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.display_value")}<code className="bg-gray-200 p-1 rounded">output_schema.message</code>{t("api.workflowDoc.show_user")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.if_value")}<code className="bg-gray-200 p-1 rounded">files</code>{t("api.workflowDoc.show_file_actions")}</li>
                </ul>
            </div>

            <h3 className='mt-8' id="guide-7">{t("api.workflowDoc.inline_input_event")}</h3>
            <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                <p className='bisheng-label'>{t("api.workflowDoc.waiting_state")}</p>
            </div>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top'>
                            <div className='max-w-[300px] relative'>
                                {brand && <div className='absolute w-40 top-1 left-2 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                                <img src={__APP_ENV__.BASE_URL + '/assets/api/chat6.png'} className='size-full' alt="" />
                            </div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.inline_input_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_label")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.display")}<code className="bg-gray-200 p-1 rounded">output_schema</code>{t("api.workflowDoc.content_suffix")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.based_on")}<code className="bg-gray-200 p-1 rounded">input_schema</code>{t("api.workflowDoc.render_inline_input")}<code className="bg-gray-200 p-1 rounded">input_schema.value.value</code>{t("api.workflowDoc.editable_default")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.submit_edited")}</li>
                </ul>
            </div>
            <SyntaxHighlighter
                className="w-full overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.inline_submit_example")}
            </SyntaxHighlighter>

            <h3 className='mt-8' id="guide-8">{t("api.workflowDoc.choice_event")}</h3>
            <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                <p className='bisheng-label'>{t("api.workflowDoc.waiting_state")}</p>
            </div>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className='w-[300px]'>{t("api.workflowDoc.preview")}</TableHead>
                        <TableHead className=''>{t('api.example')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    <TableRow>
                        <TableCell className='align-top'>
                            <div className='max-w-[300px] relative'>
                                {brand && <div className='absolute w-40 top-1 left-2 z-10 bg-[#EFF1F5] text-gray-400 text-xs'>{brand}</div>}
                                <img src={__APP_ENV__.BASE_URL + '/assets/api/chat7.png'} className='size-full min-w-72' alt="" />
                            </div>
                        </TableCell>
                        <TableCell className='align-top'>
                            <SyntaxHighlighter
                                className="w-full overflow-auto custom-scroll"
                                language={'json'}
                                style={oneDark}
                            >
                                {t("api.workflowDoc.choose_output_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_label")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.display")}<code className="bg-gray-200 p-1 rounded">output_schema</code>{t("api.workflowDoc.content_suffix")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.based_on")}<code className="bg-gray-200 p-1 rounded">input_schema</code>{t("api.workflowDoc.render_options")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.submit_choice")}</li>
                </ul>
            </div>
            <SyntaxHighlighter
                className="w-full overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.choose_submit_example")}
            </SyntaxHighlighter>

            <h3 className='mt-8' id='guide-9'>{t("api.workflowDoc.stream_chunk_event")}</h3>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <SyntaxHighlighter
                className="w-full overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.stream_chunk_example")}
            </SyntaxHighlighter>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.client_handling")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'><code className="bg-gray-200 p-1 rounded">status="stream"</code>{t("api.workflowDoc.stream_identity")}<code className="bg-gray-200 p-1 rounded">node_execution_id</code>{t("api.workflowDoc.and")}<code className="bg-gray-200 p-1 rounded">output_schema.output_key</code>{t("api.workflowDoc.stream_message_identity")}<code className="bg-gray-200 p-1 rounded">node_execution_id</code>{t("api.workflowDoc.so_use")}<code className="bg-gray-200 p-1 rounded">output_key</code>{t("api.workflowDoc.distinguish_messages")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.append_existing")}<code className="bg-gray-200 p-1 rounded">message</code>{t("api.workflowDoc.append_content")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.create_message")}<code className="bg-gray-200 p-1 rounded">message</code>{t("api.workflowDoc.subsequent_chunks")}<code className="bg-gray-200 p-1 rounded">message</code>{t("api.workflowDoc.combine_chunks")}</li>
                </ul>
            </div>

            <h3 className='mt-8' id="guide-10">{t("api.workflowDoc.stream_end_event")}</h3>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <SyntaxHighlighter
                className="w-full overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.stream_end_example")}
            </SyntaxHighlighter>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_title")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>1. <code className="bg-gray-200 p-1 rounded">status="end"</code>{t("api.workflowDoc.find_completed_message")}<code className="bg-gray-200 p-1 rounded">message</code></li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.replace_with")}<code className="bg-gray-200 p-1 rounded">message</code>{t("api.workflowDoc.replace_final_answer")}</li>
                </ul>
            </div>

            <h3 className='mt-8' id="guide-11">{t("api.workflowDoc.close_event")}</h3>
            <div className='border border-red-200 rounded-sm bg-orange-100 p-4 text-sm'>
                <p className='bisheng-label'>{t("api.workflowDoc.when_received")}<span className="bg-orange-50">event="close"</span>{t("api.workflowDoc.workflow_finished")}</p>
            </div>
            <p className='bisheng-label mt-2'>{t("api.workflowDoc.event_example")}</p>
            <SyntaxHighlighter
                className="w-full overflow-auto custom-scroll"
                language={'json'}
                style={oneDark}
            >
                {t("api.workflowDoc.close_example")}
            </SyntaxHighlighter>
            <div className="mb-6">
                <p className="bisheng-label py-2">{t("api.workflowDoc.handling_title")}</p>
                <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.check_close_message")}</li>
                    <li className='mt-2 leading-6'>{t("api.workflowDoc.show_close_error")}</li>
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
                                {t("api.workflowDoc.errors_example")}
                            </SyntaxHighlighter>
                        </TableCell>
                    </TableRow>
                </TableBody>
            </Table>
        </CardContent>
    </Card >
    );
}
