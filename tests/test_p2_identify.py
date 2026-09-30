"""P2 验收测试：粗筛、宽容解析、识别用例的编排逻辑，全程不碰网络不花钱。

分层手法与 P1 一致：
- 纯函数（粗筛、JSON 解析、日期解析）直接测；
- LLM 客户端用"假客户端"测（只测它怎么解析响应，不发真请求）；
- 用例层用 FakeSource + FakeLlm 测编排（该调 LLM 的才调、卡片字段对不对）；
- 真实调用 DeepSeek 的集成测试标了 live，默认不跑（见 pyproject addopts）。
"""

import os
from datetime import datetime

import pytest

from contest_agent.application.keyword_filter import keyword_hit
from contest_agent.application.usecases.identify_competitions import (
    IdentifyCompetitions,
)
from contest_agent.domain.entities import Notice, parse_date
from contest_agent.infrastructure.llm.openai_compat import (
    OpenAiCompatLlm,
    parse_json_loose,
)
from contest_agent.settings import ModelProfile, set_active_model


# ---------- 关键词粗筛 ----------


def test_keyword_filter_hits_competition_words() -> None:
    assert keyword_hit("关于组织参加2026第十四届数媒科技作品及创意竞赛的通知") == "竞赛"
    assert keyword_hit("第43次CCF CSP认证报名通知") == "认证"
    assert keyword_hit("蓝桥杯大赛报名开始") in ("大赛", "报名")


def test_keyword_filter_misses_daily_notices() -> None:
    assert keyword_hit("2026-2027学年秋季学期本科生学业状况审核结果公示") is None
    assert keyword_hit("研究生助教拟招聘名单公示") is None
    assert keyword_hit("2027年接收推免生复试成绩公示") is None


# ---------- 宽容 JSON 解析 ----------


def test_parse_json_loose_plain() -> None:
    assert parse_json_loose('{"a": 1}') == {"a": 1}


def test_parse_json_loose_fenced() -> None:
    """有的服务商爱包 Markdown 代码围栏，必须剥掉。"""
    raw = '```json\n{"is_competition": true, "name": "蓝桥杯"}\n```'
    assert parse_json_loose(raw)["name"] == "蓝桥杯"


def test_parse_json_loose_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_json_loose("我觉得这条通知不是比赛。")


# ---------- 日期解析（domain 工具） ----------


def test_parse_date_formats() -> None:
    assert parse_date("2026-10-08") == datetime(2026, 10, 8)
    assert parse_date("2026/10/8") == datetime(2026, 10, 8)
    assert parse_date("2026年10月8日") == datetime(2026, 10, 8)
    assert parse_date("详见通知") is None
    assert parse_date(None) is None


# ---------- LLM 客户端（假客户端，不发真请求） ----------

# 下面这组小类是"假 openai 客户端"：它的接口形状和真客户端一样
# （chat.completions.create 返回 resp.choices[0].message.content），
# 但内容是我们写死的——这样能测 OpenAiCompatLlm 收到响应后的处理逻辑。


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = _StubMessage(content)


class _StubResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_StubChoice(content)]


class _StubCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.call_count = 0

    def create(self, **kwargs) -> _StubResponse:
        self.call_count += 1
        return _StubResponse(self._content)


class _StubChat:
    def __init__(self, completions: _StubCompletions) -> None:
        self.completions = completions


class _StubClient:
    def __init__(self, content: str) -> None:
        self._completions = _StubCompletions(content)
        self.chat = _StubChat(self._completions)

    @property
    def call_count(self) -> int:
        return self._completions.call_count


def _llm_with_stub(content: str) -> tuple[OpenAiCompatLlm, _StubClient]:
    """造一个"带假客户端的 LLM"。密钥用环境变量临时塞一个。"""
    os.environ.setdefault("FAKE_KEY_ENV", "fake-key")
    profile = ModelProfile(
        name="stub", base_url="https://stub.example", api_key_env="FAKE_KEY_ENV", model="stub-model"
    )
    stub = _StubClient(content)
    return OpenAiCompatLlm(profile, client=stub), stub


def test_llm_client_parses_fenced_response() -> None:
    llm, stub = _llm_with_stub('```json\n{"is_competition": false}\n```')

    result = llm.complete_structured(system="s", user="u")

    assert result == {"is_competition": False}
    assert stub.call_count == 1


def test_llm_client_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("FAKE_KEY_ENV", raising=False)
    profile = ModelProfile(
        name="stub", base_url="https://stub.example", api_key_env="FAKE_KEY_ENV", model="m"
    )
    with pytest.raises(RuntimeError, match="FAKE_KEY_ENV"):
        OpenAiCompatLlm(profile)


# ---------- 识别用例的编排逻辑（Fake 爬虫 + Fake LLM） ----------


