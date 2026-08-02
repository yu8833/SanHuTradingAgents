"""
防回归测试：bug-009 Python 3.10 中把内建 callable() 当作类型写 union
会导致 TypeError: unsupported operand type(s) for |: 'builtin_function_or_method' and 'NoneType'

复现条件：
    from dataclasses import dataclass
    @dataclass
    class Foo:
        f: callable | None = None   # TypeError，应该用 Callable

此测试确保 startup_validator.py 能正确 import，ConfigItem 类能被实例化
（验证不会再抛 TypeError 即可）
"""
import pytest


@pytest.mark.regression
def test_bug_009_startup_validator_callable_type_error_never_recur():
    """bug-009: startup_validator.py 定义处不得使用 `callable | None`"""
    # 只要 import 不抛 TypeError（而不是抛错），说明修复生效了
    from app.core.startup_validator import ConfigItem, ConfigLevel

    item = ConfigItem(
        key="FOO",
        level=ConfigLevel.REQUIRED,
        description="foo",
        example="bar",
        validator=lambda v: v.isdigit(),
    )
    # validator 必须是可调用对象，lambda 能被正确调用
    assert item.validator is not None
    assert item.validator("42") is True
    assert item.validator("abc") is False


@pytest.mark.regression
def test_bug_009_no_callable_type_annotation_in_startup_validator_src():
    """静态源码检查：startup_validator.py 中绝不能出现 `callable | None` 这种错误的 union 写法"""
    import os
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "app" / "core" / "startup_validator.py"
    content = src.read_text(encoding="utf-8")
    # ======= bug-009 关键断言 =======
    assert "callable | None" not in content
    assert "callable  | None" not in content
    # 应该使用来自 collections.abc 的 Callable
    assert "from collections.abc import Callable" in content
