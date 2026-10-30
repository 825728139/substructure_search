"""真实浏览器回归；可选 Playwright 与 Chromium，使用本机隔离服务和合成记录。"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from reaction_reference.domain.models import ReactionRecord
from reaction_reference.settings import Settings

playwright_api = pytest.importorskip("playwright.sync_api", reason="真实页面回归需要 Playwright")


@pytest.fixture(scope="module")
def browser_server(tmp_path_factory):
    """启动私有运行目录和二十条合成记录的服务，监听预先分配的本机端口并统一清理。"""
    root = tmp_path_factory.mktemp("browser-service")
    fixture = Path(Settings.model_fields["source_path"].get_default(call_default_factory=True))
    record = ReactionRecord.model_validate_json(fixture.read_text(encoding="utf-8").splitlines()[0])
    record = record.model_copy(update={"raw": {**record.raw, "large_counter": 9007199254740993}})
    rows = [
        record.model_copy(
            update={
                "id": f"browser-{index}",
                "source": record.source.model_copy(
                    update={"record_id": f"browser-{index}", "experiment_id": f"browser-{index}"}
                ),
            }
        ).model_dump_json()
        for index in range(20)
    ]
    source = root / "source.jsonl"
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("RR_")}
    env.update(
        RR_SOURCE_KIND="jsonl",
        RR_SOURCE_PATH=str(source),
        RR_STORE_PATH=str(root / "runs"),
        RR_API_TOKEN="browser-test-token",
    )
    with socket.socket() as listener, (root / "server.log").open("w", encoding="utf-8") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "reaction_reference.interfaces.api:create_app",
                "--factory",
                "--fd",
                str(listener.fileno()),
            ],
            env=env,
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, (root / "server.log").read_text(encoding="utf-8")
                try:
                    with urllib.request.urlopen(address + "/health/live", timeout=0.5) as response:
                        assert response.status == 200
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise AssertionError("浏览器测试服务未就绪") from None
                    time.sleep(0.05)
            yield address
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.fixture(scope="module")
def chromium():
    """打开本机已安装的 Chromium；缺少浏览器时明确跳过，不自动访问外部站点。"""
    with playwright_api.sync_playwright() as playwright:
        executable = os.environ.get("RR_TEST_CHROMIUM_PATH")
        if not Path(executable or playwright.chromium.executable_path).is_file():
            pytest.skip("真实页面回归需要安装 Chromium：playwright install chromium")
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def browser_page(chromium, browser_server):
    """为每项用例创建独立页面，默认提供正确内部令牌。"""
    page = chromium.new_page()
    page.set_default_timeout(15000)
    try:
        page.goto(browser_server)
        page.locator("#token").fill("browser-test-token")
        yield page
    finally:
        page.close()


@pytest.mark.parametrize("temperature", [25.5, -10.5])
def test_fractional_temperature_can_submit(browser_page, temperature):
    """后端允许的小数温度必须能通过浏览器表单校验，并按原数值发送请求。"""
    page = browser_page
    page.locator("#temp").fill(str(temperature))
    assert page.locator("#temp").evaluate("element => element.checkValidity()")
    with page.expect_request("**/v1/search-runs") as pending:
        page.locator("#submit").click()
    assert pending.value.post_data_json["lab_context"]["max_temperature_c"] == temperature
    page.locator("#download:not([disabled])").wait_for()


def test_browser_pagination_structures_rerank_and_download(browser_page, tmp_path):
    """真实页面的分页、图片、重排和下载必须始终绑定当前运行及快照。"""
    page = browser_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.locator("#submit").click()
    page.locator("#download:not([disabled])").wait_for()
    assert page.locator("#cards .card").count() == 12
    page.wait_for_function(
        '(() => { const images = Array.from(document.querySelectorAll("#cards img")); '
        "return images.length === 12 && images.every(image => image.complete && image.naturalWidth > 0); })()"
    )
    page.locator("#more").click()
    page.wait_for_function('document.querySelectorAll("#cards .card").length === 18')
    original = page.evaluate("run")
    page.locator("#profile").select_option("lab_fit")
    page.locator("#rerank").click()
    page.wait_for_function(
        '(previous) => run !== previous && !document.getElementById("download").disabled',
        arg=original,
    )
    with page.expect_download() as pending:
        page.locator("#download").click()
    path = tmp_path / "package.json"
    pending.value.save_as(path)
    package = json.loads(path.read_text(encoding="utf-8"))
    assert package["run_id"] == page.evaluate("run")
    assert package["snapshot_id"] == page.evaluate("activeSnapshot")
    assert package["manifest"]["request"]["ranking_profile"] == "lab_fit"
    assert not errors


def test_browser_can_retry_after_authentication_failure(browser_page):
    """错误令牌得到可见错误后，修正令牌可再次提交，不沿用失败任务状态。"""
    page = browser_page
    page.locator("#token").fill("wrong-token")
    page.locator("#submit").click()
    page.wait_for_function(
        'document.getElementById("status").textContent.includes("Authentication required")'
    )
    assert page.locator("#submit").is_enabled()
    assert page.locator("#download").is_disabled()
    page.locator("#token").fill("browser-test-token")
    page.locator("#submit").click()
    page.locator("#download:not([disabled])").wait_for()
    assert "succeeded" in page.locator("#status").inner_text()


def test_browser_download_preserves_original_integer_metadata(browser_page, tmp_path):
    """下载完整资料包时不能经过 JavaScript 数值重编码，避免合法大整数被舍入。"""
    page = browser_page
    page.locator("#submit").click()
    page.locator("#download:not([disabled])").wait_for()
    with page.expect_download() as pending:
        page.locator("#download").click()
    path = tmp_path / "original.json"
    pending.value.save_as(path)
    package = json.loads(path.read_text(encoding="utf-8"))
    assert package["results"]
    assert all(
        reference["record"]["raw"]["large_counter"] == 9007199254740993
        for reference in package["results"]
    )


def test_rerank_rejects_incomplete_temperature_without_clearing_constraint(browser_page):
    """重排不能把浏览器未完成的指数输入当作空值，修正后再发送明确的温度限制。"""
    page = browser_page
    page.locator("#temp").fill("30")
    page.locator("#submit").click()
    page.locator("#download:not([disabled])").wait_for()
    original = page.evaluate("run")
    requests = []
    page.on(
        "request",
        lambda request: requests.append(request) if request.url.endswith("/rerank") else None,
    )
    page.locator("#temp").fill("")
    page.locator("#temp").press_sequentially("1e")
    assert page.locator("#temp").evaluate("element => element.validity.badInput")
    assert page.locator("#temp").input_value() == ""
    page.locator("#rerank").click()
    assert not requests, "非法温度被静默转成了不限制温度的重排请求"
    assert page.evaluate("run") == original
    assert page.locator("#download").is_enabled()
    page.locator("#temp").fill("25.5")
    with page.expect_request("**/rerank") as pending:
        page.locator("#rerank").click()
    assert pending.value.post_data_json["lab_context"]["max_temperature_c"] == 25.5
    page.locator("#download:not([disabled])").wait_for()
