# -*- coding: utf-8 -*-
"""全局热键注册中心包（P2.1）。"""
from core.hotkeys.registry import (  # noqa: F401
    declare_interest,
    find_conflicts,
    list_bindings,
    register_hook,
    register_key,
    register_mouse,
    unregister,
    unregister_owner,
)
