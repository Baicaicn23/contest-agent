"""M2 验收测试：持久记忆、会话存档、评测套件，全程不碰网络不花钱。

分层手法沿 P2-M1：
- 仓储用内存库测真 SQL（记忆/会话两张新表 + 台账按会话汇总）；
- 用例层用假 LLM / 假考卷测编排（记忆命中跳过 LLM、判卷打分、基线比对）；
- CLI 用假用例 + monkeypatch 测呈现。
真实 LLM 的验收（二次扫描 0 调用、sai eval 真跑 31 条）标了 live。
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from contest_agent.application.recorder import TaskRecorder
from contest_agent.application.usecases.evaluate_identification import (
    DatasetNoticeSource,
    EvaluateIdentification,
    _names_match,
    compare_with_baseline,
    load_dataset,
    save_baseline,
)
from contest_agent.application.usecases.identify_competitions import (
    _content_fingerprint,
    IdentifyCompetitions,
)
from contest_agent.domain.entities import Notice, UsageEntry
from contest_agent.infrastructure.persistence.repository import (
    SqliteMemoryRepository,
    SqliteSessionRepository,
    SqliteUsageRepository,
)


# ---------- 假对象 ----------


class FakeLlm:
    """假 LLM：按标题关键词给结论，并记录调用次数（验证"记忆命中就跳过"）。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete_structured(self, system: str, user: str, schema: dict) -> dict:
        self.calls += 1
        if "物理实验竞赛" in user:
            return {
                "is_competition": True, "name": "全国大学生物理实验竞赛校赛",
                "type": "deliverable", "deadline": "2025-06-03",
                "evidence": "报名截止6月3日", "reason": "竞赛通知",
            }
        return {"is_competition": False, "reason": "不是比赛"}


class FakeSource:
    """假爬虫：固定吐两条通知（一条物理实验竞赛、一条学业审核公示）。"""

    def list_notices(self, limit: int = 10) -> list[Notice]:
        return [
            Notice(source_url="u-comp", title="2025年全国大学生物理实验竞赛校赛通知"),
            Notice(source_url="u-plain", title="本科生学业状况审核结果公示",
                   content="学业审核结果如下"),
        ]

    def fetch_detail(self, notice: Notice) -> Notice:
        if notice.source_url == "u-comp":
            notice.content = "物理实验竞赛报名，截止2025年6月3日"
        return notice


class MemoryRepoFake:
    """内存版记忆仓储（测用例编排用，不建库）。"""

    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def remember(self, key: str, value: dict) -> None:
        self.store[key] = value

    def recall(self, key: str) -> dict | None:
        return self.store.get(key)

    def forget_all(self) -> int:
        n = len(self.store)
        self.store.clear()
        return n

    def list_entries(self, limit: int = 50) -> list:
        return []

    def count(self) -> int:
        return len(self.store)


class SessionRepoFake:
    """内存版会话仓储（测 recorder 与用例的事件编排）。"""

    def __init__(self) -> None:
        self.next_id = 1
        self.events: dict[int, list] = {}
        self.statuses: dict[int, str] = {}

    def create_session(self, task_type: str, note: str = "") -> int:
        sid = self.next_id
        self.next_id += 1
        self.events[sid] = []
        return sid

    def append_event(self, session_id: int, kind: str, payload: dict) -> None:
        self.events[session_id].append((kind, payload))

    def finish_session(self, session_id: int, status: str) -> None:
        self.statuses[session_id] = status

    def list_sessions(self, limit: int = 20) -> list:
        return []

    def get_session(self, session_id: int):
        raise KeyError(session_id)


# ---------- 持久记忆 ----------


def test_content_fingerprint_changes_with_content() -> None:
    """正文指纹：内容变指纹就变，内容不变指纹稳定——记忆失效判断的基石。"""
    notice = Notice(source_url="u", title="t", content="正文A")
    same = Notice(source_url="u", title="t", content="正文A")
    changed = Notice(source_url="u", title="t", content="正文B")
    assert _content_fingerprint(notice) == _content_fingerprint(same)
    assert _content_fingerprint(notice) != _content_fingerprint(changed)


