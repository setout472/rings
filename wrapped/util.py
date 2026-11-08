"""小工具函数。"""

from __future__ import annotations


def scrub(obj):
    """去掉内部字段（下划线开头），避免把本机路径、File 句柄写进产物。"""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj
