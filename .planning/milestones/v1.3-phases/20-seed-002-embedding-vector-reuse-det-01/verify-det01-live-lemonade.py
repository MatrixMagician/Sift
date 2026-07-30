"""Live-Lemonade validation of DET-01 and D-10, with counted embedding requests.

Runs the real `sift` console script against the operator's actual Lemonade
instance (127.0.0.1:13305) through a transparent counting proxy, so "run 2
performs no embedding work" is proven by observed HTTP traffic to a genuine
backend rather than inferred from printed output.

Why a proxy: Lemonade's /api/v1/stats reports the LAST request's token counts,
not cumulative totals, so token deltas cannot measure whether an embedding pass
happened. The proxy forwards every request untouched to Lemonade and tallies
paths, which can.

Proven here:
  * DET-01: run 2 on an unchanged case issues ZERO /v1/embeddings requests.
  * DET-01: `--re-embed` issues them again, at the real 1024 dimension.
  * D-10: Lemonade serves web-UI HTML at /props (HTTP 200, not JSON), so the
    prompt budget is estimated -- the warning must appear when
    `generation.context` is unset and must NOT appear when it is set.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

LEMONADE = "http://127.0.0.1:13305"
SEEN: Counter[str] = Counter()
_HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "content-length",
    "host",
    # Dropped so upstream replies uncompressed: this proxy relays the body
    # verbatim, and forwarding Accept-Encoding would relay a gzip payload while
    # advertising identity, which the client cannot parse.
    "accept-encoding",
}


class Proxy(BaseHTTPRequestHandler):
    """Transparent forwarder to Lemonade that tallies request paths."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args: object) -> None:
        pass

    def _forward(self, body: bytes | None) -> None:
        SEEN[self.path] += 1
        headers = {
            k: v for k, v in self.headers.items() if k.lower() not in _HOP
        }
        req = urllib.request.Request(  # noqa: S310
            f"{LEMONADE}{self.path}",
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as upstream:  # noqa: S310
                status, payload = upstream.status, upstream.read()
                ctype = upstream.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, exc.read()
            ctype = exc.headers.get("Content-Type", "application/json")
        except Exception as exc:  # noqa: BLE001
            status = 502
            payload = json.dumps({"error": repr(exc)}).encode()
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        self._forward(None)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self._forward(self.rfile.read(length) if length else b"")


def embeds() -> int:
    return sum(n for p, n in SEEN.items() if p.endswith("/embeddings"))


def run(
    args: list[str], env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["sift", *args],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
        timeout=900,
    )


def embed_line(out: str) -> str:
    return next(
        (ln for ln in out.splitlines() if ln.startswith("Embeddings: ")),
        "<no Embeddings line>",
    )


def props_shape() -> str:
    try:
        with urllib.request.urlopen(f"{LEMONADE}/props", timeout=5) as fh:  # noqa: S310
            head = fh.read(40).decode("utf-8", "replace")
            return f"HTTP {fh.status}, starts {head!r}"
    except Exception as exc:  # noqa: BLE001
        return repr(exc)


def main() -> int:
    print(f"Lemonade /props -> {props_shape()}")
    print("  (HTTP 200 + HTML, not JSON: the exact D-10 condition)\n")

    server = HTTPServer(("127.0.0.1", 0), Proxy)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/v1"
    print(f"counting proxy on {base} -> {LEMONADE}\n")

    tmp = Path(tempfile.mkdtemp(prefix="sift-live-"))
    try:
        logs = tmp / "logs"
        logs.mkdir()
        lines: list[str] = []
        for i in range(4):
            lines.append(
                f"2026-07-17 09:0{i}:00 ERROR MCM memory pressure: "
                f"AvailableMCM=0 working set {900 + i} MB"
            )
            lines.append(
                f"2026-07-17 09:0{i}:30 WARN smtp delivery retry {i} "
                f"queue depth growing"
            )
        (logs / "app.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Real Lemonade models, reached THROUGH the proxy so requests are counted.
        env = {
            **os.environ,
            "SIFT_DATA_DIR": str(tmp / "data"),
            "SIFT_GENERATION_BASE_URL": base,
            "SIFT_EMBEDDINGS_BASE_URL": base,
            "SIFT_GENERATION_MODEL": "user.Qwen2.5-14B-Instruct",
            "SIFT_EMBEDDINGS_MODEL": "Qwen3-Embedding-0.6B-GGUF",
            "SIFT_EMBEDDINGS_CONTEXT": "32768",
            "SIFT_GENERATION_CONTEXT": "16384",
        }

        for step in (["new", "live", "--input", str(logs)], ["ingest", "live"]):
            done = run(step, env, tmp)
            if done.returncode != 0:
                print("SETUP FAILED", step, done.returncode, done.stdout, done.stderr)
                return 1
        print("ingest OK\n")

        def measure(
            label: str, args: list[str], run_env: dict[str, str]
        ) -> tuple[subprocess.CompletedProcess[str], int]:
            before = embeds()
            proc = run(args, run_env, tmp)
            delta = embeds() - before
            print(f"{label}: exit={proc.returncode}  {embed_line(proc.stdout)}")
            print(f"    /v1/embeddings requests observed: {delta}")
            for ln in proc.stderr.strip().splitlines():
                print(f"    stderr: {ln[:130]}")
            if proc.returncode not in (0, 3):
                for ln in proc.stdout.strip().splitlines():
                    print(f"    stdout: {ln[:200]}")
            return proc, delta

        first, e1 = measure("run 1 (cold)      ", ["analyze", "live"], env)
        second, e2 = measure("run 2 (unchanged) ", ["analyze", "live"], env)
        forced, e3 = measure(
            "run 3 (--re-embed)", ["analyze", "live", "--re-embed"], env
        )
        pinned, _ = measure("run 4 (ctx pinned)", ["analyze", "live"], env)
        unset, _ = measure(
            "run 5 (ctx unset) ",
            ["analyze", "live"],
            {k: v for k, v in env.items() if k != "SIFT_GENERATION_CONTEXT"},
        )

        db = tmp / "data" / "cases" / "live" / "case.db"
        meta: dict[str, str] = {}
        if db.exists():
            conn = sqlite3.connect(db)
            try:
                meta = dict(
                    conn.execute(
                        "SELECT key, value FROM meta WHERE key LIKE 'embedding%'"
                    )
                )
            finally:
                conn.close()
        print(f"\ncase meta: {json.dumps(meta, indent=2, sort_keys=True)}")
        print(f"all proxied paths: {dict(SEEN)}\n")

        warn = "estimated rather than discovered"
        identity = "without a verifiable model identity"
        results = [
            ("run 1 exits 0", first.returncode in (0, 3)),
            ("run 2 exits 0", second.returncode in (0, 3)),
            ("run 3 exits 0", forced.returncode in (0, 3)),
            ("run 4 exits 0", pinned.returncode in (0, 3)),
            ("run 5 exits 0", unset.returncode in (0, 3)),
            ("run 1 issued embedding requests", e1 > 0),
            ("run 1 printed N new, 0 reused", "0 reused" in embed_line(first.stdout)),
            ("DET-01: run 2 issued ZERO embedding requests", e2 == 0),
            ("DET-01: run 2 printed 0 new", "0 new" in embed_line(second.stdout)),
            ("DET-01: --re-embed issued them again", e3 > 0),
            ("--re-embed printed 0 reused", "0 reused" in embed_line(forced.stdout)),
            ("real embedding dim recorded (1024)", meta.get("embedding_dim") == "1024"),
            (
                "real model identity recorded",
                meta.get("embedding_model") == "Qwen3-Embedding-0.6B-GGUF",
            ),
            (
                "reuse/embed split persisted to meta",
                meta.get("embedding_reused_count") is not None,
            ),
            ("D-04: no identity warning (model named)", identity not in second.stderr),
            ("D-10: NO warning when ctx pinned", warn not in pinned.stderr),
            ("D-10: warning WHEN ctx unset", warn in unset.stderr),
        ]

        print()
        ok = True
        for name, passed in results:
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
