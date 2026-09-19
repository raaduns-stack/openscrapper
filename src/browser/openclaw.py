import json
import os
import subprocess
import time


class OpenClawBrowser:
    DEFAULT_TIMEOUT = 30.0

    def __init__(self, cli: str = "openclaw", timeout: float | None = None):
        self.cli = cli if cli != "openclaw" else "/root/.openclaw/bin/openclaw"
        self.timeout = timeout if timeout is not None else float(os.getenv("OPENCLAW_BROWSER_TIMEOUT", self.DEFAULT_TIMEOUT))
        if self.timeout <= 0:
            raise ValueError("OpenClaw browser timeout must be positive")

    def _run(self, *args: str) -> str:
        last_error = None
        for attempt in range(3):
            try:
                result = subprocess.run(
                    [self.cli, "browser", *args],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=self.timeout,
                )
                return result.stdout.strip()
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"OpenClaw browser command timed out after {self.timeout:g}s: {' '.join(args)}") from e
            except subprocess.CalledProcessError as e:
                detail = (e.stderr or e.stdout or "").strip()
                last_error = RuntimeError(
                    f"OpenClaw browser command failed: {' '.join(args)}"
                    + (f": {detail}" if detail else "")
                )
                if "GatewayTransportError" not in detail or attempt == 2:
                    raise last_error from e
                time.sleep(1 + attempt)

        raise last_error

    def navigate(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL: {url}")
        return self._run("navigate", url)

    def snapshot(self) -> str:
        return self._run("snapshot")

    def click(self, ref: str) -> str:
        if not ref:
            raise ValueError("Browser ref cannot be empty")
        return self._run("click", ref)

    def evaluate(self, expression: str):
        raw = self._run("evaluate", "--fn", expression)

        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return raw

        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value

        return value

    def current_url(self) -> str:
        value = self.evaluate("() => location.href")
        if not isinstance(value, str) or not value:
            raise RuntimeError("OpenClaw returned an invalid current URL")
        return value

    def text(self) -> str:
        value = self.evaluate("() => document.body.innerText")
        if not isinstance(value, str):
            raise RuntimeError("OpenClaw returned invalid page text")
        return value

    def html(self) -> str:
        value = self.evaluate("() => document.documentElement.outerHTML")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("OpenClaw returned empty page HTML")
        return value
