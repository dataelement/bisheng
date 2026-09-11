import { Badge } from '@/components/bs-ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/bs-ui/card';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { copyText } from '@/utils';
import { Check, Clipboard } from 'lucide-react';
import { useState, type MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/cjs/styles/prism";
import { useParams } from 'react-router-dom';
import { ApiWorkflowEvents } from './ApiWorkflowEvents';

export function ApiAccessFlow() {
    const { t } = useTranslation()
    const { id } = useParams()

    const { message } = useToast()
    const handleCopyLink = (event: MouseEvent<HTMLElement>) => {
        copyText(event.currentTarget).then(() => {
            message({ variant: 'success', description: t('api.copySuccess') })
        })
    }

    const [isCopied, setIsCopied] = useState<boolean>(false);
    const handleCopyCode = (code: string) => {
        setIsCopied(true);
        copyText(code).then(() => {
            setTimeout(() => {
                setIsCopied(false);
            }, 2000);
        })
    }

    const firstCode = t("api.workflowDoc.first_request_example", { origin: location.origin, workflowId: id, interpolation: { escapeValue: false } })

    return (
        <section className='max-w-[1600px] flex-grow'>
            <Card className="mb-8">
                <CardHeader>
                    <CardTitle id="guide-t1">{t("api.workflowDoc.basic_info")}</CardTitle>
                </CardHeader>
                <CardContent>
                    <h3 className='py-2' id="guide-word">{t("api.workflowDoc.invoke_endpoint")}</h3>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>{location.origin}/api/v2/workflow/invoke</span>
                    </h3>
                    <h3 className='py-2' id="guide-word">{t("api.workflowDoc.stop_endpoint")}</h3>
                    <h3 className="mb-2 bg-secondary px-4 py-2 inline-flex items-center rounded-md gap-1">
                        <Badge>POST</Badge> <span className='hover:underline cursor-pointer' onClick={handleCopyLink}>{location.origin}/api/v2/workflow/stop</span>
                    </h3>
                </CardContent>
            </Card>

            <Card className="mb-8">
                <CardHeader>
                    <CardTitle id="guide-t2">{t("api.workflowDoc.call_sequence")}</CardTitle>
                </CardHeader>
                <CardContent>
                    <div className='w-[700px] mx-auto'><img src={__APP_ENV__.BASE_URL + '/assets/api/flow.png'} className='size-full' alt="" /></div>
                    <p className='bisheng-label pb-2'>{t("api.workflowDoc.sequence_intro")}</p>
                    <p className="bisheng-label pb-2"><span className="font-semibold">{t("api.workflowDoc.step_one")}</span>{t("api.workflowDoc.start_workflow")}</p>
                    <div className='relative  max-w-[80vw]'>
                        <button
                            className="absolute right-0 flex items-center gap-1.5 rounded bg-none p-1 text-xs text-gray-500 dark:text-gray-300"
                            onClick={() => handleCopyCode(firstCode)}
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
                    <p className="bisheng-label py-2"><span className="font-semibold">{t("api.workflowDoc.step_two")}</span>{t("api.workflowDoc.parse_events")}</p>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll text-sm"
                        language={'json'}
                        style={oneDark}
                    >
                        {t("api.workflowDoc.first_response_example")}
                    </SyntaxHighlighter>
                    <div className="mb-6">
                        <p className="bisheng-label py-2"><span className="font-semibold">{t("api.workflowDoc.step_three")}</span>{t("api.workflowDoc.render_events")}</p>
                        <ul className="list-disc list-inside pl-4 mt-2 bisheng-label pb-2">
                            <li className='mt-2 leading-6'>{t("api.workflowDoc.if_event")}<strong>{t("api.workflowDoc.normal_output")}</strong>{t("api.workflowDoc.for_example")}<code className="bg-gray-200 py-1 rounded">event="output_msg"</code>{t("api.workflowDoc.show_content")}</li>
                            <li className='mt-2 leading-6'>{t("api.workflowDoc.if_event")}<strong>{t("api.workflowDoc.wait_user_input")}</strong>{t("api.workflowDoc.for_example")}<code className="bg-gray-200 p-1 rounded">event="input"</code>{t("api.workflowDoc.or")}<code className="bg-gray-200 p-1 rounded">event="output_with_input_msg"</code>{t("api.workflowDoc.or")}<code className="bg-gray-200 p-1 rounded">event="output_with_choose_msg"</code>{t("api.workflowDoc.render_input_ui")}</li>
                        </ul>
                    </div>
                    <p className="bisheng-label py-2"><span className="font-semibold">{t("api.workflowDoc.step_four")}</span>{t("api.workflowDoc.submit_again")}<code className="bg-gray-200 p-1 rounded">/invoke</code>{t("api.workflowDoc.endpoint_suffix")}</p>
                    <SyntaxHighlighter
                        className="w-full max-w-[80vw] overflow-auto custom-scroll text-sm"
                        language={'json'}
                        style={oneDark}
                    >
                        {t("api.workflowDoc.continue_request_example")}
                    </SyntaxHighlighter>
                    <p className="bisheng-label py-2"><span className="font-semibold">{t("api.workflowDoc.step_five")}</span>{t("api.workflowDoc.continue_events")}<code className="bg-gray-100 p-1 rounded">close</code>{t("api.workflowDoc.close_or_stop")}<code className="bg-gray-100 p-1 rounded">POST /workflow/stop</code>{t("api.workflowDoc.stop_manually")}</p>
                </CardContent>
            </Card>

            <ApiWorkflowEvents />

        </section >

    );
};
