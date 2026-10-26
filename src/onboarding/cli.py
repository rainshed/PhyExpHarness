"""Commands are local operator clients, not another control plane."""
import argparse
import json
import sys

from .common import Problem, require_platform, settings
from .install import DEFAULT_TASK, doctor, setup


def parser():
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--data-dir', help='受管数据目录；覆盖 PHYEXP_DATA_DIR')
    shared.add_argument('--quantum-harbor', help='Quantum-Harbor checkout 的绝对路径')
    shared.add_argument('--model-config', help='现有供应商 JSON 文件，不包含真实密钥')
    shared.add_argument('--control-port', type=int)
    shared.add_argument('--ui-port', type=int)
    p = argparse.ArgumentParser(description='本地安装与首次实验。所有命令支持 --json；setup/doctor 不调用模型。')
    p.add_argument('--json', action='store_true', help='结构化结果（也可置于命令后）')
    commands = p.add_subparsers(dest='command', required=True)
    install = commands.add_parser('setup', help='安装固定依赖并构建；可重复运行')
    install.add_argument('--repair', action='store_true', help='强制重装项目依赖并重建')
    check = commands.add_parser('doctor', parents=[shared], help='只读环境检查')
    check.add_argument('--task', default=DEFAULT_TASK)
    check.add_argument('--project-only', action='store_true', help='只检查项目安装，不检查外部 Docker/任务条件')
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in argv
    argv = [arg for arg in argv if arg != '--json']
    args = parser().parse_args(argv)
    try:
        require_platform()
        if args.command == 'setup':
            result = setup(repair=args.repair)
        else:
            result = doctor(settings(args), task=args.task, project_only=args.project_only)
        code = 1 if result.get('status') == 'failed' else 0
    except Problem as error:
        result = {'status': 'failed', 'error': {'code': error.code, 'message': str(error), 'nextStep': error.next_step}}
        code = error.exit_code
    except KeyboardInterrupt:
        result = {'status': 'interrupted', 'nextStep': '查询原状态后用相同参数继续；中断本地命令不会取消后台活动。'}
        code = 130
    except (OSError, ValueError) as error:
        result = {'status': 'failed', 'error': {'code': 'local_error', 'message': str(error), 'nextStep': '核对文件、参数和权限后重试。'}}
        code = 1
    result = {'schemaVersion': 1, 'command': args.command, **result}
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{args.command}: {result['status']}")
        for row in result.get('checks', []):
            print(f"  [{row['status']}] {row['id']}: {row['detail']}")
            if row.get('nextStep'):
                print('    '+row['nextStep'])
        for key, value in result.items():
            if key not in ('schemaVersion', 'command', 'status', 'checks'):
                print(f'{key}: '+(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)))
    return code
