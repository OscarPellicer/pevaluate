"""The local web server of ``pevaluate review``: the page, a JSON API over :mod:`.data` and
:mod:`.edits`, the files referenced by the results (behind opaque tokens) and the rebuild
buttons. It listens on 127.0.0.1 only, and every request needs the token of the URL it printed
(kept in a cookie), so other sites or users of the machine cannot read or change the grades.
"""
import html
import json
import mimetypes
import os
import secrets
import shlex
import sys
import subprocess
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import edits
from .data import (RebuildAction, ReviewConfig, describe_command, load_review, manifest_rebuild_command,
                   render_comment, render_markdown, Files, _read_csv)

STATIC = Path(__file__).with_name("static")
COOKIE = "pevaluate_review"


def open_answers_pending(cfg: ReviewConfig) -> list[str]:
    """Answers of the crops index with no saved grade: rerunning exam-open would grade them
    with the LLM. The rebuild buttons refuse while there are any."""
    if not (cfg.open_dir and cfg.index_csv and os.path.exists(cfg.index_csv)):
        return []
    import yaml

    path = os.path.join(cfg.open_dir, "open_evaluations.yaml")
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) if os.path.exists(path) else {}
    graded = {(str(r.get("student_id")), str(r.get("question_id"))) for r in (data or {}).get("responses", [])
              if r.get("status") in ("graded", "cached")}
    return [f"{r.get('student_id')} q{r.get('question_id')}" for r in _read_csv(cfg.index_csv)
            if (str(r.get("student_id")), str(r.get("question_id"))) not in graded]


def command_action(id_: str, label: str, argv: list[str], cwd: str, env: Optional[dict] = None,
                   guard=None) -> RebuildAction:
    """A rebuild button that runs a command (``guard`` returns an error message to refuse)."""
    def run():
        if guard:
            problem = guard()
            if problem:
                return False, problem
        result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
        return result.returncode == 0, (result.stdout + result.stderr)[-6000:]
    return RebuildAction(id_, label, describe_command(argv, cwd), run)


def default_actions(cfg: ReviewConfig) -> list[RebuildAction]:
    """Without a course record: rerun the last exam-open/exam-free command (saved grades only)."""
    if not cfg.open_dir:
        return []
    found = manifest_rebuild_command(cfg.open_dir)
    if not found:
        return []
    argv, cwd = found

    def guard():
        pending = open_answers_pending(cfg)
        if pending:
            return (f"{len(pending)} answer(s) have no saved grade ({', '.join(pending[:5])}...): rebuilding would grade "
                    "them with the LLM. Grade them first (exam-open), then rebuild here.")
        return None
    label = "Reconstruir notas y PDF" if cfg.lang == "es" else "Rebuild marks and PDFs"
    return [command_action("marks", label, argv, cwd, guard=guard)]


