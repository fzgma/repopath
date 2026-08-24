"""Python fixture helpers."""


class MessageBuilder:
    """构造固定消息。"""

    def render(self) -> str:
        """返回消息文本。"""
        return "hello"


def build_message() -> str:
    """构造示例消息。"""
    return MessageBuilder().render()
