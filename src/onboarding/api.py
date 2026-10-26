"""Authenticated loopback client. Never follows redirects carrying a control token."""
import json
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .common import Problem


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class API:
    def __init__(self, config, *, timeout=20):
        self.config, self.timeout = config, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, route, body=None):
        if not route.startswith('/') or route.startswith('//'):
            raise Problem('invalid_route', 'API 路由必须是本地绝对路径。')
        try:
            token = (Path(self.config['data_dir'])/'user-token').read_text().strip()
        except OSError:
            raise Problem('control_not_ready', '数据目录中没有可读的后台认证文件。', '先运行 start，并核对 --data-dir。', exit_code=3) from None
        headers = {'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'}
        request = Request(self.config['control_url']+route, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                data = json.loads(error.read(1024*1024))
                message = data.get('error', '后台拒绝请求')
            except (ValueError, AttributeError):
                message = '后台拒绝请求'
            raise Problem('http_'+str(error.code), str(message), '核对原活动状态、参数与认证；未知创建结果须保留原 session 重试。') from None
        except (URLError, TimeoutError, socket.timeout, ConnectionError, json.JSONDecodeError) as error:
            raise Problem('request_unknown', '无法确认后台请求结果。', '运行 status 核对连接，并用相同 session 查询或重试；不要另建活动。', exit_code=3) from error


def health_matches(health, config):
    return isinstance(health, dict) and health.get('service') == 'independent-control' and health.get('instance', {}).get('source') == config['source'] and health['instance'].get('dataDir') == config['data_dir'] and health['instance'].get('quantumHarbor') == config['quantum_harbor']
