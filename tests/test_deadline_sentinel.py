"""M4 差异化方向①验收测试：截止日期守望哨兵。

用注入的"今天"（定格日期）+ 内存记忆 + 假推送通道，把四条规则逐一钉死：
四档警报、同档去重、晚添加补发、过期停报；再测推送降级与只读视图。
"""

from datetime import date, datetime, timedelta

from contest_agent.application.usecases.deadline_watch import DeadlineSentinel
from contest_agent.application.usecases.watch_site import push_via_channels
from contest_agent.domain.entities import Competition


# ---------- 假对象 ----------


class MemoryRepoFake:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def remember(self, key, value):
        self.store[key] = value

    def recall(self, key):
        return self.store.get(key)

    def forget_all(self):
        n = len(self.store)
        self.store.clear()
        return n

    def list_entries(self, limit=50):
        return []

    def count(self):
        return len(self.store)


class FakePusher:
    def __init__(self, name: str, boom: bool = False) -> None:
        self._name = name
        self._boom = boom
        self.sent: list[tuple[str, str]] = []

    @property
    def channel_name(self) -> str:
        return self._name

    def send(self, title, content):
        if self._boom:
            raise ConnectionError("通道故障")
        self.sent.append((title, content))


def _card(name: str, days: int | None, today: date, url: str | None = None) -> Competition:
    deadline = (today + timedelta(days=days)) if days is not None else None
    return Competition(name=name, notice_url=url or f"u-{name}", type="exam",
                       deadline=deadline)


class RepoFake:
    def __init__(self, cards) -> None:
        self.cards = cards

    def save_if_absent(self, competition):
        return True

    def list_all(self):
        return self.cards


TODAY = date(2026, 10, 1)


def _sentinel(cards, memory=None, pushers=None, today=TODAY):
    return DeadlineSentinel(
        competition_repository=RepoFake(cards),
        memory=memory or MemoryRepoFake(),
        pushers=pushers or [],
        today=today,
    )


# ---------- 规则逐条钉 ----------


def test_four_thresholds_and_makeup() -> None:
    """剩余 7/3/1/0 天各触发一档；窗口内首次露脸的卡（B5，剩余 5 天）
    立即补发一次；之后它走正常档位。"""
    cards = [
        _card("A7", 7, TODAY), _card("B5", 5, TODAY),
        _card("C3", 3, TODAY), _card("D1", 1, TODAY), _card("E0", 0, TODAY),
    ]
    report = _sentinel(cards).execute(push=False)

    alerted = {a.card.name: a.remaining for a in report.alerts}
    assert alerted == {"A7": 7, "B5": 5, "C3": 3, "D1": 1, "E0": 0}
    labels = {a.card.name: a.label for a in report.alerts}
    assert labels["E0"] == "🔴 今天截止"
    assert labels["D1"] == "🟠 明天截止（最后一天）"
    assert "⏳ 还剩 5 天" in labels["B5"]


def test_memory_dedupes_same_level() -> None:
    """同一档只提醒一次：T-3 推送并记账 → T-2 安静 → T-1 下一档再推。"""
    memory = MemoryRepoFake()
    web = FakePusher("webhook")
    card = _card("数学竞赛", 3, TODAY)
    sentinel = _sentinel([card], memory=memory, pushers=[web])

    r1 = sentinel.execute(push=True)
    assert [a.remaining for a in r1.alerts] == [3]
    assert len(web.sent) == 1

    sentinel.today = TODAY + timedelta(days=1)      # T-2：非阈值，安静
    r2 = sentinel.execute(push=True)
    assert r2.alerts == []
    assert len(web.sent) == 1

    sentinel.today = TODAY + timedelta(days=2)      # T-1：下一档，再推
    r3 = sentinel.execute(push=True)
    assert [a.remaining for a in r3.alerts] == [1]
    assert len(web.sent) == 2


