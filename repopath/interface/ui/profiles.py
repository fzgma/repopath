"""Streamlit 分析预设定义。"""

from dataclasses import dataclass

from ...model.options import AnalysisOptions


@dataclass(frozen=True)
class ProfileSpec:
    """定义一个 UI 可选择的分析预设及其说明。"""

    label: str
    profile: str
    description: str

    def options(self) -> AnalysisOptions:
        """创建该预设对应的核心分析选项。"""
        return AnalysisOptions.for_profile(self.profile)


PROFILE_SPECS = (
    ProfileSpec(
        "快速",
        "fast",
        "仅扫描文件、语言和目录规模，适合先确认仓库范围。",
    ),
    ProfileSpec(
        "标准",
        "standard",
        "增加 Python、C++ 结构和 Git 历史统计，适合快速了解代码组成与演进。",
    ),
    ProfileSpec(
        "深度",
        "deep",
        "运行全部常规分析，生成依赖图、评分和变更关注模块；试验性阅读指南需单独开启。",
    ),
)

_BY_LABEL = {spec.label: spec for spec in PROFILE_SPECS}
_BY_PROFILE = {spec.profile: spec for spec in PROFILE_SPECS}


def profile_for_label(label: str) -> ProfileSpec:
    """按页面标签获取分析预设。"""
    return _BY_LABEL[label]


def label_for_profile(profile: str) -> str:
    """按核心 profile 值获取页面标签。"""
    return _BY_PROFILE.get(profile, _BY_PROFILE["deep"]).label
