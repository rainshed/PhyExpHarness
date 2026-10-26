"""Commands are local operator clients, not another control plane."""
import argparse
import json
import sys

from .common import Problem, require_platform, settings
from .install import DEFAULT_TASK, doctor, setup
from .runtime import start, status, stop_local
from . import experiment


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Problem('invalid_arguments', message, '使用 --help 查看参数。', exit_code=2)


def parser():
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--data-dir', help='受管数据目录；覆盖 PHYEXP_DATA_DIR')
    shared.add_argument('--quantum-harbor', help='Quantum-Harbor checkout 的绝对路径')
    shared.add_argument('--model-config', help='现有供应商 JSON 文件，不包含真实密钥')
    shared.add_argument('--control-port', type=int)
    shared.add_argument('--ui-port', type=int)
    p = Parser(description='本地安装与首次实验。所有命令支持 --json；setup/doctor 不调用模型。')
    p.add_argument('--json', action='store_true', help='结构化结果（也可置于命令后）')
    commands = p.add_subparsers(dest='command', required=True)
    install = commands.add_parser('setup', help='安装固定依赖并构建；可重复运行')
    install.add_argument('--repair', action='store_true', help='强制重装项目依赖并重建')
    check = commands.add_parser('doctor', parents=[shared], help='只读环境检查')
    check.add_argument('--task', default=DEFAULT_TASK)
    check.add_argument('--project-only', action='store_true', help='只检查项目安装，不检查外部 Docker/任务条件')
    launch = commands.add_parser('start', parents=[shared], help='启动后台与工作台；重复调用复用准确实例')
    launch.add_argument('--open', action='store_true', help='打开本机认证入口，不在输出中显示令牌')
    launch.add_argument('--timeout', type=int, default=60, help='每个服务的启动等待秒数，默认 60')
    commands.add_parser('status', parents=[shared], help='读取后台和工作台就绪状态')
    commands.add_parser('stop-local', parents=[shared], help='没有未结束活动时关闭本入口管理的本地进程')
    commands.add_parser('models', parents=[shared], help='查询模型与认证状态，不调用模型')
    commands.add_parser('tasks', parents=[shared], help='查询任务与 benchmark 各阶段时间上限')
    exp = commands.add_parser('experiment', help='准备、启动和核对一次有限实验')
    operations = exp.add_subparsers(dest='operation', required=True)
    for action in ('init', 'prepare', 'start', 'status', 'wait'):
        command = operations.add_parser(action, parents=[shared])
        command.add_argument('--session', required=True, help='持久实验名称；重试保持相同名称')
        if action == 'init':
            command.add_argument('--solver', nargs=2, metavar=('PROVIDER', 'MODEL'), required=True)
            command.add_argument('--meta', nargs=2, metavar=('PROVIDER', 'MODEL'), required=True)
            command.add_argument('--solver-effort')
            command.add_argument('--meta-effort')
            command.add_argument('--task', default=DEFAULT_TASK)
            command.add_argument('--wall-time', type=int, help='活动总秒数；默认完整 benchmark 预留 + 1800 秒')
        if action == 'wait':
            command.add_argument('--timeout', type=int, default=30, help='本地等待 1–60 秒，不改变活动时限')
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in argv
    argv = [arg for arg in argv if arg != '--json']
    args = None
    try:
        args = parser().parse_args(argv)
        require_platform()
        if args.command == 'setup':
            result = setup(repair=args.repair)
        elif args.command == 'doctor':
            result = doctor(settings(args), task=args.task, project_only=args.project_only)
        elif args.command == 'start':
            if not 1 <= args.timeout <= 300:
                raise Problem('invalid_timeout', '启动等待须为 1–300 秒。', exit_code=2)
            result = start(settings(args), timeout=args.timeout, open_browser=args.open)
        elif args.command == 'status':
            result = status(settings(args))
        elif args.command == 'stop-local':
            result = stop_local(settings(args))
        elif args.command == 'models':
            result = experiment.catalog(settings(args))
        elif args.command == 'tasks':
            result = experiment.tasks(settings(args))
        elif args.command == 'experiment':
            config = settings(args)
            if args.operation == 'init':
                result = experiment.initialize(config, args.session, solver=args.solver, meta=args.meta, task=args.task,
                                               wall_time=args.wall_time, solver_effort=args.solver_effort, meta_effort=args.meta_effort)
            elif args.operation == 'prepare':
                result = experiment.prepare(config, args.session)
            elif args.operation == 'start':
                result = experiment.start_experiment(config, args.session)
            elif args.operation == 'wait':
                result = experiment.wait(config, args.session, args.timeout)
            else:
                result = experiment.experiment_status(config, args.session)
        code = 1 if result.get('status') == 'failed' else 3 if result.get('status') == 'pending' else 0
    except Problem as error:
        result = {'status': 'failed', 'error': {'code': error.code, 'message': str(error), 'nextStep': error.next_step}}
        code = error.exit_code
    except KeyboardInterrupt:
        result = {'status': 'interrupted', 'nextStep': '查询原状态后用相同参数继续；中断本地命令不会取消后台活动。'}
        code = 130
    except (OSError, ValueError) as error:
        result = {'status': 'failed', 'error': {'code': 'local_error', 'message': str(error), 'nextStep': '核对文件、参数和权限后重试。'}}
        code = 1
    command = args.command if args else 'arguments'
    if 'schemaVersion' in result:
        result['payloadSchemaVersion'] = result.pop('schemaVersion')
    result = {**result, 'schemaVersion': 1, 'command': command, **({'operation': args.operation} if args and hasattr(args, 'operation') else {})}
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{command}: {result['status']}")
        for row in result.get('checks', []):
            print(f"  [{row['status']}] {row['id']}: {row['detail']}")
            if row.get('nextStep'):
                print('    '+row['nextStep'])
        for key, value in result.items():
            if key not in ('schemaVersion', 'command', 'status', 'checks'):
                print(f'{key}: '+(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)))
    return code
