"""User-only inspection of exact frozen assets; callers cannot supply host paths."""
import subprocess
import sys
from pathlib import Path
from .store import Refused
from src.execution.bundle.manifest import verify
from src.execution.bundle.plugin_reading import source_view


def plugin_source(service,candidate_id,plugin_id,file=None):
    candidate=service.store.get('candidates',candidate_id)
    bundle=Path(candidate['bundlePath']).resolve()
    if not bundle.is_relative_to((service.data/'objects/sha256').resolve()):raise Refused('Frozen object outside data directory')
    try:return source_view(candidate,plugin_id,file)
    except (OSError,ValueError,KeyError,TypeError) as error:raise Refused('冻结插件源码不可用：'+str(error)) from error


def open_folder(path):
    if sys.platform!='darwin':raise Refused('当前系统不支持直接打开文件夹，请复制路径。')
    subprocess.run(['open','--',str(path)],check=True,timeout=10,capture_output=True)
    return {'opened':True,'directory':str(path)}


def export_folder(service,id):
    row=service.store.get('exports',id);root=Path(row['path']).resolve()
    if not root.is_relative_to((service.data/'exports').resolve()) or not root.is_dir():raise Refused('Export directory unavailable')
    verify(root)
    return root


def export_guide(service,id):
    row=service.store.get('exports',id);c=service.store.get('campaigns',row['campaignId'])
    tables=service.reports.tables(c['id']);v=next(v for v in tables['versions'] if v['id']==row['candidateId'])
    plugins={p['id']:p for p in tables['plugins']}
    model=c['config']['solver'];task=c['config']['tasks'][0]
    from src.execution.host.models import campaign_route
    route=campaign_route(c['config'],'solver')
    auth=route['auth']
    auth_guide=('默认读取本机 ~/.codex/auth.json；也可用 PHYEXP_CODEX_AUTH_FILE 指定有效登录文件，勿复制进项目。'
                if auth['type']=='codex' else
                f"在启动独立项目的终端配置 {auth['env']}；密钥仅在宿主使用，勿写入项目。")
    text=f"""# {v['displayName']} · 运行说明

固定执行模型：{model['model']} / {model.get('reasoningEffort','无')}。
本说明对应所选冻结项目；下载不会触发模型调用。

## 1. 准备环境

需要 Node.js 24、Python 3.13、Docker、外部 Quantum-Harbor 任务环境和官方评分镜像，以及有效模型登录。
项目包含执行代码、插件、配置、依赖锁和运行入口。Meta、工作台、活动数据库、历史轨迹、凭据和任务镜像不在包内。

## 2. 安装

解压后进入 harness 目录，执行：

```sh
npm ci --ignore-scripts
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
node install-runner.mjs
.venv/bin/python run.py --verify
```

verify 只检查文件完整性，不调用模型。
{auth_guide}

## 3. 选择任务并运行

下面命令使用本活动的任务；替换外部环境和新输出目录。执行会真实调用固定 Solver：

```sh
.venv/bin/python run.py --quantum-harbor /path/to/Quantum-Harbor --task {task} --output /path/to/new-run --timeout 3600 --soft-token-limit 3000000
```

可将 --task 改成外部环境提供的其他任务，泛化能力尚未验证。输出目录必须尚不存在。
此示例为单次运行、最多 1 小时、300 万 token 软阈值；不自动沿用活动的并发或不限用量设置。
完成后读取 summary.json、轨迹和官方评分；未评分与零分分别记录。

## 包含的插件

"""
    text+='\n'.join('- '+plugins[m['pluginId']]['displayName']+' · '+plugins[m['pluginId']]['version']+'：'+plugins[m['pluginId']]['functionSummary'].replace('\n',' ') for m in v['plugins']) or '无额外执行插件。'
    text+='\n\n文件检查：'+row['staticValidation']+'；独立装配：'+row['relocationValidation']+'；独立真实运行：'+row['realValidation']+'。\n'
    return {'title':v['displayName'],'directory':str(export_folder(service,id)),'markdown':text,'filename':v['displayName']+'-运行说明.md'}