def test_memory_repository_roundtrip() -> None:
    repo = SqliteMemoryRepository("sqlite:///:memory:")
    repo.remember("verdict:u1", {"is_competition": False, "reason": "公示"})
    repo.remember("verdict:u2", {"is_competition": True, "name": "蓝桥杯"})

    assert repo.count() == 2
    assert repo.recall("verdict:u1")["reason"] == "公示"
    assert repo.recall("missing") is None

    # 同 key 再记 = 覆盖更新（结论可以修正）
    repo.remember("verdict:u1", {"is_competition": True, "reason": "改判了"})
    assert repo.recall("verdict:u1")["is_competition"] is True
    assert repo.count() == 2

    assert repo.forget_all() == 2
    assert repo.count() == 0


def test_identify_second_run_hits_memory_zero_llm_calls() -> None:
    """M2 核心验收（离线版）：第一次识别调 LLM 并记住结论；
    第二次同样的通知全部命中记忆，一次 LLM 都不调。

    注意 FakeSource 里有条"学业审核公示"会被关键词粗筛挡下、根本不问 LLM，
    所以首次运行也只有 1 次调用——粗筛挡下的结论不进记忆（零成本的东西不值得记）。
    """
    memory = MemoryRepoFake()
    llm = FakeLlm()

    first = IdentifyCompetitions(FakeSource(), llm, memory=memory).execute(limit=2)
    assert llm.calls == 1           # 第一次：只有粗筛放行的那条问 LLM
    assert all(not o.from_memory for o in first)

    second = IdentifyCompetitions(FakeSource(), llm, memory=memory).execute(limit=2)
    assert llm.calls == 1           # 计数没涨 = 第二次 0 次调用
    # LLM 判过的那条必须命中记忆（粗筛挡下的那条不进记忆，也不该 from_memory）
    comp = next(o for o in second if o.is_competition)
    assert comp.from_memory is True
    assert comp.notice.source_url == "u-comp"
    # 结论一致：记忆命中的判断和 LLM 当时给的一样
    assert comp.competition.name == "全国大学生物理实验竞赛校赛"


def test_identify_memory_invalidated_when_content_changes() -> None:
    """正文变了记忆必须作废：旧结论不可信，重新调 LLM。"""
    memory = MemoryRepoFake()
    llm = FakeLlm()

    class MutableSource(FakeSource):
        """内容可控的爬虫：第二次扫描时正文变了。"""

        def __init__(self) -> None:
            self.competition_content = "物理实验竞赛报名，截止2025年6月3日"

        def fetch_detail(self, notice: Notice) -> Notice:
            if notice.source_url == "u-comp":
                notice.content = self.competition_content
            return notice

    source = MutableSource()
    IdentifyCompetitions(source, llm, memory=memory).execute(limit=2)
    assert llm.calls == 1

    source.competition_content = "物理实验竞赛报名，截止时间改为2025年6月10日"
    IdentifyCompetitions(source, llm, memory=memory).execute(limit=2)
    assert llm.calls == 2           # 变了的那条重判（另一条仍命中记忆/粗筛挡下）


# ---------- 会话存档 ----------


def test_session_repository_roundtrip(tmp_path: Path) -> None:
    """会话两表 CRUD + 台账按会话汇总。注意：台账和会话必须共用同一个库文件
    （两个 :memory: 是两个独立的库，互相看不见——第一版测试就栽在这里）。"""
    db_file = f"sqlite:///{tmp_path / 'shared.db'}"
    repo = SqliteSessionRepository(db_file)
    usage = SqliteUsageRepository(db_file)

    sid = repo.create_session("identify", "limit=2")
    repo.append_event(sid, "user_input", {"text": "识别最新 2 条通知"})
    repo.append_event(sid, "result", {"url": "u1", "is_competition": True})
    repo.finish_session(sid, "completed")

    # 台账按会话汇总：给这个会话记两笔账，概要里应能读出总花费
    usage.record(UsageEntry("identify", "deepseek", "deepseek-chat", 100, 10, 0.00028,
                            session_id=sid))
    usage.record(UsageEntry("identify", "deepseek", "deepseek-chat", 200, 20, 0.00056,
                            session_id=sid))

    summary, events = repo.get_session(sid)
    assert summary.task_type == "identify"
    assert summary.status == "completed"
    assert summary.event_count == 2
    assert summary.cost_yuan == pytest.approx(0.00028 + 0.00056)
    assert [e.seq for e in events] == [1, 2]     # 序号自动递增
    assert events[0].kind == "user_input"

    # 最近列表（新会话在前）
    sid2 = repo.create_session("generate", "")
    sessions = repo.list_sessions(limit=10)
    assert sessions[0].id == sid2
    assert sessions[1].id == sid

    with pytest.raises(KeyError):
        repo.get_session(999)


