"""Define the public operation on a sequence of words."""

__all__ = ["combine"]


def combine(words: list[str]) -> str:
    """Join words using one space."""
    return " ".join(words)
