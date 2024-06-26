import json
from tqdm import tqdm
from openai import OpenAI


def predict():
    func_json_file = 'func_call_agent_oai_convs.jsonl'
    with open(func_json_file, 'r') as f:
        lines = f.readlines()
    
    results = []
    for index, line in enumerate(tqdm(lines)):
        data = json.loads(line)
        tools = data['tools']
        messages = data['messages']

        client = OpenAI(
            api_key="dummy",
            base_url="http://34.87.129.78:9200/v1"
        )

        completion = client.chat.completions.create(
            model="qwen1.5-72b-chat",
            messages=messages,
            tools=tools,
            temperature=0.3,
        )
        response = completion.choices[0].message

        if response.tool_calls is not None:
            tool_calls =[{"id": tool_call.id, "function": {"arguments": tool_call.function.arguments, "name": tool_call.function.name}, "type": "function"} for tool_call in response.tool_calls] 
        else:
            tool_calls = None

        response = {
            'content': response.content,
            'role': response.role,
            'function_call': response.function_call,
            'tool_calls': tool_calls,
        }
        results.append(json.dumps(response, ensure_ascii=False))
    
    with open('func_call_ageent_pred_local_qwen2_72b.json', 'w') as f:
        f.write('\n'.join(results))


predict()
