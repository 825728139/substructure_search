"""通过浏览器接口替身验证页面的异步任务隔离与正常显示流程。"""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="前端异步回归需要 Node.js")
def test_frontend_task_isolation_and_current_results():
    """运行乱序状态、分页、下载、重排失败隔离、正常显示及串行轮询十个场景。"""
    result = subprocess.run(
        [shutil.which("node"), str(Path(__file__).with_name("check_frontend_state.cjs"))],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