def test_task_recorder_without_archive_is_silent() -> None:
    """没配存档时 recorder 是哑巴：不炸、不记——测试和关闭存档的场景靠它。"""
    recorder = TaskRecorder(None, "identify")
    assert recorder.session_id is None
    recorder.log("user_input", text="hi")   # 不应抛异常
    recorder.finish("completed")


def test_identify_records_session_events_and_status() -> None:
    """识别全程写会话事件：输入、逐条结果、completed 戳；熔断时盖 budget_break。"""
    repo = SessionRepoFake()
    recorder = TaskRecorder(repo, "identify", "limit=2")
    usecase = IdentifyCompetitions(FakeSource(), FakeLlm(), recorder=recorder)
    usecase.execute(limit=2)

    kinds = [k for k, _ in repo.events[recorder.session_id]]
    assert kinds[0] == "user_input"
    assert kinds.count("result") == 2
    assert repo.statuses[recorder.session_id] == "completed"

    # 熔断场景：第一次 LLM 调用就熔断 -> 没有任何结果、盖 budget_break
    from contest_agent.application.cost import BudgetExceededError

    class BreakImmediately:
        def complete_structured(self, system: str, user: str, schema: dict) -> dict:
            raise BudgetExceededError("预算熔断：已达上限")

    repo2 = SessionRepoFake()
    recorder2 = TaskRecorder(repo2, "identify")
    usecase2 = IdentifyCompetitions(FakeSource(), BreakImmediately(), recorder=recorder2)
    outcomes = usecase2.execute(limit=2)
    assert len(outcomes) == 0       # 第一条就熔断，没有任何结果
    assert usecase2.budget_error is not None
    assert repo2.statuses[recorder2.session_id] == "budget_break"


# ---------- 评测套件 ----------


