"""任务记录器（TaskRecorder）：把一次任务的轨迹逐条写进会话存档（M2）。

它只是 SessionArchivePort 的一层薄包装，职责是"绑定会话、简化调用"：
- composition.py 组装用例时开好会话，把 recorder 递进去；
- 用例和 harness 在关键节点调 recorder.log(事件类型, **内容)；
- 任务结束时调 recorder.finish(状态)。

为什么不让用例直接用仓储接口？——用例不该关心"会话编号怎么管理、
事件怎么存"，只要说"记一笔：发生了什么"。和 CostMeter 一样，
这是横切关注点：组装时注入，业务代码保持干净。

事件类型约定（回放器按这个渲染）：
    user_input   用户/调用方交给任务的话（text）
    model_call   一次模型调用（usage、消息数；正文截断存储）
    compression  框架做了一次上下文压缩（摘要前 300 字）
    tool_call    一次工具调用（工具名、参数、结果截断存储）
    result       任务收尾陈述（final_text）
    error        任务出错（error）
"""

from __future__ import annotations

from ..domain.ports import SessionArchivePort


class TaskRecorder:
    """绑定了一个会话的事件记录器。所有方法都容忍"没配存档"（archive 为 None）：
    此时静默不记——和 CostMeter 的 repository=None 一个道理，测试不用建库。
    """

    def __init__(self, archive: SessionArchivePort | None, task_type: str, note: str = ""):
        self._archive = archive
        # 会话编号：组装时没配存档就是 None；配了就在构造时开好会话
        self.session_id: int | None = (
            archive.create_session(task_type, note) if archive is not None else None
        )

    def log(self, kind: str, **payload) -> None:
        """记一条事件。任何存储异常都不允许影响主任务——存档是锦上添花，
        不能让"记日志失败"把识别/生成搞挂（所以这里兜住所有异常）。"""
        if self._archive is None or self.session_id is None:
            return
        try:
            self._archive.append_event(self.session_id, kind, payload)
        except Exception:
            pass  # 存档失败不影响业务；排查存储问题去看数据库本身

    def finish(self, status: str) -> None:
        """盖任务结束戳。同样吞异常（理由同上）。"""
        if self._archive is None or self.session_id is None:
            return
        try:
            self._archive.finish_session(self.session_id, status)
        except Exception:
            pass
