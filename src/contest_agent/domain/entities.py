"""领域实体：这个系统里最核心的两种"东西"——通知和比赛——的数据结构。

"领域（domain）"指的是业务本身，不掺任何技术细节。这一层的代码是全项目
最"纯"的：不允许 import FastAPI / SQLAlchemy / openai 等任何框架。
好处是：不管以后换爬虫库、换数据库、换模型供应商，这几个文件基本不用动。

P0 先把字段立起来，后续阶段落地时会补充调整。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def parse_date(text: str | None) -> datetime | None:
    """把日期字符串安全转成 datetime；解析不了就返回 None（绝不抛异常）。

    LLM 提取出来的日期格式没法保证（"2026-10-08"、"2026/10/8"、
    "2026年10月8日"都有可能），这里把见过的格式都试一遍；
    全失败返回 None——日期缺失不该让整张卡片作废。
    """
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None


@dataclass  # 装饰器：自动生成 __init__、__repr__ 等方法，效果类似 Java 里 Lombok 的 @Data
class Notice:
    """一条官网通知。P1 爬虫的产出物。"""

    # —— 必填字段（爬列表页就能拿到）——
    source_url: str   # 这条通知在官网的网址，也是整个系统里的"身份证号"
    title: str        # 通知标题

    # —— 详情字段（爬详情页后才补充，都有默认值，所以允许先建"半成品"对象）——
    published_at: datetime | None = None  # 发布时间；网页上没写或解析失败就是 None
    content: str = ""                     # 正文文本（只留文字，去掉 HTML 标签）
    attachments: list[str] = field(default_factory=list)
    # ↑ 注意这个写法：可变类型（列表）的默认值必须用 default_factory 生成新列表。
    #   如果直接写 attachments: list[str] = []，所有对象会共享同一个列表——
    #   给 A 加附件会凭空出现在 B 身上，这是 Python 的经典大坑


@dataclass
class Competition:
    """一条比赛卡片。P2（LLM 识别）的产出物，从通知里提炼出来的结构化信息。"""

    name: str            # 比赛名称，如 "蓝桥杯"
    notice_url: str      # 来源通知的网址（沿袭 Notice 的身份证号，方便溯源）
    type: str = "unknown"  # 比赛类型：deliverable=交付物型 / exam=考试型 / unknown=没识别出来
    deadline: datetime | None = None  # 报名或提交截止时间
    evidence: str = ""   # 原文证据片段：LLM 说这是比赛，就得指出来原文哪句话支持的——防幻觉


@dataclass
class UsageEntry:
    """一次 LLM 调用的"账单流水"（M1 成本台账）。

    每次调用大模型（不管走识别的结构化调用，还是走 agent 循环），
    都会记一条流水进 usage_records 表——就像银行对账单上的一行。
    有了流水，"识别 10 条通知花了多少钱"这类问题才答得出来。
    """

    task_type: str        # 这次调用属于哪个任务：identify / generate / study_path
    profile_name: str     # 用的哪个模型档案（如 deepseek）——模型路由的"台账可证"就靠它
    model: str            # 具体模型名（如 deepseek-chat），比档案名更细一层
    prompt_tokens: int    # 输入 token 数（服务商在响应里如实回报的）
    completion_tokens: int  # 输出 token 数
    cost_yuan: float | None = None  # 折算费用（元）。档案没配单价时是 None（记不了钱但记得量）
    note: str = ""        # 备注哪个比赛/哪次扫描，方便对账
    created_at: datetime | None = None  # 记账时间；仓储写入时自动补当前时间

# 历史注记（v1.5）：P4 曾自研过 ToolCall / LlmReply 实体和手写 ReAct 循环，
# v1.5 采纳 AgentScope 后由框架的消息模型接管（ADR-002）；
# 实体随 loop.py/registry.py 一同移除，git 历史可查。
