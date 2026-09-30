"""sai 命令行工具：不开浏览器、不发请求，在终端里直接操作本项目。

"薄壳"纪律：CLI 只做三件事——解析命令行参数、调用内部功能、打印结果。
真正的逻辑全在内层，所以同一套功能既能被命令行用，也能被 FastAPI 接口用。

用法（装好依赖后，用 uv run sai xxx 执行）：
    sai scan                 扫描官网通知并识别比赛（P1/P2 实现后可用）
    sai identify             扫描 + LLM 识别比赛卡片（P2/P3）
    sai report               渲染比赛情报报告（P3）
    sai generate             生成参赛材料（AgentScope 循环，P4）
    sai study-path           生成备考路径（P5）
    sai cost                 查 LLM 花费账单（M1 成本台账）
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

    # 子命令二：sai identify [--limit N]（P2：粗筛 + LLM 识别比赛）
    identify = sub.add_parser(
        "identify", help="扫描并识别比赛（关键词粗筛 + LLM 单次结构化调用）"
    )
    identify.add_argument("--limit", type=int, default=5, help="扫描最近多少条通知（默认 5）")

    # 子命令三：sai report [--out 路径]（P3：渲染 Markdown 比赛情报报告）
    report = sub.add_parser("report", help="把库里的比赛卡片渲染成 Markdown 报告")
    report.add_argument(
        "--out", default=None, help="输出文件路径（默认 output/contest_report.md）"
    )

    # 子命令四：sai generate [--skill 名] [--competition 关键字]（P4：AgentScope 循环）
    generate = sub.add_parser(
        "generate", help="为比赛生成参赛材料（AgentScope ReAct 循环 + 工具 + 技能）"
    )
    generate.add_argument(
        "--skill", default="ppt-outline",
        help="技能名，对应 skills/ 目录下的文件（ppt-outline / proposal）",
    )
    generate.add_argument(
        "--competition", default=None,
        help="比赛名称关键字（默认取库里截止日期最近的一张卡）",
    )
    generate.add_argument(
        "--max-steps", type=int, default=8, help="agent 循环最大步数（防死循环）"
    )

    # 子命令五：sai study-path [--competition 关键字]（P5：备考路径 + 引用校验）
    study = sub.add_parser(
        "study-path",
        help="为考试型比赛生成备考学习路径（联网搜索 + 引用存在性校验）",
    )
    study.add_argument(
        "--competition", default=None,
        help="比赛名称关键字（默认优先取库里第一张考试型卡片）",
    )

    # 子命令六：sai cost [--task 名] [--today | --date 日期]（M1：查成本台账）
    cost = sub.add_parser("cost", help="查 LLM 花费账单（识别 10 条通知花了多少钱就问它）")
    cost.add_argument(
        "--task", default=None, choices=["identify", "generate", "study_path"],
        help="只看某个任务的账单（默认全部任务）",
    )
    cost.add_argument(
        "--today", action="store_true", help="只看今天的账单"
    )
    cost.add_argument(
        "--date", default=None, metavar="YYYY-MM-DD", help="只看指定某天的账单"
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


def _describe_prices(profile) -> str:
    """把模型档案的单价拼成一小段展示文字（sai model 列表用）。

    没配单价就什么都不显示——列表保持干净，也提示你去 config.yaml 补价格。
    """
    if profile.input_price_per_m is None or profile.output_price_per_m is None:
        return ""
    return f"（¥{profile.input_price_per_m}/¥{profile.output_price_per_m} 每百万 tok）"


def _run_scan(args: argparse.Namespace) -> int:
    """执行 sai scan：调 scan_site 用例拿通知，按人能读的格式打印。

    P1 阶段的"扫描"= 抓通知列表（+ 可选详情）。P2 会在同一条命令里
    接上 LLM 识别，把比赛卡片一起打出来。
    """
    from ..composition import build_scan_usecase

    detail_indexes = [args.detail] if args.detail is not None else []

    try:
        usecase = build_scan_usecase()
        notices = usecase.execute(
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

    # P3 起 scan 会把通知幂等写入台账，把账目亮出来
    if usecase.last_sync:
        print(
            f"\n台账入库：新增 {usecase.last_sync['new']} 条，"
            f"已存在 {usecase.last_sync['existing']} 条"
        )

    # 用户点名要的那条详情，打印正文
    if args.detail is not None and args.detail <= len(notices):
        notice = notices[args.detail - 1]
        print("\n" + "=" * 62)
        print(f"详情（第 {args.detail} 条）：{notice.title}")
        print("=" * 62)
        print(notice.content or "（正文为空：可能这条通知是图片/外链形式）")

    return 0


def _run_identify(args: argparse.Namespace) -> int:
    """执行 sai identify：扫描 -> 粗筛 -> LLM 识别，打印比赛卡片和拒绝理由。

    这是 P2 的主命令。每条通知的输出都带"理由"和"原文证据"——
    LLM 说它是比赛，就要拿出原文哪句话支持的证据，方便人工复核。
    """
    from ..composition import build_identify_usecase

    try:
        usecase = build_identify_usecase()
        outcomes = usecase.execute(limit=args.limit)
    except (ConnectionError, RuntimeError) as error:
        # RuntimeError 多为密钥没配；ConnectionError 是网络/重试耗尽
        print(f"识别失败：{error}")
        return 1

    competition_count = sum(1 for o in outcomes if o.is_competition)
    llm_count = sum(1 for o in outcomes if o.llm_called)
    print(
        f"共扫描 {len(outcomes)} 条通知，识别出比赛 {competition_count} 条"
        f"（粗筛挡下 {len(outcomes) - llm_count} 条，实际调用 LLM {llm_count} 次）\n"
    )

    # P3 起识别出的卡片会幂等入库，把账目亮出来
    if usecase.last_sync:
        print(
            f"卡片入库：新增 {usecase.last_sync['new']} 张，"
            f"已存在 {usecase.last_sync['existing']} 张\n"
        )

    # M1 预算闸门：熔断了要亮出来——已花钱的部分照常入库，但任务没跑完
    if usecase.budget_error:
        print(f"⚠️ {usecase.budget_error}")
        print("（已识别的卡片已入库；可调高 config.yaml 的 budget_per_task_yuan 后重跑）\n")

    type_names = {"deliverable": "交付物型", "exam": "考试型"}
    for number, outcome in enumerate(outcomes, start=1):
        mark = "✅ 比赛  " if outcome.is_competition else "❌ 非比赛"
        print(f"{number:>2}. {mark} | {outcome.notice.title}")
        print(f"     {outcome.notice.source_url}")
        print(f"     理由：{outcome.reason}")

        if outcome.is_competition and outcome.competition is not None:
            card = outcome.competition
            type_name = type_names.get(card.type, card.type)
            deadline = card.deadline.strftime("%Y-%m-%d") if card.deadline else "通知内未写"
            print(f"     卡片：{card.name} | {type_name} | 截止 {deadline}")
            print(f"     证据：{card.evidence}")
        print()

    return 0


def _run_report(args: argparse.Namespace) -> int:
    """执行 sai report：渲染 Markdown 报告，写入文件并打印到终端。

    报告默认写到 output/ 目录（该目录已被 gitignore：报告是产物，
    随时可以重新生成，不需要进版本库）。
    """
    from pathlib import Path

    from ..composition import build_report_usecase
    from ..settings import PROJECT_ROOT

    markdown = build_report_usecase().execute()

    out_path = (
        Path(args.out) if args.out else PROJECT_ROOT / "output" / "contest_report.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    print(f"报告已生成：{out_path}\n")
    print(markdown)
    return 0


def _run_generate(args: argparse.Namespace) -> int:
    """执行 sai generate：AgentScope 循环驱动材料生成，播报工具轨迹与成果。

    轨迹播报是刻意保留的：材料是 LLM 生成的，人必须能看到
    "它查了什么、写了什么文件"才敢放心用——这是 agent 产品的透明度底线。
    """
    from ..composition import build_generate_material_usecase

    try:
        usecase = build_generate_material_usecase()
        result = usecase.execute(
            skill_name=args.skill,
            competition_name=args.competition,
        )
    except (ConnectionError, RuntimeError, FileNotFoundError) as error:
        # RuntimeError：没卡片/没匹配比赛/没密钥；FileNotFoundError：技能名打错
        print(f"生成失败：{error}")
        return 1

    status = "完成" if result.success else f"失败：{result.error}"
    print(f"任务：为「{result.competition_name}」生成「{result.skill_name}」材料")
    print(f"工具调用 {len(result.tool_trace)} 次 ｜ 状态：{status}")

    # 工具轨迹播报：agent 干活的透明度底线
    if result.tool_trace:
        print("\n工具轨迹：")
        for line in result.tool_trace:
            print(f"  - {line}")

    print("-" * 62)
    print(result.final_text)
    print("-" * 62)
    if result.success:
        print("材料已保存到 output/ 目录，请用编辑器打开检查内容质量。")
        return 0
    return 1


def _run_study_path(args: argparse.Namespace) -> int:
    """执行 sai study-path：生成备考路径并对全部引用做存在性校验。

    输出里每个链接都带 ✅/❌ 标记——❌ 意味着程序验证过这个链接打不开，
    这类链接绝对不会原样出现在最终材料里（有死链会被打回重做）。
    """
    from ..composition import build_plan_study_path_usecase

    try:
        usecase = build_plan_study_path_usecase()
        result = usecase.execute(competition_name=args.competition)
    except (ConnectionError, RuntimeError, FileNotFoundError) as error:
        print(f"生成失败：{error}")
        return 1

    ok_count = sum(1 for c in result.citations if c["ok"])
    print(f"任务：为「{result.competition_name}」生成备考学习路径")
    status = "完成" if result.success else f"失败：{result.error or '仍有失效链接'}"
    print(f"引用校验：{ok_count}/{len(result.citations)} 通过 ｜ 状态：{status}")

    if result.tool_trace:
        print("\n工具轨迹：")
        for line in result.tool_trace:
            print(f"  - {line}")

    print("\n引用校验明细：")
    for citation in result.citations:
        mark = "✅" if citation["ok"] else "❌"
        print(f"  {mark} {citation['url']}")
        print(f"     {citation['note']}")

    print("-" * 62)
    print(result.final_text)
    print("-" * 62)
    if result.success:
        print(f"路径已保存到 output/{result.material_file}，请打开检查内容质量。")
        return 0
    return 1


def _run_cost(args: argparse.Namespace) -> int:
    """执行 sai cost：查成本台账，按任务/模型汇总打印（M1）。

    这就是 v2 验收题"识别 10 条通知花了多少钱"的标准答案入口：
    sai cost --task identify --today
    """
    from datetime import date as date_cls, datetime

    from ..composition import build_cost_report_usecase

    # --today 和 --date 二选一：都给了以 --today 为准（简单明确，不搞组合语义）
    on_date: date | None = None
    if args.today:
        on_date = date_cls.today()
    elif args.date:
        try:
            on_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"日期格式不对：{args.date!r}，应为 YYYY-MM-DD")
            return 1

    summary = build_cost_report_usecase().execute(task_type=args.task, on_date=on_date)

    # 范围说明放在第一行，避免"以为看的全部其实是今天"这种对账误会
    if args.today:
        scope = f"今天（{on_date.isoformat()}）"
    elif on_date is not None:
        scope = f"{on_date.isoformat()}"
    elif args.task:
        scope = f"任务 = {args.task}"
    else:
        scope = "全部"

    print(f"账单范围：{scope}\n")

    def _fmt_cost(cost: float | None, calls: int) -> str:
        """费用格式化：没配单价时如实显示"未知"，不编数字。"""
        if cost is None:
            return "费用未知（模型档案未配单价）" if calls else "¥0"
        return f"¥{cost:.4f}"

    total = summary.total
    if total.calls == 0:
        print("（还没有任何 LLM 调用记录。跑一次 sai identify 或 sai generate 再来看）")
        return 0

    print(
        f"总计：{total.calls} 次调用 ｜ 输入 {total.prompt_tokens:,} tok ｜ "
        f"输出 {total.completion_tokens:,} tok ｜ {_fmt_cost(total.cost_yuan, total.calls)}"
    )

    if summary.by_task:
        print("\n按任务：")
        for task_name, bucket in sorted(
            summary.by_task.items(), key=lambda item: -item[1].calls
        ):
            print(
                f"  {task_name:<12} {bucket.calls:>3} 次  "
                f"输入 {bucket.prompt_tokens:>8,}  输出 {bucket.completion_tokens:>7,}  "
                f"{_fmt_cost(bucket.cost_yuan, bucket.calls)}"
            )

    if summary.by_model:
        print("\n按模型：")
        for model_name, bucket in sorted(
            summary.by_model.items(), key=lambda item: -item[1].calls
        ):
            print(
                f"  {model_name:<20} {bucket.calls:>3} 次  {_fmt_cost(bucket.cost_yuan, bucket.calls)}"
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口。pyproject.toml 里注册的 sai 命令，最终执行的就是这个函数。

    argv 不传就默认解析命令行上的参数；测试时可以直接传列表进来。
    返回值是进程退出码：0 = 成功，非 0 = 失败（操作系统惯例）。
    """
    args = build_parser().parse_args(argv)

    if args.command == "scan":
        return _run_scan(args)

    if args.command == "identify":
        return _run_identify(args)

    if args.command == "report":
        return _run_report(args)

    if args.command == "generate":
        return _run_generate(args)

    if args.command == "study-path":
        return _run_study_path(args)

    if args.command == "model":
        # 在函数内部 import：只有真的执行到这个子命令才加载配置模块
        from ..settings import load_settings

        settings = load_settings()

        if args.action == "use" and args.name:
            # 真正的切换：校验档案存在 -> 写回 config.yaml -> 清配置缓存
            from ..settings import set_active_model

            try:
                set_active_model(args.name)
            except KeyError as error:
                print(f"切换失败：{error}")
                return 1
            print(f"已切换模型档案：{args.name}（已写回 config.yaml）")
            return 0

        # 默认动作是 list：打印档案列表，行首带 * 的表示当前生效
        print(f"当前档案：{settings.active_model}")
        for name, profile in settings.yaml_config.models.items():
            marker = "*" if name == settings.active_model else " "
            prices = _describe_prices(profile)
            print(f" {marker} {name:<10} {profile.model}{prices}")

        # M1 模型路由：展示"哪个任务用哪个档案"（没配的任务用当前档案兜底）
        if settings.yaml_config.routing:
            print("\n按任务路由（未列出的任务用当前档案）：")
            for task_name, routed in sorted(settings.yaml_config.routing.items()):
                print(f"  {task_name:<12} -> {routed}")
        return 0

    if args.command == "cost":
        return _run_cost(args)

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
