# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from pathlib import Path


# 相对仓库根定位:硬编码 H:\ 在 CI runner/他人机器上必挂(CI #6 实锤)
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

MAIN_DOC = DOCS_DIR / "CS2Customizer_后台静默自查规范_v1.md"
INDEX_DOC = DOCS_DIR / "CS2Customizer_后台静默自查索引_v1.md"
EXECUTION_DOC = DOCS_DIR / "CS2Customizer_后台静默自查执行模板_v1.md"
COVERAGE_DOC = DOCS_DIR / "CS2Customizer_后台静默自查覆盖矩阵_v1.md"
RECORD_DOC = DOCS_DIR / "CS2Customizer_后台静默自查记录模板_v1.md"
FAILURE_DOC = DOCS_DIR / "CS2Customizer_后台静默自查常见失败处理手册_v1.md"

ALL_DOCS = [
    MAIN_DOC,
    INDEX_DOC,
    EXECUTION_DOC,
    COVERAGE_DOC,
    RECORD_DOC,
    FAILURE_DOC,
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_silent_acceptance_docs_exist():
    for path in ALL_DOCS:
        assert path.exists(), f"missing silent-acceptance doc: {path.name}"


def test_main_doc_links_all_support_docs():
    text = _read(MAIN_DOC)
    for path in [EXECUTION_DOC, COVERAGE_DOC, RECORD_DOC, FAILURE_DOC]:
        assert path.name in text, f"main doc missing link to {path.name}"


def test_index_doc_links_all_docs_and_sets_assistant_as_executor():
    text = _read(INDEX_DOC)
    for path in [MAIN_DOC, EXECUTION_DOC, COVERAGE_DOC, RECORD_DOC, FAILURE_DOC]:
        assert path.name in text, f"index doc missing link to {path.name}"
    assert "默认由我" in text


def test_support_docs_reference_main_doc():
    for path in [EXECUTION_DOC, COVERAGE_DOC, RECORD_DOC, FAILURE_DOC]:
        text = _read(path)
        assert MAIN_DOC.name in text, f"{path.name} should reference main doc"


def test_silent_acceptance_docs_do_not_reintroduce_dual_layer_flow():
    forbidden_tokens = ["`L2`", "run_isolated_acceptance", "双层验收"]
    for path in ALL_DOCS:
        text = _read(path)
        for token in forbidden_tokens:
            assert token not in text, f"{path.name} unexpectedly contains forbidden token: {token}"


def test_main_doc_keeps_single_layer_positioning():
    text = _read(MAIN_DOC)
    assert "默认由我负责执行检查" in text
    assert "后台静默自查" in text
    assert "虚拟机、隔离会话、黑盒环境" in text


def _defines_page_class(path) -> bool:
    """这个模块是不是一个"页面"——判据落在**文件定义了什么**上。

    原先是一张硬编码排除名单（`audio_status_badge.py` 就在上面）。
    UP-057 加了 `pages/sound_page_base.py`（音效页共用的 mixin，不是页面、
    也不会被展示给用户），这条判据当场把它当成"漏写文档的页面"报红。
    再往名单里塞一个名字只是把问题推后：下次再加个辅助模块还会再红一次。
    改成看文件里有没有定义 `*Page` 类——页面模块都有，辅助模块都没有。
    """
    import ast as _ast

    try:
        tree = _ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return True  # 解析不了就别放过它,宁可误报
    return any(
        isinstance(node, _ast.ClassDef) and node.name.endswith("Page")
        for node in tree.body
    )


def test_coverage_matrix_mentions_all_real_page_modules():
    page_names = sorted(
        path.name
        for path in (DOCS_DIR.parent / "pages").glob("*.py")
        if path.name != "__init__.py" and _defines_page_class(path)
    )
    assert page_names, "一个页面模块都没识别出来，判据落空了"
    text = _read(COVERAGE_DOC)
    for page_name in page_names:
        assert page_name in text, f"coverage matrix missing page: {page_name}"


def test_coverage_matrix_only_references_existing_test_files():
    import re

    test_names = sorted(set(re.findall(r"test_[A-Za-z0-9_\.]+\.py", _read(COVERAGE_DOC))))
    for test_name in test_names:
        assert (DOCS_DIR.parent / "tests" / test_name).exists(), (
            f"coverage matrix references missing test file: {test_name}"
        )


def test_cfg_writing_pages_are_marked_as_high_risk_in_coverage_matrix():
    text = _read(COVERAGE_DOC)
    for page_name in ["magnifier_page.py", "viewmodel_page.py", "hud_color_page.py"]:
        assert page_name in text
    assert text.count("静默前必须断开真实 CFG 写出") >= 3
