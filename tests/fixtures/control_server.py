"""M0 independent supervisor fixture; no model or experiment execution."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json,time
started=time.monotonic()
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.headers.get('authorization')!='Bearer m0-user':self.send_error(403);return
  self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps({'fixture':True,'status':'running','supervisedSeconds':round(time.monotonic()-started,1)}).encode())
 def log_message(self,*args):pass
ThreadingHTTPServer(('127.0.0.1',18402),Handler).serve_forever()
