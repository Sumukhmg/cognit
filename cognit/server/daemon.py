"""Lightweight REST / JSON API server and Web Visualizer daemon for Cognit."""

from __future__ import annotations

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from cognit.agentic.explain import ExplainEngine
from cognit.agentic.intent_locks import IntentLockManager
from cognit.agentic.speculative import SpeculativeManager
from cognit.core.models import AgentMetadata
from cognit.core.repo import CognitRepo


class CognitRequestHandler(BaseHTTPRequestHandler):
    """HTTP Request handler for Cognit REST API and Web Dashboard."""

    repo: CognitRepo = None
    web_dir: Path = None

    def log_message(self, format, *args):
        # Quiet standard output during server operations
        return

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps({"status": "ok" if status < 400 else "error", "data": data}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            # REST API Routes
            if path == "/api/status":
                statuses = self.repo.status()
                head_cp = self.repo.get_head_checkpoint()
                self._send_json({
                    "branch": self.repo.get_active_branch(),
                    "head_checkpoint": head_cp.to_dict() if head_cp else None,
                    "files": [s.to_dict() for s in statuses],
                })
                return

            elif path == "/api/log":
                limit = int(query.get("limit", [50])[0])
                branch = query.get("branch", [None])[0]
                cps = self.repo.log(limit=limit, branch=branch)
                self._send_json([c.to_dict() for c in cps])
                return

            elif path == "/api/diff":
                mode = query.get("mode", ["semantic"])[0]
                diffs = self.repo.diff(mode=mode)
                self._send_json([d.to_dict() for d in diffs])
                return

            elif path == "/api/branches":
                branches = self.repo.list_branches()
                self._send_json(branches)
                return

            elif path == "/api/trials":
                spec = SpeculativeManager(self.repo.db, self.repo)
                trials = spec.list_trials()
                self._send_json([t.to_dict() for t in trials])
                return

            elif path == "/api/locks":
                mgr = IntentLockManager(self.repo.db)
                locks = mgr.list_active()
                self._send_json(locks)
                return

            elif path == "/api/explain":
                engine = ExplainEngine(self.repo.db, self.repo)
                file_p = query.get("file", [""])[0]
                sym = query.get("symbol", [None])[0]
                if not file_p:
                    self._send_json({"error": "Missing 'file' parameter"}, status=400)
                    return
                if sym:
                    res = [l.to_dict() for l in engine.explain_symbol(file_p, sym)]
                else:
                    res = engine.explain_file(file_p)
                self._send_json(res)
                return

            elif path == "/api/impact":
                target = query.get("target", [""])[0]
                if not target:
                    self._send_json({"error": "Missing 'target' parameter"}, status=400)
                    return
                report = self.repo.analyze_impact(target)
                self._send_json(report.to_dict())
                return

            elif path == "/api/context":
                goal = query.get("goal", [""])[0]
                tokens = int(query.get("tokens", [1500])[0])
                ctx = self.repo.build_context(goal, max_tokens=tokens)
                self._send_json({"goal": goal, "context": ctx, "approx_tokens": len(ctx) // 4})
                return

            elif path == "/api/workspaces":
                from cognit.agentic.workspace import WorkspaceManager
                wm = WorkspaceManager(self.repo)
                self._send_json([w.to_dict() for w in wm.list_workspaces()])
                return

            elif path == "/api/flight":
                from cognit.agentic.recorder import FlightRecorder
                fr = FlightRecorder(self.repo)
                self._send_json([s.to_dict() for s in fr.get_timeline()])
                return

            # Static Web Assets
            if path == "/" or not path:
                target_file = (self.web_dir / "index.html").resolve()
            else:
                rel_path = path.lstrip("/")
                target_file = (self.web_dir / rel_path).resolve()

            # Safety check against path traversal
            if not target_file.is_relative_to(self.web_dir.resolve()):
                self.send_error(HTTPStatus.FORBIDDEN, "Access denied")
                return

            if target_file.is_file():
                mime, _ = mimetypes.guess_type(str(target_file))
                mime = mime or "application/octet-stream"
                data = target_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            self.send_error(HTTPStatus.NOT_FOUND, "File not found")

        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = 0

        if content_length < 0 or content_length > 10 * 1024 * 1024:
            self._send_json({"error": "Invalid or excessive Content-Length"}, status=400)
            return

        body = self.rfile.read(content_length) if content_length > 0 else b""
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        try:
            if path == "/api/checkpoint":
                meta_dict = payload.get("agent_metadata", {})
                agent_meta = AgentMetadata.from_dict(meta_dict)
                cp = self.repo.create_checkpoint(
                    message=payload.get("message", "Agent checkpoint"),
                    author=payload.get("author", "Agent"),
                    agent_metadata=agent_meta,
                    branch=payload.get("branch"),
                )
                self._send_json(cp.to_dict())
                return

            elif path == "/api/branch":
                bname = payload.get("name")
                switch = payload.get("switch", False)
                if not bname:
                    self._send_json({"error": "Missing branch 'name'"}, status=400)
                    return
                self.repo.create_branch(bname)
                if switch:
                    self.repo.switch_branch(bname)
                self._send_json({"created": bname, "switched": switch})
                return

            elif path == "/api/undo":
                cp = self.repo.undo()
                if not cp:
                    self._send_json({"error": "No checkpoint to undo to"}, status=400)
                    return
                self._send_json(cp.to_dict())
                return

            elif path == "/api/flight/rollback":
                from cognit.agentic.recorder import FlightRecorder
                fr = FlightRecorder(self.repo)
                steps = int(payload.get("steps", 1))
                snap = fr.rollback(steps=steps)
                if not snap:
                    self._send_json({"error": "Cannot rollback"}, status=400)
                    return
                self._send_json(snap.to_dict())
                return

            elif path == "/api/flight/record":
                from cognit.agentic.recorder import FlightRecorder
                fr = FlightRecorder(self.repo)
                action = payload.get("action", "Agent action")
                agent_id = payload.get("agent_id", "agent")
                snap = fr.record_step(action=action, agent_id=agent_id)
                self._send_json(snap.to_dict())
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

        except Exception as e:
            self._send_json({"error": str(e)}, status=500)


def start_server(port: int = 5050, host: str = "127.0.0.1", root_dir: str = ".") -> None:
    """Launch the Cognit daemon server."""
    repo = CognitRepo.find_repo(root_dir)
    web_dir = Path(__file__).parent / "web"

    CognitRequestHandler.repo = repo
    CognitRequestHandler.web_dir = web_dir

    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, CognitRequestHandler)
    print(f"\n\033[96m\033[1m🚀 Cognit Agent Visualizer & API Server running at:\033[0m")
    print(f"   \033[92mhttp://{host}:{port}/\033[0m")
    print(f"\033[2mServing repo at {repo.root_dir}. Press Ctrl+C to stop.\033[0m\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\033[93mShutting down Cognit daemon...\033[0m")
        httpd.server_close()