@pytest.fixture
def tiny_dataset(tmp_path: Path) -> Path:
    """迷你考卷：3 道题（2 比赛 1 非比赛），够测判卷和基线比对。"""
    dataset = [
        {"source_url": "u1", "title": "物理实验竞赛通知", "content": "报名从速",
         "expected": {"is_competition": True, "name": "物理实验竞赛",
                      "type": "deliverable", "deadline": "2025-06-03"}},
        {"source_url": "u2", "title": "蓝桥杯报名通知", "content": "蓝桥杯大赛报名",
         "expected": {"is_competition": True, "name": "蓝桥杯", "type": "exam"}},
        {"source_url": "u3", "title": "助教招聘名单公示", "content": "名单如下",
         "expected": {"is_competition": False}},
    ]
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_dataset_validates_contract(tmp_path: Path) -> None:
    """考卷契约：缺字段/不是数组要在加载时立刻报错，不能等到花完钱才发现。"""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps([{"source_url": "u", "title": "t", "content": "c"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected"):
        load_dataset(bad)

    empty = tmp_path / "empty.json"
    empty.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="非空"):
        load_dataset(empty)


def test_dataset_source_serves_frozen_content(tiny_dataset: Path) -> None:
    """考卷数据源：内容来自考卷而不是网络，且截到 limit。"""
    items = load_dataset(tiny_dataset)
    source = DatasetNoticeSource(items)
    notices = source.list_notices(limit=2)
    assert len(notices) == 2
    assert notices[0].content == "报名从速"
    # 评测绝不碰网络：fetch_detail 原样返回
    assert source.fetch_detail(notices[0]) is notices[0]


def test_names_match_allows_containment() -> None:
    """比赛名按"去空格后互相包含"算对上——考认对比赛，不考起一样的名字。"""
    assert _names_match("全国大学生数学竞赛", "第十八届全国大学生数学竞赛新疆赛区竞赛")
    assert _names_match("蓝桥杯", "蓝桥杯")
    assert _names_match("蓝桥杯", "计算机设计大赛") is False


def test_eval_scores_with_fake_llm(tiny_dataset: Path) -> None:
    """判卷全流程：假 LLM 全答对 -> 满分；答错一条 -> 指标随之变化。"""

    class PerfectLlm:
        def complete_structured(self, system: str, user: str, schema: dict) -> dict:
            if "物理实验竞赛" in user:
                return {"is_competition": True, "name": "物理实验竞赛",
                        "type": "deliverable", "deadline": "2025-06-03"}
            if "蓝桥杯" in user:
                return {"is_competition": True, "name": "蓝桥杯", "type": "exam"}
            return {"is_competition": False}

        # 假 LLM 直接收标题文本（DatasetNoticeSource 的通知有正文，
        # 走完整 identify 用例时 user 是拼好的提示词，包含标题）

    report = EvaluateIdentification(PerfectLlm(), dataset_path=tiny_dataset).execute()
    assert report.total == 3
    assert report.accuracy == 1.0
    assert report.precision == 1.0 and report.recall == 1.0 and report.f1 == 1.0
    # 注意：助教公示那条被粗筛挡下、根本不问 LLM——粗筛也是被测系统的一部分
    assert report.llm_calls == 2
    assert report.type_hits == 2

    class MissesOne(PerfectLlm):
        """故意把物理实验竞赛说成非比赛：召回率掉到 1/2，准确率 2/3。"""

        def complete_structured(self, system: str, user: str, schema: dict) -> dict:
            if "物理实验竞赛" in user:
                return {"is_competition": False, "reason": "看走眼了"}
            return super().complete_structured(system, user, schema)

    report2 = EvaluateIdentification(MissesOne(), dataset_path=tiny_dataset).execute()
    assert report2.accuracy == pytest.approx(2 / 3)
    assert report2.recall == pytest.approx(0.5)


def test_baseline_save_and_regression_compare(tmp_path: Path, tiny_dataset: Path) -> None:
    """基线闭环：--save 存成绩；下次跑分掉了 -> 比对报 regressed 并点名判翻的题。"""
    baseline_path = tmp_path / "baseline.json"

    class PerfectLlm:
        def complete_structured(self, system: str, user: str, schema: dict) -> dict:
            if "物理实验竞赛" in user:
                return {"is_competition": True, "name": "物理实验竞赛",
                        "type": "deliverable", "deadline": "2025-06-03"}
            if "蓝桥杯" in user:
                return {"is_competition": True, "name": "蓝桥杯", "type": "exam"}
            return {"is_competition": False}

    report = EvaluateIdentification(PerfectLlm(), dataset_path=tiny_dataset).execute()
    save_baseline(report, path=baseline_path)

    # 第一次没有基线时的提示
    empty_compare = compare_with_baseline(report, path=tmp_path / "nope.json")
    assert empty_compare["status"] == "no_baseline"

    # 同样的成绩再跑：PASS
    same = compare_with_baseline(report, path=baseline_path)
    assert same["status"] == "pass"

    # 退化场景：蓝桥杯被漏判 -> 基线里它原本是对的 -> 点名 + regressed
    class Degraded(PerfectLlm):
        def complete_structured(self, system: str, user: str, schema: dict) -> dict:
            if "蓝桥杯" in user:
                return {"is_competition": False, "reason": "看走眼了"}
            return super().complete_structured(system, user, schema)

    report2 = EvaluateIdentification(Degraded(), dataset_path=tiny_dataset).execute()
    compare = compare_with_baseline(report2, path=baseline_path)
    assert compare["status"] == "regressed"
    assert any("蓝桥杯" in line for line in compare["regressions"])


# ---------- CLI（假用例，测呈现层） ----------


def test_sai_memory_list_and_clear(monkeypatch, capsys) -> None:
    import contest_agent.composition as composition_module
    import contest_agent.presentation.cli as cli_module
    from contest_agent.application.usecases.memory_report import MemoryReport
    from contest_agent.domain.entities import MemoryEntry

    class FakeMemoryPort:
        def remember(self, key, value): ...

        def recall(self, key): return None

        def forget_all(self): return 2

        def list_entries(self, limit=50):
            return [MemoryEntry(key="verdict:u1", value={"is_competition": False, "reason": "公示"},
                                updated_at=datetime(2026, 9, 30, 12, 0))]

        def count(self): return 1

    monkeypatch.setattr(composition_module, "build_memory_report_usecase",
                        lambda: MemoryReport(FakeMemoryPort()))

    assert cli_module.main(["memory"]) == 0
    out = capsys.readouterr().out
    assert "共 1 条" in out and "非比赛" in out

    assert cli_module.main(["memory", "clear"]) == 0
    assert "删掉 2 条" in capsys.readouterr().out


def test_sai_sessions_and_replay(monkeypatch, capsys) -> None:
    import contest_agent.composition as composition_module
    import contest_agent.presentation.cli as cli_module
    from contest_agent.application.usecases.session_report import SessionReport
    from contest_agent.domain.entities import SessionEvent, SessionSummary

    class FakeArchive:
        def list_sessions(self, limit=20):
            return [SessionSummary(id=7, task_type="identify", note="limit=10",
                                   status="completed", started_at=datetime(2026, 9, 30, 9, 0),
                                   ended_at=datetime(2026, 9, 30, 9, 1),
                                   event_count=3, cost_yuan=0.0173, llm_calls=4)]

        def get_session(self, session_id):
            if session_id != 7:
                raise KeyError(f"会话 {session_id} 不存在")
            summary = self.list_sessions()[0]
            events = [
                SessionEvent(seq=1, kind="user_input", payload={"text": "识别最新 10 条通知"}),
                SessionEvent(seq=2, kind="model_call",
                             payload={"messages": 2, "input_tokens": 700, "output_tokens": 90,
                                      "blocks": ["TextBlock"]}),
                SessionEvent(seq=3, kind="result",
                             payload={"url": "u1", "is_competition": True}),
            ]
            return summary, events

    monkeypatch.setattr(composition_module, "build_session_report_usecase",
                        lambda: SessionReport(FakeArchive()))

    assert cli_module.main(["sessions"]) == 0
    out = capsys.readouterr().out
    assert "#7" in out and "完成" in out and "¥0.0173" in out

    assert cli_module.main(["replay", "7"]) == 0
    out = capsys.readouterr().out
    assert "模型调用" in out and "输入 700 tok" in out

    assert cli_module.main(["replay", "999"]) == 1
    assert "不存在" in capsys.readouterr().out


def test_sai_eval_with_tiny_dataset(monkeypatch, capsys, tmp_path: Path) -> None:
    """sai eval 离线全流程：迷你考卷 + 假用例（真实跑 LLM 的版本标 live）。"""
    import contest_agent.presentation.cli as cli_module
    from contest_agent.application.usecases.evaluate_identification import (
        EvalReport, ItemResult,
    )

    class FakeEvalUsecase:
        def __init__(self, dataset_path=None) -> None:
            assert dataset_path is not None  # --dataset 传进来了

        def execute(self, limit=None) -> EvalReport:
            report = EvalReport(total=3, accuracy=2 / 3, precision=1.0, recall=0.5, f1=2 / 3,
                                llm_calls=3)
            report.items = [
                ItemResult("u1", "物理实验竞赛通知", True, False, False, reason="看走眼了"),
                ItemResult("u2", "蓝桥杯报名通知", True, True, True),
                ItemResult("u3", "助教招聘名单公示", False, False, True),
            ]
            return report

    import contest_agent.composition as composition_module
    monkeypatch.setattr(composition_module, "build_eval_usecase", FakeEvalUsecase)

    dataset = tmp_path / "d.json"
    dataset.write_text("[]", encoding="utf-8")
    baseline_dir = tmp_path / "out"
    monkeypatch.setattr("contest_agent.application.usecases.evaluate_identification.DEFAULT_BASELINE_PATH",
                        baseline_dir / "baseline.json")

    # 无基线 + 不 --save：给出"先建基线"的提示
    assert cli_module.main(["eval", "--dataset", str(dataset)]) == 0
    assert "还没有基线" in capsys.readouterr().out

    # --save 建基线
    assert cli_module.main(["eval", "--dataset", str(dataset), "--save"]) == 0
    assert "已保存基线" in capsys.readouterr().out

    # 再跑一次（成绩没变但基线里 u1 判错、这次也错？不——基线里 u1 就是错的，
    # 两次一致 = pass）
    exit_code = cli_module.main(["eval", "--dataset", str(dataset)])
    out = capsys.readouterr().out
    assert "相比基线" in out
    assert exit_code == 0