def test_dry_run_does_not_consume_alerts() -> None:
    """push=False（干跑预览）永不记账：看多少遍都不消耗警报。"""
    memory = MemoryRepoFake()
    web = FakePusher("webhook")
    sentinel = _sentinel([_card("A", 3, TODAY)], memory=memory, pushers=[web])

    for _ in range(3):
        r = sentinel.execute(push=False)
        assert [a.remaining for a in r.alerts] == [3]

    # 干跑之后真推送：警报还在，正常发出并记账
    r = sentinel.execute(push=True)
    assert len(web.sent) == 1
    assert memory.store[f"deadline:u-A"]["last_level"] == 3


def test_late_added_card_gets_makeup_alert() -> None:
    """晚添加补发：T-2 才进库的卡（错过 T-7/T-3）立即补发一次。"""
    memory = MemoryRepoFake()
    web = FakePusher("webhook")
    card = _card("迟到的比赛", 2, TODAY)
    r = _sentinel([card], memory=memory, pushers=[web]).execute(push=True)

    assert [a.remaining for a in r.alerts] == [2]
    assert "⏳ 还剩 2 天" in r.alerts[0].label
    # 记住补发级别：T-1 照常走档，不会重复补发
    r2 = _sentinel([card], memory=memory, pushers=[web]).execute(push=True)
    assert r2.alerts == []


def test_expired_cards_stop_alerting_but_counted() -> None:
    """过期停报：仅计入 expired；无截止日期的卡片直接忽略。"""
    cards = [
        _card("过期的", -2, TODAY),
        _card("没写截止", None, TODAY),
    ]
    r = _sentinel(cards).execute(push=False)

    assert r.expired == 1
    assert r.alerts == []
    assert r.upcoming == []


def test_upcoming_view_sorted_within_days() -> None:
    """只读列表（sai deadlines / API 用）：按剩余天数升序，可限窗口。"""
    cards = [
        _card("今天", 0, TODAY), _card("三天", 3, TODAY),
        _card("二十天", 20, TODAY), _card("两个月", 60, TODAY),
    ]
    all_list = _sentinel(cards).upcoming(within_days=30)
    assert [a.remaining for a in all_list] == [0, 3, 20]

    tight = _sentinel(cards).upcoming(within_days=7)
    assert [a.remaining for a in tight] == [0, 3]


# ---------- 推送 ----------


def test_push_grouped_message_and_dedup() -> None:
    """多场临近合并成一条消息推给所有通道；推过之后下一轮不再推。"""
    web = FakePusher("webhook")
    memory = MemoryRepoFake()
    cards = [_card("A", 3, TODAY), _card("B", 1, TODAY)]
    sentinel = _sentinel(cards, memory=memory, pushers=[web])

    r = sentinel.execute(push=True)

    assert all(x["ok"] for x in r.push_results)
    assert len(web.sent) == 1
    title, content = web.sent[0]
    assert "2 场比赛临近截止" in title
    assert "数学" not in content and "A" in content and "B" in content

    # 下一轮（同一天再跑一次 watch）：同档已记账，安静
    r2 = sentinel.execute(push=True)
    assert r2.alerts == []
    assert len(web.sent) == 1


def test_push_failure_still_records_next_round_retries() -> None:
    """推送全挂：不记账，下一轮同档还会再试（警报不能因为通道抽风而永久丢）。"""
    web = FakePusher("webhook", boom=True)
    memory = MemoryRepoFake()
    sentinel = _sentinel([_card("A", 1, TODAY)], memory=memory, pushers=[web])

    r1 = sentinel.execute(push=True)
    assert r1.push_results[0]["ok"] is False
    assert memory.store == {}                     # 没推出去就不记账

    web._boom = False                             # 通道恢复
    r2 = sentinel.execute(push=True)
    assert [a.remaining for a in r2.alerts] == [1]  # 再试成功
    assert len(web.sent) == 1


def test_push_via_channels_shared_helper() -> None:
    """watch 与哨兵共用的推送函数：逐通道结果、故障隔离。"""
    web = FakePusher("webhook", boom=True)
    filep = FakePusher("file")
    results = push_via_channels([web, filep], "t", "c")

    assert results[0]["ok"] is False
    assert results[1] == {"channel": "file", "ok": True}
    assert filep.sent == [("t", "c")]
