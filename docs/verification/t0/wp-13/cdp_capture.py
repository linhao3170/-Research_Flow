"""Minimal Chrome DevTools Protocol helper for evidence screenshots.

The command-line ``--screenshot`` mode captures when the page's load event fires
and cannot wait for Streamlit's websocket-rendered content.  This helper drives
Chrome through CDP instead: navigate, poll ``document.body.innerText`` until the
expected text is present, then capture the PNG and the DOM.
"""

from __future__ import annotations

import base64
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from websockets.sync.client import connect

__all__ = ["CDPChrome", "find_browser"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def find_browser() -> Path:
    for candidate in (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ):
        if candidate.is_file():
            return candidate
    raise RuntimeError("no headless Chrome/Edge found")


class _CDP:
    def __init__(self, websocket) -> None:
        self._ws = websocket
        self._next_id = 0

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._ws.send(
            json.dumps({"id": request_id, "method": method, "params": params or {}})
        )
        while True:
            message = json.loads(self._ws.recv())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})

    def close(self) -> None:
        try:
            self.send("Browser.close")
        except Exception:  # noqa: BLE001 - closing is best effort
            pass
        self._ws.close()


class CDPChrome:
    def __init__(self, profile_root: Path | None = None) -> None:
        self.browser = find_browser()
        self.port = _free_port()
        self.profile = (
            (profile_root or Path.cwd() / "runtime")
            / f"cdp-profile-{uuid.uuid4().hex[:8]}"
        )
        self.profile.mkdir(parents=True, exist_ok=True)
        self.log_path = self.profile / "chrome.log"
        self._log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                str(self.browser),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--hide-scrollbars",
                "--disable-background-networking",
                "--no-first-run",
                "--no-default-browser-check",
                f"--remote-debugging-port={self.port}",
                "--remote-allow-origins=*",
                f"--user-data-dir={self.profile}",
                "--window-size=1440,1200",
                "about:blank",
            ],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._ws = None
        self._cdp = None
        self._connect()

    def _endpoint(self, path: str) -> str:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=2
        ) as response:
            return response.read().decode("utf-8")

    def _connect(self) -> None:
        deadline = time.time() + 60
        target = None
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"browser exited early; see {self.log_path}"
                )
            try:
                targets = json.loads(self._endpoint("/json/list"))
                target = next(
                    (item for item in targets if item.get("type") == "page"), None
                )
                if target is not None:
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        if target is None:
            raise RuntimeError(f"no page target; see {self.log_path}")
        self._ws = connect(target["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
        self._cdp = _CDP(self._ws)
        self._cdp.send("Page.enable")
        self._cdp.send("Runtime.enable")
        self._cdp.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 1440,
                "height": 1200,
                "deviceScaleFactor": 1,
                "mobile": False,
            },
        )

    @property
    def version(self) -> str:
        return self.browser.as_posix()

    def goto_and_wait(
        self,
        url: str,
        expected: list[str],
        *,
        timeout: float = 60.0,
        settle: float = 1.0,
    ) -> str:
        self._cdp.send("Page.navigate", {"url": url})
        deadline = time.time() + timeout
        text = ""
        while time.time() < deadline:
            result = self._cdp.send(
                "Runtime.evaluate",
                {
                    "expression": "document.body ? document.body.innerText : ''",
                    "returnByValue": True,
                },
            )
            text = str((result.get("result") or {}).get("value") or "")
            if all(item in text for item in expected):
                time.sleep(settle)
                return text
            time.sleep(0.2)
        missing = [item for item in expected if item not in text]
        raise TimeoutError(f"expected text did not render: {missing}")

    def screenshot(self, path: Path) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        result = self._cdp.send(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
        )
        data = base64.b64decode(result["data"])
        path.write_bytes(data)
        return {
            "target": path.as_posix(),
            "bytes": len(data),
            "duration_sec": round(time.perf_counter() - started, 3),
        }

    def dom(self, path: Path) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        result = self._cdp.send(
            "Runtime.evaluate",
            {
                "expression": "document.documentElement.outerHTML",
                "returnByValue": True,
            },
        )
        text = str((result.get("result") or {}).get("value") or "")
        path.write_text(text, encoding="utf-8")
        return {"target": path.as_posix(), "bytes": len(text.encode("utf-8"))}

    def close(self) -> None:
        try:
            if self._cdp is not None:
                self._cdp.close()
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                    self.process.kill()
                    self.process.wait(timeout=20)
            self._log.close()