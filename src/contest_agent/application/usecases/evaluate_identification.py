"""evaluate_identification 用例：识别能力的"定期考试 + 防退化比对"（M2 评测套件）。

解决的问题是：改了识别提示词（或换了模型/改了粗筛词表），怎么知道
"识别质量是变好了还是变坏了"？凭感觉翻一两条看，等于没考。

做法（借鉴 pi-telemetry 的"契约 + 一致性测试"思想）：
1. **固定考卷**：tests/fixtures/eval_identify.json 存 30 条真实历史通知
   （标题 + 正文 + 人工标注的期望结果）——考卷进 git，永不悄悄变；
2. **同样的流程考一遍**：把考卷塞给和线上完全相同的识别用例
   （只换数据源为"考卷数据源"、关闭记忆——考的是 LLM 本身，不是缓存）；
3. **打分**：对 is_competition 算准确率/精确率/召回率/F1；
   对卡片字段（类型、截止日期）算命中率；
4. **回归比对**：`sai eval --save` 把本次成绩存成基线；以后每次跑，
   和基线比——准确率掉了、或哪条"原来对现在错"，报告里点名。

约定（这是"契约"部分，别破坏）：
- 数据集 JSON 里每个条目必须有 source_url / title / content / expected；
- expected.is_competition 必填；是比赛时 name/type/deadline 尽量给全；
- 改了 IDENTIFY_SYSTEM_PROMPT、keyword_filter 词表、模型路由之后必须跑：
  uv run sai eval（对比基线）——这是"改提示词必跑"的制度。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ...domain.entities import Notice, parse_date
from ...settings import PROJECT_ROOT
from .identify_competitions import IdentifyCompetitions, ScanOutcome

# 默认考卷位置：项目根 tests/fixtures/eval_identify.json（进 git 的契约文件）
DEFAULT_DATASET_PATH = PROJECT_ROOT / "tests" / "fixtures" / "eval_identify.json"

# 基线默认存这里：output/ 目录是 gitignore 的产物目录，
# 基线是"本机最近一次成绩"，不是资产，所以不进 git
DEFAULT_BASELINE_PATH = PROJECT_ROOT / "output" / "eval_baseline.json"

# 回归判定阈值：核心指标比基线掉超过 5 个百分点就报 REGRESSED。
# 定 5 而不是 0：单条通知判翻就会引起 3pp 左右的波动（30 条的考卷），
# 完全不容忍波动会天天误报；5pp 以上基本必然是真空化
REGRESSION_THRESHOLD = 0.05

# 评测走的新任务类型：台账里和日常 identify 分开记账，
# "今天识别花了多少钱"（identify）不会被考试花费（eval）污染
EVAL_TASK_TYPE = "eval"


@dataclass
class EvalItem:
    """考卷上的一道题：一条真实通知 + 人工标注的期望结果。"""

    source_url: str
    title: str
    content: str
    expected: dict  # {is_competition: bool, name?, type?, deadline?}


@dataclass
class ItemResult:
    """一道题的判卷结果。"""

    source_url: str
    title: str
    expected_competition: bool
    predicted_competition: bool
    competition_correct: bool       # 是否比赛判断对了（主得分）
    type_correct: bool | None = None    # 类型对了吗（只在"期望是比赛"的题上判；None=不判）
    deadline_correct: bool | None = None  # 截止日期对了吗（同上）
    reason: str = ""                # 识别给出的理由（人复核用）


@dataclass
class EvalReport:
    """一次考试的总成绩单。"""

    total: int = 0
    accuracy: float = 0.0           # 是否比赛判断对的比例（主指标）
    precision: float = 0.0          # 报了比赛的里面真比赛占多少（误报的倒数）
    recall: float = 0.0             # 真比赛里被报出来多少（漏报的倒数）
    f1: float = 0.0                 # 精确率与召回率的调和平均
    type_hits: int = 0              # 类型判对的题数
    type_total: int = 0             # 有类型可比的题数
    deadline_hits: int = 0          # 截止日期判对的题数
    deadline_total: int = 0         # 有截止日期可比的题数
    llm_calls: int = 0              # 这次考试实际调了几次 LLM（粗筛挡下的不算）
    items: list[ItemResult] = field(default_factory=list)

    def summary_dict(self) -> dict:
        """指标部分的字典形态（存基线 / HTTP 返回共用，格式即契约）。"""
        return {
            "total": self.total,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "type_hits": self.type_hits,
            "type_total": self.type_total,
            "deadline_hits": self.deadline_hits,
            "deadline_total": self.deadline_total,
            "llm_calls": self.llm_calls,
        }


def load_dataset(path: Path | None = None) -> list[EvalItem]:
    """读考卷并校验格式（这一步就是"契约检查"：少字段/类型不对当场报错）。

    校验放在加载时而不是打分时——考卷本身坏了要第一时间发现，
    而不是跑完 30 次 LLM 调用（花了钱）才发现第 17 行少个字段。
    """
    dataset_path = path or DEFAULT_DATASET_PATH
    raw_items = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError(f"考卷 {dataset_path} 应是非空 JSON 数组")

    items: list[EvalItem] = []
    for index, raw in enumerate(raw_items):
        for required in ("source_url", "title", "content", "expected"):
            if required not in raw:
                raise ValueError(f"考卷第 {index} 条缺少字段 {required!r}")
        expected = raw["expected"]
        if not isinstance(expected, dict) or "is_competition" not in expected:
            raise ValueError(f"考卷第 {index} 条的 expected 必须含 is_competition")
        items.append(
            EvalItem(
                source_url=raw["source_url"],
                title=raw["title"],
                content=raw.get("content", ""),
                expected=expected,
            )
        )
    return items


def _names_match(expected_name: str | None, predicted_name: str | None) -> bool:
    """比赛名是否算"对上"：完全一致或一方包含另一方（去空格后比较）。

    模型起名和人工标注几乎不可能逐字一致（"第十八届全国大学生数学竞赛
    新疆赛区竞赛（全国初赛）" vs "全国大学生数学竞赛"），包含关系就算对——
    考的是"认对了比赛"，不是"起了一样的名字"。
    """

    def norm(name: str | None) -> str:
        return (name or "").replace(" ", "").replace("　", "")

    a, b = norm(expected_name), norm(predicted_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


class DatasetNoticeSource:
    """考卷数据源：实现 NoticeSourcePort，但数据来自固定考卷而非网络。

    这是评测"可复现"的关键——同一个数据集不管什么时候考、考多少遍，
    输入一字不差，分数的波动只可能来自被测对象（提示词/模型）本身。
    """

    def __init__(self, items: list[EvalItem]):
        self._items = items

    def list_notices(self, limit: int = 10) -> list[Notice]:
        notices = [
            Notice(source_url=item.source_url, title=item.title, content=item.content)
            for item in self._items
        ]
        return notices[:limit]

    def fetch_detail(self, notice: Notice) -> Notice:
        """考卷里的正文已经齐了，直接原样返回（评测绝不碰网络）。"""
        return notice


class EvaluateIdentification:
    """组织一场识别能力考试：发卷 -> 答题 -> 判卷 -> 出成绩单。"""

    def __init__(
        self,
        llm,
        dataset_path: Path | None = None,
        meter=None,
    ):
        # llm 注入的是真实的 LlmPort 实现（考试就是要考真模型）；
        # meter 注入计价器——考试花费也要进台账，但记在 eval 任务名下
        self._llm = llm
        self._dataset_path = dataset_path
        self._meter = meter

    def execute(self, limit: int | None = None) -> EvalReport:
        """跑完整场考试，返回成绩单（并自动和基线比对，见 compare_baseline）。"""
        items = load_dataset(self._dataset_path)
        if limit is not None:
            items = items[:limit]

        # 关键配置：memory=None（考 LLM 不考缓存）、recorder=None
        #（考试轨迹不进会话存档——sai sessions 回放的是"真实任务"，不是模拟考）
        identify = IdentifyCompetitions(
            source=DatasetNoticeSource(items),
            llm=self._llm,
            competition_store=None,   # 考试不往正式卡片库里写数据
            memory=None,
            recorder=None,
        )
        started = datetime.now()
        outcomes = identify.execute(limit=len(items))
        report = self._score(items, outcomes)
        report.llm_calls = sum(1 for o in outcomes if o.llm_called)
        return report

    def _score(self, items: list[EvalItem], outcomes: list[ScanOutcome]) -> EvalReport:
        """判卷：逐题比对期望与预测，汇总出指标。"""
        by_url = {o.notice.source_url: o for o in outcomes}
        report = EvalReport(total=len(items))

        true_positive = false_positive = false_negative = 0
        for item in items:
            outcome = by_url.get(item.source_url)
            predicted = outcome.is_competition if outcome else False
            expected = bool(item.expected.get("is_competition"))

            result = ItemResult(
                source_url=item.source_url,
                title=item.title,
                expected_competition=expected,
                predicted_competition=predicted,
                competition_correct=(predicted == expected),
                reason=outcome.reason if outcome else "（没跑到这条）",
            )

            # 混淆矩阵四格：算 precision / recall 用
            if expected and predicted:
                true_positive += 1
            elif not expected and predicted:
                false_positive += 1
            elif expected and not predicted:
                false_negative += 1

            # 是比赛的题才判类型和截止日期（非比赛没有这些字段可比）
            if expected and predicted:
                report.type_total += 1
                if _names_match(item.expected.get("name"),
                                outcome.competition.name if outcome.competition else None):
                    report.type_hits += 1
                    result.type_correct = True
                else:
                    result.type_correct = False
                expected_deadline = parse_date(item.expected.get("deadline"))
                predicted_deadline = outcome.competition.deadline if outcome.competition else None
                if expected_deadline is not None and predicted_deadline is not None:
                    report.deadline_total += 1
                    same = expected_deadline.date() == predicted_deadline.date()
                    report.deadline_hits += 1 if same else 0
                    result.deadline_correct = same

            report.items.append(result)

        correct = sum(1 for r in report.items if r.competition_correct)
        report.accuracy = correct / report.total if report.total else 0.0
        report.precision = (true_positive / (true_positive + false_positive)
                            if true_positive + false_positive else 0.0)
        report.recall = (true_positive / (true_positive + false_negative)
                         if true_positive + false_negative else 0.0)
        if report.precision + report.recall:
            report.f1 = 2 * report.precision * report.recall / (report.precision + report.recall)
        return report


def save_baseline(report: EvalReport, path: Path | None = None) -> Path:
    """把成绩存成本基线（sai eval --save 的后端）。返回基线文件路径。"""
    baseline_path = path or DEFAULT_BASELINE_PATH
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "metrics": report.summary_dict(),
        # 逐题的期望/预测也存进去：比对时能精确指出"哪一条从对变错"
        "items": [
            {
                "source_url": r.source_url,
                "expected_competition": r.expected_competition,
                "predicted_competition": r.predicted_competition,
                "competition_correct": r.competition_correct,
            }
            for r in report.items
        ],
    }
    baseline_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return baseline_path


def compare_with_baseline(report: EvalReport, path: Path | None = None) -> dict:
    """和基线比对，返回人能读的比对结论（没有基线就返回提示新建）。"""
    baseline_path = path or DEFAULT_BASELINE_PATH
    if not baseline_path.exists():
        return {
            "status": "no_baseline",
            "message": "还没有基线：首次运行请加 --save 建立基线，之后的运行才会做回归比对。",
        }

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    old = baseline.get("metrics", {})
    accuracy_delta = report.accuracy - old.get("accuracy", 0.0)
    f1_delta = report.f1 - old.get("f1", 0.0)

    # 逐题翻车检测：基线里判对、这次判错的题，逐条点名
    old_by_url = {i["source_url"]: i for i in baseline.get("items", [])}
    regressions: list[str] = []
    improvements: list[str] = []
    for r in report.items:
        old_item = old_by_url.get(r.source_url)
        if old_item is None:
            continue
        was_right = bool(old_item.get("competition_correct"))
        if was_right and not r.competition_correct:
            regressions.append(f"{r.title}（期望比赛={r.expected_competition}，这次判反了）")
        elif not was_right and r.competition_correct:
            improvements.append(r.title)

    regressed = accuracy_delta < -REGRESSION_THRESHOLD or f1_delta < -REGRESSION_THRESHOLD
    return {
        "status": "regressed" if regressed else "pass",
        "baseline_run_at": baseline.get("run_at"),
        "accuracy_delta": round(accuracy_delta, 4),
        "f1_delta": round(f1_delta, 4),
        "regressions": regressions,
        "improvements": improvements,
        "message": (
            f"相比基线：准确率 {accuracy_delta:+.1%}，F1 {f1_delta:+.1%}；"
            f"判翻 {len(regressions)} 条，判对 {len(improvements)} 条。"
            + ("低于阈值，判定为退化！" if regressed else "在正常波动范围内。")
        ),
    }
