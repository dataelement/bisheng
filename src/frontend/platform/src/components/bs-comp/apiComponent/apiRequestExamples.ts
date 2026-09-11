export type ApiIdentityMode = 'service' | 'delegate' | 'external';
export type PublishedApiKind = 'assistant' | 'workflow';

interface ExampleOptions {
    origin: string;
    applicationId: string;
    identity: ApiIdentityMode;
    question: string;
}

function identityHeader(identity: ApiIdentityMode): [string, string] | undefined {
    if (identity === 'delegate') return ['X-On-Behalf-Of', '123'];
    if (identity === 'external') return ['X-End-User', 'customer-001'];
    return undefined;
}

function curlRequest(path: string, body: object, options: ExampleOptions) {
    const header = identityHeader(options.identity);
    return [
        `curl --no-buffer -X POST "${options.origin}${path}" \\`,
        '  -H "Authorization: Bearer $BISHENG_API_KEY" \\',
        '  -H "Content-Type: application/json" \\',
        ...(header ? [`  -H "${header[0]}: ${header[1]}" \\`] : []),
        "  --data-binary @- <<'JSON'",
        JSON.stringify(body, null, 2),
        'JSON',
    ].join('\n');
}

export function assistantExamples(options: ExampleOptions) {
    const header = identityHeader(options.identity);
    const messages = [{ role: 'user', content: options.question }];
    return {
        curl: curlRequest('/api/v2/assistant/chat/completions', {
            model: options.applicationId, messages, temperature: 0, stream: true,
        }, options),
        python: `import os
from openai import OpenAI

base_url = ${JSON.stringify(`${options.origin}/api/v2/assistant`)}
model = ${JSON.stringify(options.applicationId)}
client = OpenAI(base_url=base_url, api_key=os.environ["BISHENG_API_KEY"])
identity_headers = ${JSON.stringify(header ? { [header[0]]: header[1] } : {})}
messages = ${JSON.stringify(messages)}

response = client.chat.completions.create(
    model=model,
    messages=messages,
    temperature=0,
    stream=True,
    extra_headers=identity_headers,
)
answer = ""
for chunk in response:
    if not chunk.choices:
        continue
    delta = chunk.choices[0].delta
    reasoning = (delta.model_extra or {}).get("reasoning_content")
    if reasoning:
        print(reasoning, end="", flush=True)
    if delta.content:
        answer += delta.content
        print(delta.content, end="", flush=True)

# Keep this history separately for each caller's conversation.
messages.append({"role": "assistant", "content": answer})
# Append the next user message and send messages again for the next turn.
`,
    };
}

export function workflowExamples(options: ExampleOptions) {
    const header = identityHeader(options.identity);
    return {
        curl: curlRequest('/api/v2/workflow/invoke', {
            workflow_id: options.applicationId, stream: false,
        }, options),
        continue: curlRequest('/api/v2/workflow/invoke', {
            workflow_id: options.applicationId,
            session_id: '<session_id>',
            message_id: 123456,
            input: { '<node_id>': { '<field_key>': options.question } },
            stream: false,
        }, options),
        stop: curlRequest('/api/v2/workflow/stop', {
            workflow_id: options.applicationId, session_id: '<session_id>',
        }, options),
        python: `import os
import requests

base_url = ${JSON.stringify(`${options.origin}/api/v2/workflow`)}
workflow_id = ${JSON.stringify(options.applicationId)}
headers = {
    "Authorization": f"Bearer {os.environ['BISHENG_API_KEY']}",
    "Content-Type": "application/json",${header ? `\n    "${header[0]}": "${header[1]}",` : ''}
}

def send(path, body):
    response = requests.post(base_url + path, headers=headers, json=body, timeout=300)
    response.raise_for_status()
    return response.json()

def continue_workflow(session_id, message_id, node_id, values):
    return send("/invoke", {
        "workflow_id": workflow_id,
        "session_id": session_id,
        "message_id": message_id,
        "input": {node_id: values},
        "stream": False,
    })

def stop_workflow(session_id):
    return send("/stop", {"workflow_id": workflow_id, "session_id": session_id})

result = send("/invoke", {"workflow_id": workflow_id, "stream": False})
print(result)
# Use returned session_id and input event fields with continue_workflow.
# Call stop_workflow only when the caller requests cancellation.
`,
    };
}
