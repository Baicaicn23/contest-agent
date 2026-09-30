"""sai 命令行工具：不开浏览器、不发请求，在终端里直接操作本项目。

"薄壳"纪律：CLI 只做三件事——解析命令行参数、调用内部功能、打印结果。
真正的逻辑全在内层，所以同一套功能既能被命令行用，也能被 FastAPI 接口用。

用法（装好依赖后，用 uv run sai xxx 执行）：
    sai scan                 扫描官网通知并识别比赛（P1/P2 实现后可用）
    sai model                查看模型档案列表（带 * 的是当前生效档案）
    sai model use qwen       切换模型档案（P2 接入 LLM 工厂时实现）
    sai serve                启动 FastAPI 服务（默认 127.0.0.1:8000）
"""

from __future__ import annotations

import argparse  # Python 标准库自带的命令行参数解析器，不用安装第三方包
import sys


def build_parser() -> argparse.ArgumentParser:
    """定义 sai 支持哪些子命令、每个子命令接什么参数。"""
    parser = argparse.ArgumentParser(prog="sai", description="比赛 Agent 助手（sai）")

    # add_subparsers 实现"一个主命令 + 多个子命令"的结构，
    # 效果就像 git 后面可以接 add / commit / push 一样
    sub = parser.add_subparsers(dest="command", required=True)

    # 子命令一：sai scan [--limit N] [--detail 序号]
    scan = sub.add_parser("scan", help="扫描官网通知列表（可补抓指定条目的详情正文）")
    scan.add_argument("--limit", type=int, default=10, help="最多显示多少条通知（默认 10）")
    scan.add_argument(
        "--detail", type=int, default=None, metavar="序号",
        help="补抓第几条通知的详情正文（从 1 开始），如 --detail 1",
    )

    # 子命令二：sai model [list | use 档案名]
    model = sub.add_parser("model", help="查看或切换模型档案")
    model.add_argument("action", nargs="?", default="list", choices=["list", "use"])
    # nargs="?" 表示这个位置参数可填可不填，不填就用 default
    model.add_argument("name", nargs="?", help="use 时要切换到的档案名，如 qwen")

    # 子命令三：sai serve --host xxx --port xxx
    serve = sub.add_parser("serve", help="启动 FastAPI 服务")
    serve.add_argument("--host", default="127.0.0.1")  # 默认只监听本机，不对外
    serve.add_argument("--port", type=int, default=8000)

    return parser


def _run_scan(args: argparse.Namespace) -> int:
    """执行 sai scan：调 scan_site 用例拿通知，按人能读的格式打印。

    P1 阶段的"扫描"= 抓通知列表（+ 可选详情）。P2 会在同一条命令里
    接上 LLM 识别，把比赛卡片一起打出来。
    """
    from ..composition import build_scan_usecase

    detail_indexes = [args.detail] if args.detail is not None else []

    try:
        notices = build_scan_usecase().execute(
            limit=args.limit, detail_indexes=detail_indexes
        )
    except ConnectionError as error:
        # 网络层失败（重试耗尽）：给人看得懂的一句话，而不是甩一屏异常栈
        print(f"扫描失败：{error}")
        return 1

    if not notices:
        print("没有抓到任何通知（列表页为空或结构变了？检查 config.yaml 的选择器）")
        return 1

    print(f"扫描到 {len(notices)} 条通知：\n")
    for number, notice in enumerate(notices, start=1):
        date = notice.published_at.strftime("%Y-%m-%d") if notice.published_at else "????-??-??"
        print(f"{number:>2}. [{date}] {notice.title}")
        print(f"     {notice.source_url}")

    # 用户点名要的那条详情，打印正文
    if args.detail is not None and args.detail <= len(notices):
        notice = notices[args.detail - 1]
        print("\n" + "=" * 62)
        print(f"详情（第 {args.detail} 条）：{notice.title}")
        print("=" * 62)
        print(notice.content or "（正文为空：可能这条通知是图片/外链形式）")

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。pyproject.toml 里注册的 sai 命令，最终执行的就是这个函数。

    argv 不传就默认解析命令行上的参数；测试时可以直接传列表进来。
    返回值是进程退出码：0 = 成功，非 0 = 失败（操作系统惯例）。
    """
    args = build_parser().parse_args(argv)

    if args.command == "scan":
        return _run_scan(args)

    if args.command == "model":
        # 在函数内部 import：只有真的执行到这个子命令才加载配置模块
        from ..settings import load_settings

        settings = load_settings()

        if args.action == "use" and args.name:
            # P2 接入 LLM 工厂时，这里会把用户的选择持久化回 config.yaml
            print(f"模型切换写入 config.yaml 的功能在 P2 接入 LLM 工厂时实现（目标：{args.name}）")
            return 0

        # 默认动作是 list：打印档案列表，行首带 * 的表示当前生效
        print(f"当前档案：{settings.active_model}")
        for name, profile in settings.yaml_config.models.items():
            marker = "*" if name == settings.active_model else " "
            print(f" {marker} {name:<10} {profile.model}")
        return 0

    if args.command == "serve":
        # uvicorn 是 FastAPI 官方配套的 Web 服务器，负责真正监听端口、处理 HTTP
        import uvicorn

        # 注意第一个参数是 "模块路径:变量名" 这样的字符串，不是直接把 app 对象传进去：
        # 这是 uvicorn 的官方推荐写法，它要自己去 import，
        # 以后开 --reload 热重载等功能都依赖这个字符串形式
        uvicorn.run("contest_agent.composition:app", host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":  # 直接 python -m contest_agent.presentation.cli 也能跑
    sys.exit(main())
