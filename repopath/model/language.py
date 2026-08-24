"""语言识别模型和扩展名映射。"""

from enum import StrEnum
from pathlib import Path


class Language(StrEnum):
    """RepoPath 当前支持识别的语言类别。"""

    PYTHON = "Python"
    JAVASCRIPT = "JavaScript"
    JAVASCRIPT_REACT = "JavaScript React"
    TYPESCRIPT = "TypeScript"
    TYPESCRIPT_REACT = "TypeScript React"
    JAVA = "Java"
    GO = "Go"
    RUST = "Rust"
    C = "C"
    CPP_HEADER = "C++ Header"
    CPP = "C++"
    MARKDOWN = "Markdown"
    JSON = "JSON"
    YAML = "YAML"
    OTHER = "Other"


LANGUAGE_BY_EXTENSION = {
    ".py": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT_REACT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT_REACT,
    ".java": Language.JAVA,
    ".go": Language.GO,
    ".rs": Language.RUST,
    ".c": Language.C,
    ".h": Language.CPP_HEADER,
    ".hh": Language.CPP_HEADER,
    ".hpp": Language.CPP_HEADER,
    ".hxx": Language.CPP_HEADER,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".md": Language.MARKDOWN,
    ".json": Language.JSON,
    ".yaml": Language.YAML,
    ".yml": Language.YAML,
}


def detect_language(path: Path) -> Language:
    """根据文件扩展名识别文件语言。"""
    return LANGUAGE_BY_EXTENSION.get(
        path.suffix.lower(), Language.OTHER
    )


def language_family(language: Language) -> str:
    """将语言归入跨文件统计使用的语言族。"""
    if language in {Language.CPP, Language.CPP_HEADER}:
        return "C++"
    return str(language)
