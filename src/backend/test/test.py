# from http.server import HTTPServer, BaseHTTPRequestHandler
# import json
# import time

# class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

#     def do_POST(self, **kwargs):
#         response = {
#             'id':
#             'chatcmpl-1016',
#             'created':
#             time.time(),
#             'model':
#             'Qwen-14B-Chat',
#             'choices': [{
#                 'index': 0,
#                 'message': {
#                     'role': 'assistant',
#                     'content': 'ok'
#                 },
#                 'finish_reason': 'stop'
#             }],
#             'usage': {
#                 'prompt_tokens': 34,
#                 'total_tokens': 59,
#                 'completion_tokens': 25
#             }
#         }
#         time.sleep(2)  # 设置sleep
#         self.send_response(200)
#         self.send_header('Content-type', 'text/html')
#         self.end_headers()
#         self.wfile.write(json.dumps(response).encode())

# def run(server_class=HTTPServer, handler_class=SimpleHTTPRequestHandler, port=8000):
#     server_address = ('', port)
#     httpd = server_class(server_address, handler_class)
#     print(f'Starting httpd server on port {port}...')
#     httpd.serve_forever()

# if __name__ == '__main__':
#     run()

import asyncio
import json
import time

from aiohttp import web


async def handle(request):

    await asyncio.sleep(2)
    response = {
        'id':
        'chatcmpl-1016',
        'created':
        time.time(),
        'model':
        'Qwen-14B-Chat',
        'choices': [{
            'index': 0,
            'message': {
                'role': 'assistant',
                'content': 'ok'
            },
            'finish_reason': 'stop'
        }],
        'usage': {
            'prompt_tokens': 34,
            'total_tokens': 59,
            'completion_tokens': 25
        }
    }
    return web.Response(text=json.dumps(response))


app = web.Application()
app.router.add_post('/', handle)

if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=8080)
