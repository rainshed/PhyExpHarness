"""Loopback-only synthetic provider for adapter and UI checks. No external model calls."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = 'fixture-provider-key'


class ModelProvider(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        key = self.headers.get('x-api-key') or self.headers.get('Authorization', '').removeprefix('Bearer ')
        self.server.calls.append({'path': self.path, 'model': body.get('model'), 'keyAccepted': key == KEY})
        if key != KEY or body.get('model') == 'error-model':
            self.send_response(401)
            self.send_header('content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': {'message': 'Invalid API key: '+key, 'type': 'authentication_error'}}).encode())
            return
        model = body.get('model', 'fixture-model')
        messages = body.get('messages', body.get('input', []))
        followup = any(m.get('role') == 'tool' or m.get('type') == 'function_call_output' or
                       any(c.get('type') == 'tool_result' for c in (m.get('content') or []) if isinstance(c, dict)) for m in messages)
        tool = not followup and model != 'no-tool'
        args = '{"value":"connection-ok"}'
        name = 'phyexp_connection_check'
        if '/chat/completions' in self.path:
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'fixture-call', 'type': 'function', 'function': {'name': name, 'arguments': args}}]} if tool else {'role': 'assistant', 'content': 'PHYEXP_OK'}
            events = [{'id': 'fixture', 'object': 'chat.completion.chunk', 'model': model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                      {'id': 'fixture', 'object': 'chat.completion.chunk', 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if tool else 'stop'}]}]
            if model != 'no-usage':
                events[-1]['usage'] = {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}
        elif '/responses' in self.path:
            item = {'id': 'fc-fixture', 'type': 'function_call', 'call_id': 'fixture-call', 'name': name, 'arguments': ''} if tool else {'id': 'msg-fixture', 'type': 'message', 'role': 'assistant', 'content': [], 'status': 'in_progress'}
            events = [{'type': 'response.created', 'response': {'id': 'r-fixture', 'model': model, 'status': 'in_progress', 'output': []}},
                      {'type': 'response.output_item.added', 'output_index': 0, 'item': item}]
            if tool:
                events += [{'type': 'response.function_call_arguments.delta', 'output_index': 0, 'item_id': item['id'], 'delta': args},
                           {'type': 'response.output_item.done', 'output_index': 0, 'item': {**item, 'arguments': args}}]
            else:
                events += [{'type': 'response.content_part.added', 'output_index': 0, 'content_index': 0, 'item_id': item['id'], 'part': {'type': 'output_text', 'text': '', 'annotations': []}},
                           {'type': 'response.output_text.delta', 'output_index': 0, 'content_index': 0, 'item_id': item['id'], 'delta': 'PHYEXP_OK'},
                           {'type': 'response.output_item.done', 'output_index': 0, 'item': {**item, 'status': 'completed', 'content': [{'type': 'output_text', 'text': 'PHYEXP_OK', 'annotations': []}]}}]
            events += [{'type': 'response.completed', 'response': {'id': 'r-fixture', 'model': model, 'status': 'completed', 'output': [],
                        'usage': {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}}]
        else:
            block = {'type': 'tool_use', 'id': 'fixture-call', 'name': name, 'input': {}} if tool else {'type': 'text', 'text': ''}
            delta = {'type': 'input_json_delta', 'partial_json': args} if tool else {'type': 'text_delta', 'text': 'PHYEXP_OK'}
            events = [{'type': 'message_start', 'message': {'id': 'msg-fixture', 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'usage': {'input_tokens': 10, 'output_tokens': 0}}},
                      {'type': 'content_block_start', 'index': 0, 'content_block': block},
                      {'type': 'content_block_delta', 'index': 0, 'delta': delta}, {'type': 'content_block_stop', 'index': 0},
                      {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use' if tool else 'end_turn'}, 'usage': {'output_tokens': 2}}, {'type': 'message_stop'}]
        self.send_response(200)
        self.send_header('content-type', 'text/event-stream')
        self.end_headers()
        for event in events:
            prefix = 'event: '+event['type']+'\n' if '/messages' in self.path else ''
            self.wfile.write((prefix+'data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.flush()


def server(port=0):
    instance = ThreadingHTTPServer(('127.0.0.1', port), ModelProvider)
    instance.calls = []
    return instance


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18513)
    args = parser.parse_args()
    server(args.port).serve_forever()
