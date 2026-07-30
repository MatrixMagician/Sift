"""End-to-end proof of DET-01 against the REAL `sift` CLI over a real socket.

Not part of the test suite: this runs the shipped console entry point against a
stub HTTP endpoint on loopback, so the reuse claim is verified through the
actual process boundary rather than through httpx.MockTransport.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

EMBED_CALLS: list[int] = []


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/embeddings"):
            texts = body["input"]
            EMBED_CALLS.append(len(texts))
            payload = {
                "data": [
                    {"index": i, "embedding": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}
                    for i, _ in enumerate(texts)
                ]
            }
        else:
            content = (
                json.dumps(
                    {
                        "hypotheses": [],
                        "timeline_summary": "none",
                        "unexplained_signals": [],
                    }
                )
                if "response_format" in body
                else "{}"
            )
            payload = {"choices": [{"message": {"content": content}}]}
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def run(
    args: list[str], env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sift", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tmp = Path(tempfile.mkdtemp(prefix="sift-det01-"))
    try:
        logs = tmp / "logs"
        logs.mkdir()
        (logs / "app.log").write_text(
            "\n".join(
                f"2026-07-17 09:0{i}:00 ERROR alpha memory pressure warning {i}"
                for i in range(6)
            )
            + "\n",
            encoding="utf-8",
        )

        base = f"http://127.0.0.1:{port}/v1"
        env = {
            **os.environ,
            "SIFT_DATA_DIR": str(tmp / "cases"),
            "SIFT_GENERATION_BASE_URL": base,
            "SIFT_EMBEDDINGS_BASE_URL": base,
            # The operator's real config.toml names an embeddings model, so
            # identity is VERIFIABLE and the D-04 warning must stay silent.
            "SIFT_EMBEDDINGS_MODEL": "stub-embed-v1",
        }

        for step in (["new", "det01", "--input", str(logs)], ["ingest", "det01"]):
            done = run(step, env, tmp)
            if done.returncode != 0:
                print("SETUP FAILED", step, done.returncode)
                print(done.stdout, done.stderr)
                return 1

        first = run(["analyze", "det01"], env, tmp)
        after_first = list(EMBED_CALLS)
        second = run(["analyze", "det01"], env, tmp)
        after_second = EMBED_CALLS[len(after_first) :]
        forced = run(["analyze", "det01", "--re-embed"], env, tmp)
        after_forced = EMBED_CALLS[len(after_first) + len(after_second) :]

        # D-04: a SEPARATE case where identity is genuinely unverifiable on
        # both sides — no SIFT_EMBEDDINGS_MODEL and an isolated XDG_CONFIG_HOME
        # so the operator's real config.toml (which names a model) is not read.
        # The stub never reports a model either, so both sides are None.
        empty_cfg = tmp / "empty-config"
        empty_cfg.mkdir()
        env_unknown = {
            k: v for k, v in env.items() if k != "SIFT_EMBEDDINGS_MODEL"
        } | {"XDG_CONFIG_HOME": str(empty_cfg)}
        for step in (["new", "det04", "--input", str(logs)], ["ingest", "det04"]):
            done = run(step, env_unknown, tmp)
            if done.returncode != 0:
                print("D-04 SETUP FAILED", step, done.stdout, done.stderr)
                return 1
        run(["analyze", "det04"], env_unknown, tmp)
        unknown = run(["analyze", "det04"], env_unknown, tmp)

        # D-03: a PROVEN model change discards the cache silently.
        before_changed = len(EMBED_CALLS)
        changed = run(
            ["analyze", "det01"], {**env, "SIFT_EMBEDDINGS_MODEL": "stub-embed-v2"}, tmp
        )
        after_changed = EMBED_CALLS[before_changed:]

        def line(out: str) -> str:
            return next(
                (ln for ln in out.splitlines() if ln.startswith("Embeddings: ")),
                "<none>",
            )

        print(f"run 1: exit={first.returncode}  {line(first.stdout)}")
        print(f"        embed requests: {after_first}")
        print(f"run 2: exit={second.returncode}  {line(second.stdout)}")
        print(f"        embed requests: {after_second}")
        print(f"run 3 (--re-embed): exit={forced.returncode}  {line(forced.stdout)}")
        print(f"        embed requests: {after_forced}")
        print(
            f"run 4 (no model named): exit={unknown.returncode}  "
            f"{line(unknown.stdout)}"
        )
        print(
            f"run 5 (model changed):  exit={changed.returncode}  "
            f"{line(changed.stdout)}"
        )
        print(f"        embed requests: {after_changed}")
        print(f"run 4 stderr: {unknown.stderr.strip()[:200]}")

        checks = [
            ("run 1 exits 0", first.returncode == 0),
            ("run 2 exits 0", second.returncode == 0),
            ("run 3 exits 0", forced.returncode == 0),
            ("run 4 exits 0", unknown.returncode == 0),
            ("run 5 exits 0", changed.returncode == 0),
            ("run 1 embedded", sum(after_first) > 0),
            ("run 1 reports 0 reused", "0 reused" in line(first.stdout)),
            ("run 2 made ZERO embed requests", after_second == []),
            ("run 2 reports 0 new", "0 new" in line(second.stdout)),
            ("run 2 stays SILENT when identity is verifiable",
             "without a verifiable model identity" not in second.stderr),
            ("run 2 discloses when identity is NOT verifiable",
             "without a verifiable model identity" in unknown.stderr),
            ("unknown-identity run still reused", "0 new" in line(unknown.stdout)),
            ("proven model change re-embeds everything",
             sum(after_changed) > 0 and "0 reused" in line(changed.stdout)),
            ("--re-embed embedded again", sum(after_forced) > 0),
            ("--re-embed reports 0 reused", "0 reused" in line(forced.stdout)),
        ]
        print()
        ok = True
        for name, passed in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
            ok &= passed
        print()
        print("RESULT:", "ALL CHECKS PASSED" if ok else "FAILURES PRESENT")
        return 0 if ok else 1
    finally:
        server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
