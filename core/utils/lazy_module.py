# -*- coding: utf-8 -*-
"""惰性模块代理（UP-055）。

用途：把某个**很贵但很少用**的第三方模块从 import 期挪到首次真正使用时。
本项目的具体场景是 pygame —— 本机实测 import 一次约 400ms
（pkg_resources 219ms + numpy 113ms），而它只在"显示准心 / 播击杀图标"时才需要，
绝大多数启动里用户根本不会触发。

为什么不是"把 import 挪进用到它的函数"：
    那要求找齐**每一个**入口点。`crosshair_animation` 里 `pygame.` 出现在
    十几个方法中，漏掉一处就是运行期 AttributeError —— 用崩溃换启动速度是赔本的。
    代理让漏掉的那处照常工作，只是第一次访问时多付一次 import。

代价：首次属性访问会走一次 `__getattr__`。之后代理把自己从调用方的模块全局里
**换成真模块**，后续访问零开销。

    # 模块顶部
    pygame = lazy_module("pygame", __name__)

    # 其余代码照写 pygame.init() / pygame.draw.line(...)，不必改
"""

from __future__ import annotations

import importlib
import sys


class LazyModule:
    """首次属性访问时才导入真模块，并就地把自己替换掉。"""

    __slots__ = ("_lazy_name", "_lazy_owner")

    def __init__(self, module_name: str, owner_module: str):
        # 用 object.__setattr__ 绕开自己的 __setattr__
        object.__setattr__(self, "_lazy_name", module_name)
        object.__setattr__(self, "_lazy_owner", owner_module)

    def _resolve(self):
        module = importlib.import_module(object.__getattribute__(self, "_lazy_name"))
        owner = sys.modules.get(object.__getattribute__(self, "_lazy_owner"))
        if owner is not None:
            # 把调用方模块里**所有**指向本代理的名字改绑到真模块上——之后不再经过代理。
            # 早先的实现命中第一个就 break，同一模块里给代理起了别名时会漏掉后面的；
            # 更糟的是它还有个 for-else 兜底 `setattr(owner, name.split('.')[0], module)`：
            # 对 "a.b" 这种点号模块名会凭空造出一个叫 `a` 的全局名并绑上 `a.b` 模块。
            # 兜底本身没必要——找不到名字时代理照常工作，只是每次多一层 __getattr__。
            for attr, value in list(vars(owner).items()):
                if value is self:
                    setattr(owner, attr, module)
        return module

    def __getattr__(self, item):
        if item.startswith("_lazy_"):
            raise AttributeError(item)
        return getattr(self._resolve(), item)

    def __setattr__(self, key, value):
        setattr(self._resolve(), key, value)

    def __bool__(self):
        # 别为了一次真值判断就把整个模块拉起来
        return True

    def __repr__(self):
        name = object.__getattribute__(self, "_lazy_name")
        loaded = name in sys.modules
        return f"<LazyModule {name!r} {'已加载' if loaded else '未加载'}>"


def lazy_module(module_name: str, owner_module: str) -> LazyModule:
    """返回 module_name 的惰性代理；owner_module 传调用方的 `__name__`。

    若该模块**已经**被加载过，直接返回真模块——没有理由再绕一层。
    """
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    return LazyModule(module_name, owner_module)