class ReviewServer:
    """One server for one or several parts of an assessment (e.g. the exam and the lab work), each
    with its own configuration; the page chooses the part, and every request names it."""

    def __init__(self, cfg: Optional[ReviewConfig] = None, parts: Optional[list[tuple[str, str, ReviewConfig]]] = None,
                 initial: Optional[str] = None):
        self.parts = parts or [("main", cfg.title, cfg)]
        self.cfg = self.parts[0][2] if initial is None else self.part(initial)
        self.token = secrets.token_urlsafe(18)
        self.files: dict[str, str] = {}
        self.lock = threading.Lock()  # one edit or rebuild at a time
        # How to start this server again (shown in the page: closing it stops the server).
        self.rerun = f"cd {shlex.quote(os.getcwd())} && {shlex.join([os.path.basename(sys.argv[0]), *sys.argv[1:]])}"
        self.last_seen = None         # last request from a page (pages ping every 10 s)
        self.closing_since = None     # a page said goodbye (closed or reloaded)
        for _, _, part_cfg in self.parts:
            if not part_cfg.rebuild_actions:
                part_cfg.rebuild_actions = default_actions(part_cfg)

    def part(self, part_id: Optional[str]) -> ReviewConfig:
        if not part_id:
            return self.cfg
        for pid, _, part_cfg in self.parts:
            if pid == part_id:
                return part_cfg
        raise edits.Invalid(f"Unknown part {part_id}.")

    def model(self, part_id: Optional[str] = None) -> dict:
        cfg = self.part(part_id)
        with self.lock:
            model = load_review(cfg)
            self.files.update(cfg._files.by_token)
        model["part"] = next(pid for pid, _, c in self.parts if c is cfg)
        model["rerun"] = self.rerun
        model["parts"] = [{"id": pid, "label": label} for pid, label, _ in self.parts]
        return model

    # --- Rendering of submission files --------------------------------------------------------
    def rendered(self, path: str) -> str:
        suffix = Path(path).suffix.lower()
        body = ""
        if suffix == ".ipynb":
            try:
                import nbformat
                from nbconvert import HTMLExporter

                exporter = HTMLExporter(template_name="lab")
                body, _ = exporter.from_notebook_node(nbformat.read(path, as_version=4))
                return body
            except Exception as e:
                body = f"<p>Notebook not rendered: {html.escape(str(e))}</p>"
        else:
            from ..utils import read_file_markdown

            files = Files()
            try:
                markdown = read_file_markdown(path).markdown
            except Exception as e:
                markdown = f"Not rendered: {e}"
            body = render_markdown(markdown, files, os.path.dirname(path))
            self.files.update(files.by_token)
        return ("<!doctype html><meta charset='utf-8'><style>body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;"
                "margin:1rem auto;padding:0 1rem}pre{background:#f4f4f4;padding:.5rem;overflow:auto}"
                "img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:2px 6px}</style>"
                "<script>window.MathJax={tex:{inlineMath:[['\\\\(','\\\\)']],displayMath:[['\\\\[','\\\\]']]},"
                "options:{ignoreHtmlClass:'.*|',processHtmlClass:'arithmatex'}};</script>"
                "<script async src='https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js'></script>" + body)

    # --- Edits --------------------------------------------------------------------------------
    def edit(self, kind: str, body: dict, part_id: Optional[str] = None) -> dict:
        cfg = self.part(part_id)
        with self.lock:
            if kind == "open":
                edits.save_open(cfg, body["student_id"], body["question_id"], body.get("score"), body.get("feedback", ""),
                                body.get("version"))
            elif kind == "mc":
                edits.save_mc(cfg, body["page"], body["number"], body.get("letter", ""), int(body.get("n_options", 4)),
                              body.get("version"))
            elif kind == "student":
                edits.save_student(cfg, body["page"], body.get("student_id", ""), body.get("student_name", ""),
                                   body.get("versions") or {})
            elif kind == "lab":
                edits.save_lab(cfg, body["key"], body.get("mark"), body.get("feedback", ""), body.get("members"),
                               body.get("version"))
            elif kind == "reviewed":
                edits.set_reviewed(cfg, list(body.get("keys") or []), bool(body.get("reviewed")))
            else:
                raise edits.Invalid(f"Unknown edit {kind}.")
        if kind != "reviewed" and cfg.on_edit:
            try:
                cfg.on_edit()
            except Exception as e:  # the edit is saved; recording it elsewhere must not fail it
                print(f"Warning: edit saved, but not recorded: {e}")
        return {"ok": True}

    def rebuild(self, action_id: str, part_id: Optional[str] = None) -> dict:
        action = next((a for a in self.part(part_id).rebuild_actions if a.id == action_id), None)
        if action is None:
            raise edits.Invalid(f"Unknown action {action_id}.")
        with self.lock:
            ok, output = action.run()
        return {"ok": ok, "output": output}

    # --- HTTP ---------------------------------------------------------------------------------
    def handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet: the terminal shows only the URL and errors
                pass

            def _authorized(self) -> bool:
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                ok = (cookie.get(COOKIE) and secrets.compare_digest(cookie[COOKIE].value, server.token)) or \
                    secrets.compare_digest(self.headers.get("X-Review-Token", ""), server.token)
                if ok:
                    server.last_seen, server.closing_since = time.time(), None
                return bool(ok)

            def _send(self, code: int, body: bytes, content_type: str, extra: Optional[dict] = None):
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, data):
                self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"),
                           "application/json; charset=utf-8")

            def do_GET(self):
                url = urlparse(self.path)
                if url.path == "/":
                    token = (parse_qs(url.query).get("t") or [""])[0]
                    if not (secrets.compare_digest(token, server.token) or self._authorized()):
                        return self._send(403, b"Open the URL printed by pevaluate review.", "text/plain")
                    page = (STATIC / "app.html").read_bytes()
                    return self._send(200, page, "text/html; charset=utf-8", {
                        "Set-Cookie": f"{COOKIE}={server.token}; Path=/; HttpOnly; SameSite=Strict"})
                if not self._authorized():
                    return self._send(403, b"Forbidden", "text/plain")
                if url.path.startswith("/static/"):
                    path = STATIC / Path(url.path).name
                    if path.is_file():
                        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                        return self._send(200, path.read_bytes(), kind)
                    return self._send(404, b"Not found", "text/plain")
                if url.path == "/api/ping":
                    return self._json(200, {"ok": True})
                if url.path == "/api/model":
                    try:
                        return self._json(200, server.model((parse_qs(url.query).get("part") or [None])[0]))
                    except Exception as e:
                        return self._json(500, {"error": f"{type(e).__name__}: {e}"})
                if url.path.startswith(("/f/", "/r/")):
                    path = server.files.get(url.path[3:])
                    if not path or not os.path.isfile(path):
                        return self._send(404, b"Not found", "text/plain")
                    if url.path.startswith("/r/"):
                        return self._send(200, server.rendered(path).encode("utf-8"), "text/html; charset=utf-8")
                    kind = mimetypes.guess_type(path)[0] or "application/octet-stream"
                    if kind.startswith("text/") or Path(path).suffix.lower() in (".sql", ".py", ".r", ".ipynb", ".yaml", ".yml"):
                        kind = ("text/html" if kind == "text/html" else "text/plain") + "; charset=utf-8"
                    return self._send(200, Path(path).read_bytes(), kind)
                return self._send(404, b"Not found", "text/plain")

            def do_POST(self):
                if not self._authorized():
                    return self._send(403, b"Forbidden", "text/plain")
                if urlparse(self.path).path == "/api/bye":  # the page was closed or reloaded
                    server.closing_since = time.time()
                    return self._json(200, {"ok": True})
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    return self._json(400, {"error": "Invalid JSON."})
                url = urlparse(self.path)
                path, part_id = url.path, (parse_qs(url.query).get("part") or [None])[0]
                try:
                    if path == "/api/markdown":
                        files = Files()
                        rendered = (render_comment(body.get("text", "")) if body.get("mode") == "comment"
                                    else render_markdown(body.get("text", ""), files))
                        server.files.update(files.by_token)
                        return self._json(200, {"html": rendered})
                    if path.startswith("/api/edit/"):
                        return self._json(200, server.edit(path.rsplit("/", 1)[1], body, part_id))
                    if path.startswith("/api/rebuild/"):
                        return self._json(200, server.rebuild(path.rsplit("/", 1)[1], part_id))
                except edits.Conflict as e:
                    return self._json(409, {"error": str(e)})
                except (edits.Invalid, KeyError) as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
                return self._json(404, {"error": "Not found"})

        return Handler

    def watch(self, httpd, grace: float = 2.0, idle: float = 600.0) -> None:
        """Stop the server when its page is closed: the page says goodbye and nothing comes back
        within ``grace`` seconds (a reload or another tab would), or no page pinged for ``idle``."""
        def loop():
            while True:
                time.sleep(0.5)
                now = time.time()
                if self.last_seen is None:
                    continue
                if (self.closing_since and now - self.closing_since > grace) or now - self.last_seen > idle:
                    print(f"The review page was closed: server stopped. All edits are saved. To open it again:\n  {self.rerun}")
                    httpd.shutdown()
                    return
        threading.Thread(target=loop, daemon=True).start()

    def serve(self, port: int = 0, open_browser: bool = True, keep_open: bool = False) -> None:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), self.handler())
        if not keep_open:
            self.watch(httpd)
        url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={self.token}"
        title = self.cfg.title if len(self.parts) == 1 else f"{self.cfg.title} (+{len(self.parts) - 1} more part(s), chosen in the page)"
        print(f"Review app for '{title}': {url}")
        print("Edits are saved to the result files as you make them. The server stops when the page is closed (or Ctrl+C).")
        if open_browser:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            httpd.server_close()


def serve(cfg: Optional[ReviewConfig] = None, port: int = 0, open_browser: bool = True,
          parts: Optional[list[tuple[str, str, ReviewConfig]]] = None, initial: Optional[str] = None,
          keep_open: bool = False) -> None:
    ReviewServer(cfg, parts=parts, initial=initial).serve(port, open_browser, keep_open)
