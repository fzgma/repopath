"""分析任务的协作式取消控制。"""

from threading import Event


class AnalysisCancelled(Exception):
    """表示分析任务已按用户请求协作式停止。"""


class CancellationToken:
    """封装线程事件并为分析流程提供取消检查。"""

    def __init__(self, event: Event | None = None) -> None:
        """使用指定事件或新事件创建取消令牌。"""
        self._event = event or Event()

    @property
    def cancelled(self) -> bool:
        """返回当前任务是否已收到取消请求。"""
        return self._event.is_set()

    def cancel(self) -> None:
        """通知分析流程尽快停止当前任务。"""
        self._event.set()

    def raise_if_cancelled(self) -> None:
        """在收到取消请求时中断当前分析流程。"""
        if self.cancelled:
            raise AnalysisCancelled("分析已取消")