class FakeSource:
    """内存假爬虫：通知是预置的，详情抓取只是把 content 填上。"""

    def __init__(self, notices: list[Notice]) -> None:
        self._notices = notices
        self.detail_calls: list[str] = []

    def list_notices(self, limit: int = 10) -> list[Notice]:
        return self._notices[:limit]

    def fetch_detail(self, notice: Notice) -> Notice:
        self.detail_calls.append(notice.source_url)
        notice.content = f"{notice.title}的正文，报名截止2026-10-08"
        return notice


class FakeLlm:
    """内存假 LLM：按顺序吐预设卡片，并记下每次收到的提示词。"""

    def __init__(self, cards: list[dict]) -> None:
        self._cards = list(cards)
        self.prompts: list[str] = []

    def complete_structured(self, system: str, user: str, schema: dict | None = None) -> dict:
        self.prompts.append(user)
        return self._cards.pop(0) if self._cards else {"is_competition": False}


def test_identify_skips_llm_on_prefilter_miss() -> None:
    notice = Notice(source_url="u1", title="研究生助教拟招聘名单公示")
    fake_llm = FakeLlm(cards=[])

    outcomes = IdentifyCompetitions(FakeSource([notice]), fake_llm).execute()

    assert len(outcomes) == 1
    assert outcomes[0].is_competition is False
    assert outcomes[0].llm_called is False
    assert "粗筛" in outcomes[0].reason
    assert fake_llm.prompts == []  # 一分钱没花


def test_identify_fetches_detail_and_calls_llm() -> None:
    """粗筛命中但没正文：先补详情，LLM 收到的提示词里要有正文。"""
    notice = Notice(source_url="u2", title="关于数媒竞赛报名的通知")  # 无正文
    source = FakeSource([notice])
    fake_llm = FakeLlm(cards=[{"is_competition": False, "reason": "测试"}])

    outcomes = IdentifyCompetitions(source, fake_llm).execute()

    assert source.detail_calls == ["u2"]           # 补抓了详情
    assert "报名截止2026-10-08" in fake_llm.prompts[0]  # 正文进了提示词
    assert outcomes[0].is_competition is False


def test_identify_builds_competition_card() -> None:
    notice = Notice(source_url="u3", title="数媒竞赛报名通知")
    source = FakeSource([notice])
    fake_llm = FakeLlm(
        cards=[
            {
                "is_competition": True,
                "name": "全国大学生数字媒体科技作品及创意竞赛",
                "type": "deliverable",
                "deadline": "2026-10-08",
                "evidence": "关于组织参加2026第十四届全国大学生数字媒体科技作品及创意竞赛的通知",
                "reason": "面向学生征集参赛作品的竞赛通知",
            }
        ]
    )

    outcome = IdentifyCompetitions(source, fake_llm).execute()[0]

    assert outcome.is_competition is True
    card = outcome.competition
    assert card is not None
    assert card.name == "全国大学生数字媒体科技作品及创意竞赛"
    assert card.type == "deliverable"
    assert card.deadline == datetime(2026, 10, 8)   # 字符串被转成了日期对象
    assert card.notice_url == "u3"                  # 溯源字段来自通知
    assert "竞赛" in card.evidence


# ---------- 模型切换写回 config.yaml ----------


def test_set_active_model_rewrites_only_that_line(tmp_path) -> None:
    """切换档案只动 active_model 一行，文件里的注释必须原样保留。"""
    import shutil

    from contest_agent.settings import PROJECT_ROOT, load_yaml_config

    target = tmp_path / "config.yaml"
    shutil.copy(PROJECT_ROOT / "config.yaml", target)

    set_active_model("qwen", config_path=target)

    content = target.read_text(encoding="utf-8")
    assert "active_model: qwen" in content
    assert "爬虫限速" in content  # 中文注释还在 = 没被 yaml 重写冲掉
    assert load_yaml_config(target).active_model == "qwen"


def test_set_active_model_rejects_unknown_name(tmp_path) -> None:
    import shutil

    from contest_agent.settings import PROJECT_ROOT

    target = tmp_path / "config.yaml"
    shutil.copy(PROJECT_ROOT / "config.yaml", target)

    with pytest.raises(KeyError, match="不存在"):
        set_active_model("不存在的档案", config_path=target)


# ---------- 真实联网集成测试（默认不跑） ----------


@pytest.mark.live
def test_live_identify_real_notices() -> None:
    """验收标准：真实扫描最近 5 条，正负样本判断正确、卡片带原文证据。

    运行：uv run pytest -m live（需要 .env 里配置 DEEPSEEK_API_KEY）
    """
    from contest_agent.settings import load_dotenv

    load_dotenv()  # .env 里的密钥装进环境变量（已存在的不覆盖）
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")
    from contest_agent.composition import build_identify_usecase

    outcomes = build_identify_usecase().execute(limit=5)

    assert len(outcomes) == 5
    # 至少一条真比赛、一条被正确拒绝，且每条都有可读理由
    assert any(o.is_competition for o in outcomes)
    for outcome in outcomes:
        assert outcome.reason
        if outcome.is_competition:
            assert outcome.competition is not None
            assert outcome.competition.evidence  # 原文证据不能是空的
