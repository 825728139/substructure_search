"""通过浏览器接口替身验证页面的异步任务隔离与正常显示流程。"""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="前端异步回归需要 Node.js")
def test_frontend_task_isolation_and_current_results():
    """运行乱序状态、分页、异常、下载与当前任务正常显示、串行轮询六个场景。"""
    result = subprocess.run(
        [shutil.which("node"), str(Path(__file__).with_name("check_frontend_state.cjs"))],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
