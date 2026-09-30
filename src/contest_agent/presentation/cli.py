"""sai 命令行薄壳：scan / model / serve（P0 仅骨架）。

薄壳纪律：CLI 只解析参数、调用用例、打印结果，不写业务逻辑。
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sai", description="比赛 Agent 助手（sai）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="扫描官网通知并识别比赛（P1/P2 实现）")

    model = sub.add_parser("model", help="查看或切换模型档案")
    model.add_argument("action", nargs="?", default="list", choices=["list", "use"])
    model.add_argument("name", nargs="?", help="model use deepseek")

    serve = sub.add_parser("serve", help="启动 FastAPI 服务")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "scan":
        print("scan：P1 爬虫 + P2 识别实现后可用")
        return 0

    if args.command == "model":
        from ..settings import load_settings

        settings = load_settings()
        if args.action == "use" and args.name:
            print(f"模型切换写入 config.yaml 的功能在 P2 接入 LLM 工厂时实现（目标：{args.name}）")
            return 0
        print(f"当前档案：{settings.active_model}")
        for name, profile in settings.yaml_config.models.items():
            marker = "*" if name == settings.active_model else " "
            print(f" {marker} {name:<10} {profile.model}")
        return 0

    if args.command == "serve":
        import uvicorn

        uvicorn.run("contest_agent.composition:app", host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
