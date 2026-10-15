"""将清单解析结果限定为可检查的对象字段，不执行其中的配置。"""

import json
from collections.abc import Mapping, Sequence
from typing import TypeGuard

import tomllib


def load_manifest(source: str, *, toml: bool) -> object:
    """解析外部数据，由使用方检查所需字段的实际类型。"""
    return tomllib.loads(source) if toml else json.loads(source)


def _is_object_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    """字典的键值仍是任意对象，通过只读视图逐项验证。"""
    return isinstance(value, dict)


def manifest_fields(value: object) -> Mapping[str, object] | None:
    """验证对象及字符串键，保留未知字段值供后续逐项检查。"""
    if not _is_object_mapping(value):
        return None
    fields: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        fields[key] = item
    return fields


def is_manifest_array(value: object) -> TypeGuard[Sequence[object]]:
    """仅接受清单数组，元素保留为对象，供遍历时继续收窄。"""
    return isinstance(value, list)
