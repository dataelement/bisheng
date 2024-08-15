from http import HTTPStatus
import dashscope


def call_qwen2(messages, model_name='qwen2-72b-instruct'):
    response = dashscope.Generation.call(
        model_name,
        messages=messages,
        result_format='message',  # set the result is message format.
    )
    if response.status_code == HTTPStatus.OK:
        return response['output']['choices'][0]['message']['content']
    else:
        return 'Request id: %s, Status code: %s, error code: %s, error message: %s' % (
            response.request_id,
            response.status_code,
            response.code,
            response.message,
        )
