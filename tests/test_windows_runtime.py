from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import socketserver
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cdp_client import CdpEndpoint, CdpError, inject_css, remove_css, verify_css  # noqa: E402
from windows_runtime import (  # noqa: E402
    RuntimeFailure,
    activate_runtime,
    close_matching_codex_processes,
    compile_skin,
    detect_app_version,
    load_adapters,
    monitor_runtime,
    redact_result,
    refresh_active_runtime_css,
    refresh_preference_for_runtime_update,
    remember_preference,
    resume_runtime,
    restore_allowlisted_config,
    select_adapter,
)
try:
    from tests.test_validate_skin_package import make_v2_package  # type: ignore  # noqa: E402
except ImportError:
    from test_validate_skin_package import make_v2_package  # type: ignore  # noqa: E402


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+Xn4XAAAAAElFTkSuQmCC"
)


def _read_exact(stream: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        block = stream.recv(length - len(data))
        if not block:
            raise ConnectionError("socket closed")
        data.extend(block)
    return bytes(data)


def _read_client_frame(stream: socket.socket) -> dict[str, object]:
    first, second = _read_exact(stream, 2)
    if first & 0x0F != 0x1 or not second & 0x80:
        raise ConnectionError("expected a masked text frame")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(stream, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(stream, 8))[0]
    mask = _read_exact(stream, 4)
    payload = _read_exact(stream, length)
    decoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return json.loads(decoded.decode("utf-8"))


def _server_frame(value: object) -> bytes:
    payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
    first = 0x81
    if len(payload) < 126:
        return struct.pack("!BB", first, len(payload)) + payload
    if len(payload) <= 0xFFFF:
        return struct.pack("!BBH", first, 126, len(payload)) + payload
    return struct.pack("!BBQ", first, 127, len(payload)) + payload


class FakeCdpState:
    def __init__(self) -> None:
        self.hash: str | None = None
        self.session: str | None = None
        self.present = False


class FakeCdpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        request = bytearray()
        while b"\r\n\r\n" not in request:
            request.extend(self.request.recv(4096))
        header = bytes(request).split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
        first_line = header.split("\r\n", 1)[0]
        path = first_line.split(" ")[1]
        if path == "/json/version":
            self._json(
                {
                    "Browser": "Chrome/150.0.0.0",
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.server.server_address[1]}/devtools/browser/1",
                }
            )
            return
        if path == "/json/list":
            self._json(
                [
                    {
                        "id": "page-1",
                        "type": "page",
                        "title": "Fixture",
                        "url": "app://fixture/index.html",
                        "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.server.server_address[1]}/devtools/page/1",
                    }
                ]
            )
            return
        if path.startswith("/devtools/"):
            self._websocket(header)
            return
        self.request.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")

    def _json(self, value: object) -> None:
        body = json.dumps(value).encode("utf-8")
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode("ascii")
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )

    def _websocket(self, header: str) -> None:
        headers = {}
        for line in header.split("\r\n")[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()
        accept = base64.b64encode(
            hashlib.sha1(
                (headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode(
                    "ascii"
                )
            ).digest()
        )
        self.request.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: "
            + accept
            + b"\r\n\r\n"
        )
        message = _read_client_frame(self.request)
        method = message.get("method")
        if method == "Page.captureScreenshot":
            result = {"data": base64.b64encode(PNG_1X1).decode("ascii")}
        else:
            expression = str(message.get("params", {}).get("expression", ""))
            state: FakeCdpState = self.server.fixture_state
            strings = []
            for line in expression.splitlines():
                if "expectedHash = " in line or "const session = " in line:
                    strings.append(json.loads(line.split("=", 1)[1].strip().rstrip(";")))
            if "style.textContent =" in expression:
                state.hash, state.session = strings[:2]
                state.present = True
                value = {
                    "applied": True,
                    "hash": state.hash,
                    "session": state.session,
                    "url": "app://fixture/index.html",
                }
            elif "marker-identity-mismatch" in expression:
                expected = [
                    json.loads(value)
                    for value in re.findall(
                        r"style\.dataset\.chromapaw(?:Hash|Session)\s*!==\s*(\"(?:\\.|[^\"])*\")",
                        expression,
                    )
                ]
                matches = expected == [state.hash, state.session]
                if matches:
                    state.present = False
                value = {"removed": matches, "url": "app://fixture/index.html"}
            else:
                expected = [
                    json.loads(value)
                    for value in re.findall(
                        r"style\.dataset\.chromapaw(?:Hash|Session)\s*===\s*(\"(?:\\.|[^\"])*\")",
                        expression,
                    )
                ]
                value = {
                    "present": state.present,
                    "hash": state.hash,
                    "session": state.session,
                    "matches": state.present and expected == [state.hash, state.session],
                    "url": "app://fixture/index.html",
                }
            result = {"result": {"type": "object", "value": value}}
        response = {"id": message["id"], "result": result}
        self.request.sendall(_server_frame(response))


class FakeCdpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), FakeCdpHandler)
        self.fixture_state = FakeCdpState()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    def __enter__(self) -> "FakeCdpServer":
        self.thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


class WindowsRuntimeTests(unittest.TestCase):
    def test_close_matching_codex_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(RuntimeFailure) as context:
            close_matching_codex_processes(
                Path("C:/fixture/app-26.707.9981.0/ChatGPT.exe"),
                acknowledged=False,
            )
        self.assertIn("explicit user confirmation", str(context.exception))

    @unittest.skipUnless(os.name == "nt", "Windows process close behavior")
    def test_close_matching_codex_rechecks_exact_process_identity(self) -> None:
        executable = Path("C:/fixture/app-26.707.9981.0/ChatGPT.exe").resolve()
        with mock.patch(
            "windows_runtime.running_pids",
            side_effect=[[101, 102], [101, 102], []],
        ), mock.patch(
            "windows_runtime._windows_process_paths",
            return_value={101: executable, 102: executable},
        ), mock.patch("windows_runtime.subprocess.run") as taskkill:
            result = close_matching_codex_processes(
                executable,
                acknowledged=True,
                timeout=1.0,
            )
        self.assertTrue(result["closed"])
        self.assertEqual(result["pids"], [101, 102])
        self.assertEqual(taskkill.call_count, 2)

    def test_remember_preference_persists_only_restart_safe_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            state = {
                "package": str(data_dir / "skin"),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(data_dir / "app-26.707.9981.0" / "ChatGPT.exe"),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "chatgpt-electron-26-707-9981",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
                "sessionToken": "must-not-persist",
                "port": 12345,
            }
            preference = remember_preference(data_dir, state)
            saved = json.loads((data_dir / "preferred-skin.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, preference)
            self.assertNotIn("sessionToken", saved)
            self.assertNotIn("port", saved)
            self.assertFalse(saved["applicationFilesModified"])

    def test_resume_requires_explicit_runtime_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeFailure) as context:
                resume_runtime(Path(temporary), acknowledged=False)
            self.assertIn("acknowledge-experimental-runtime", str(context.exception))

    def test_refresh_preference_allows_only_runtime_css_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            state = {
                "package": str(data_dir / "skin"),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(data_dir / "app-26.707.9981.0" / "ChatGPT.exe"),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
            }
            remember_preference(data_dir, state)
            preflight = {**state, "cssHash": "e" * 64}
            with mock.patch(
                "windows_runtime.runtime_status", return_value={"ok": True, "status": "inactive"}
            ), mock.patch("windows_runtime.build_preflight", return_value=preflight):
                result = refresh_preference_for_runtime_update(
                    data_dir,
                    ROOT / "runtime" / "windows-adapters.json",
                    acknowledged=True,
                )
            self.assertEqual(result["status"], "refreshed")
            self.assertEqual(result["cssHash"], "e" * 64)
            saved = json.loads((data_dir / "preferred-skin.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cssHash"], "e" * 64)

    def test_refresh_preference_rejects_package_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            state = {
                "package": str(data_dir / "skin"),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(data_dir / "app-26.707.9981.0" / "ChatGPT.exe"),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
            }
            remember_preference(data_dir, state)
            preflight = {**state, "manifestHash": "f" * 64, "cssHash": "e" * 64}
            with mock.patch(
                "windows_runtime.runtime_status", return_value={"ok": True, "status": "inactive"}
            ), mock.patch("windows_runtime.build_preflight", return_value=preflight):
                with self.assertRaises(RuntimeFailure) as context:
                    refresh_preference_for_runtime_update(
                        data_dir,
                        ROOT / "runtime" / "windows-adapters.json",
                        acknowledged=True,
                    )
            self.assertIn("manifestHash", str(context.exception))
            saved = json.loads((data_dir / "preferred-skin.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cssHash"], "b" * 64)

    def test_refresh_active_runtime_css_requires_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RuntimeFailure) as context:
                refresh_active_runtime_css(Path(temporary), acknowledged=False)
            self.assertIn("acknowledge-runtime-update", str(context.exception))

    def test_refresh_active_runtime_css_updates_state_and_restarts_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            backup_dir = data_dir / "sessions" / "fixture-session"
            backup_dir.mkdir(parents=True)
            package = root / "skin"
            package.mkdir()
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture-app")
            adapters = ROOT / "runtime" / "windows-adapters.json"
            executable_hash = hashlib.sha256(b"fixture-app").hexdigest()
            state = {
                "schemaVersion": 1,
                "runtimeVersion": "old-runtime",
                "sessionId": "fixture-session",
                "sessionToken": "fixture-token",
                "status": "active",
                "pid": 101,
                "executable": str(executable),
                "executableHash": executable_hash,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(adapters),
                "adapterFileHash": "d" * 64,
                "port": 12345,
                "allowedTargetSchemes": ["app"],
                "package": str(package),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "backupDir": str(backup_dir),
                "monitorPid": 202,
                "monitorExecutable": str(Path(sys.executable).resolve()),
            }
            (data_dir / "active.json").write_text(json.dumps(state), encoding="utf-8")
            preflight = {
                **state,
                "cssHash": "e" * 64,
            }
            compiled = {"css": "body { color: white; }", "cssHash": "e" * 64}
            endpoint = mock.Mock()
            endpoint.version.return_value = {"Browser": "Chrome/fixture"}
            monitor = mock.Mock(pid=303)
            monitor.poll.return_value = None
            # The runtime resolves executable paths before comparing process
            # identity.  macOS temp directories commonly expose /var as a
            # symlink to /private/var, so keep this fixture canonical too.
            paths = {101: executable.resolve(), 202: Path(sys.executable).resolve()}
            with mock.patch("windows_runtime.build_preflight", return_value=preflight), mock.patch(
                "windows_runtime.compile_skin", return_value=compiled
            ), mock.patch("windows_runtime.CdpEndpoint", return_value=endpoint), mock.patch(
                "windows_runtime._adapter_for_state", return_value={"id": "fixture-adapter"}
            ), mock.patch("windows_runtime._validate_browser_identity"), mock.patch(
                "windows_runtime._windows_process_paths", return_value=paths
            ), mock.patch("windows_runtime._terminate_monitor_process") as terminate, mock.patch(
                "windows_runtime.inject_until_ready",
                return_value=[{"targetId": "fixture", "result": {"applied": True}}],
            ), mock.patch("windows_runtime._launch_monitor", return_value=monitor):
                result = refresh_active_runtime_css(
                    data_dir,
                    adapters,
                    acknowledged=True,
                )
            terminate.assert_called_once()
            self.assertEqual(result["status"], "refreshed")
            self.assertEqual(result["monitorPid"], 303)
            saved = json.loads((data_dir / "active.json").read_text(encoding="utf-8"))
            preferred = json.loads(
                (data_dir / "preferred-skin.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["cssHash"], "e" * 64)
            self.assertEqual(saved["monitorPid"], 303)
            self.assertEqual(preferred["cssHash"], "e" * 64)

    def test_resume_returns_without_relaunch_for_matching_healthy_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            package = data_dir / "skin"
            executable = data_dir / "app-26.707.9981.0" / "ChatGPT.exe"
            preference = {
                "schemaVersion": 1,
                "package": str(package),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(executable),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
            }
            (data_dir / "preferred-skin.json").write_text(
                json.dumps(preference), encoding="utf-8"
            )
            active = {
                "schemaVersion": 1,
                "package": str(package),
                "executable": str(executable),
            }
            (data_dir / "active.json").write_text(json.dumps(active), encoding="utf-8")
            healthy = {"ok": True, "status": "active", "packageId": "fixture-skin"}
            with mock.patch("windows_runtime.runtime_status", return_value=healthy), mock.patch(
                "windows_runtime.activate_runtime"
            ) as activate:
                result = resume_runtime(data_dir, acknowledged=True)
            self.assertEqual(result["status"], "already-active")
            self.assertFalse(result["resumed"])
            activate.assert_not_called()

    def test_resume_recovers_stale_state_and_rechecks_all_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            package = data_dir / "skin"
            executable = data_dir / "app-26.707.9981.0" / "ChatGPT.exe"
            adapters = ROOT / "runtime" / "windows-adapters.json"
            preference = {
                "schemaVersion": 1,
                "package": str(package),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(executable),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(adapters),
                "adapterFileHash": "d" * 64,
            }
            (data_dir / "preferred-skin.json").write_text(
                json.dumps(preference), encoding="utf-8"
            )
            (data_dir / "active.json").write_text(
                json.dumps({"schemaVersion": 1}), encoding="utf-8"
            )
            preflight = {
                "executableHash": preference["executableHash"],
                "manifestHash": preference["manifestHash"],
                "cssHash": preference["cssHash"],
                "adapterFileHash": preference["adapterFileHash"],
                "adapterId": preference["adapterId"],
                "appVersion": preference["appVersion"],
            }
            activated = {"ok": True, "status": "active", "packageId": "fixture-skin"}
            with mock.patch(
                "windows_runtime.runtime_status", return_value={"ok": False, "status": "stale"}
            ), mock.patch("windows_runtime.restore_runtime", return_value={"status": "restored"}) as restore, mock.patch(
                "windows_runtime.build_preflight", return_value=preflight
            ), mock.patch("windows_runtime.activate_runtime", return_value=activated) as activate:
                result = resume_runtime(
                    data_dir, adapters, acknowledged=True, wait_seconds=4.0
                )
            restore.assert_called_once_with(data_dir, operation="restore")
            activate.assert_called_once()
            self.assertTrue(result["resumed"])
            self.assertTrue(result["staleSessionRecovered"])
            self.assertTrue(all(result["continuity"].values()))

    def test_cdp_inject_verify_remove_lifecycle(self) -> None:
        with FakeCdpServer() as server:
            endpoint = CdpEndpoint(server.server_address[1])
            self.assertTrue(endpoint.version()["Browser"].startswith("Chrome/"))
            applied = inject_css(endpoint, "body { color: red; }", "abc123", "session-token", {"app"})
            self.assertTrue(applied[0]["result"]["applied"])
            verified = verify_css(endpoint, "abc123", "session-token", {"app"})
            self.assertTrue(verified[0]["result"]["matches"])
            removed = remove_css(endpoint, "abc123", "session-token", {"app"})
            self.assertTrue(removed[0]["result"]["removed"])
            verified = verify_css(endpoint, "abc123", "session-token", {"app"})
            self.assertFalse(verified[0]["result"]["matches"])

    def test_cdp_capture_returns_png(self) -> None:
        with FakeCdpServer() as server:
            endpoint = CdpEndpoint(server.server_address[1])
            target = endpoint.targets({"app"})[0]
            self.assertTrue(endpoint.capture_png(target).startswith(b"\x89PNG"))

    def test_detects_clone_and_appx_versions(self) -> None:
        self.assertEqual(
            detect_app_version(Path("C:/Local/app-26.707.9981.0/ChatGPT.exe")),
            "26.707.9981.0",
        )
        self.assertEqual(
            detect_app_version(
                Path("C:/Program Files/WindowsApps/OpenAI.Codex_26.803.5235.0_x64__x/app/ChatGPT.exe")
            ),
            "26.803.5235.0",
        )

    def test_unknown_version_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "app-99.1.2.3" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            with self.assertRaises(RuntimeFailure) as context:
                select_adapter(executable)
            self.assertIn("not supported", str(context.exception))

    def test_disabled_candidate_adapter_cannot_activate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "app-26.803.5235.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            adapter = select_adapter(executable, require_enabled=False)
            self.assertFalse(adapter["activationEnabled"])
            with self.assertRaises(RuntimeFailure) as context:
                select_adapter(executable)
            self.assertIn("activation is disabled", str(context.exception))

    def test_adapter_registry_rejects_non_loopback_transport(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapters.json"
            registry = json.loads((ROOT / "runtime" / "windows-adapters.json").read_text(encoding="utf-8"))
            registry["transport"]["host"] = "0.0.0.0"
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(RuntimeFailure) as context:
                load_adapters(path)
            self.assertIn("127.0.0.1", str(context.exception))

    def test_user_facing_results_redact_nested_session_secrets(self) -> None:
        value = {
            "sessionToken": "top-secret",
            "targets": [{"result": {"session": "nested-secret", "matches": True}}],
        }
        redacted = redact_result(value)
        self.assertEqual(redacted["sessionToken"], "<redacted>")
        self.assertEqual(redacted["targets"][0]["result"]["session"], "<redacted>")
        self.assertTrue(redacted["targets"][0]["result"]["matches"])

    def test_adapter_registry_rejects_duplicate_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapters.json"
            registry = json.loads((ROOT / "runtime" / "windows-adapters.json").read_text(encoding="utf-8"))
            duplicate = dict(registry["adapters"][0])
            duplicate["id"] = "duplicate-id"
            registry["adapters"].append(duplicate)
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(RuntimeFailure) as context:
                load_adapters(path)
            self.assertIn("duplicate runtime adapter target", str(context.exception))

    @unittest.skipUnless(os.name == "nt", "Windows runtime rollback behavior")
    def test_launch_failure_records_rollback_without_active_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_root = root / "skin"
            package_root.mkdir()
            package = make_v2_package(package_root)
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            data_dir = root / "runtime-state"
            codex_home = root / "codex-home"
            codex_home.mkdir()
            config = codex_home / "config.toml"
            config.write_text("model = 'fixture'\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}), mock.patch(
                "windows_runtime._launch_codex",
                side_effect=RuntimeFailure("fixture launch denied"),
            ):
                with self.assertRaises(RuntimeFailure) as context:
                    activate_runtime(
                        package,
                        executable,
                        data_dir,
                        ROOT / "runtime" / "windows-adapters.json",
                        acknowledged=True,
                        profile_dir=None,
                        allow_parallel_profile=False,
                        wait_seconds=1.0,
                    )
            self.assertIn("rolled back", str(context.exception))
            self.assertFalse((data_dir / "active.json").exists())
            failures = list((data_dir / "sessions").glob("*/failure.json"))
            self.assertEqual(len(failures), 1)
            failure = json.loads(failures[0].read_text(encoding="utf-8"))
            self.assertFalse(failure["processLaunched"])
            self.assertTrue(failure["config"]["unchanged"])
            self.assertEqual(config.read_text(encoding="utf-8"), "model = 'fixture'\n")

    def test_compile_skin_embeds_background_and_overlay_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = make_v2_package(Path(temporary))
            compiled = compile_skin(package)
            self.assertIn("data:image/png;base64,", compiled["css"])
            self.assertIn('data-avatar-overlay-content-frame="true"', compiled["css"])
            self.assertNotRegex(
                compiled["css"],
                r"\.codex-avatar-root\s*\{[^}]*background\s*:\s*transparent",
            )
            self.assertIn(
                '[data-avatar-overlay-measure="notification-tray-row"]',
                compiled["css"],
            )
            self.assertIn("--chromapaw-notification-surface", compiled["css"])
            self.assertIn(
                '[data-app-shell-focus-area="right-panel"]',
                compiled["css"],
            )
            self.assertIn("--chromapaw-side-panel-surface", compiled["css"])
            self.assertNotIn('url("./background.png")', compiled["css"])
            self.assertRegex(compiled["cssHash"], r"^[0-9a-f]{64}$")

    def test_monitor_repairs_unstyled_target_and_exits_with_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, FakeCdpServer() as server:
            root = Path(temporary)
            package = make_v2_package(root)
            compiled = compile_skin(package)
            data_dir = root / "runtime-state"
            backup_dir = data_dir / "sessions" / "fixture-session"
            backup_dir.mkdir(parents=True)
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            adapter_file = ROOT / "runtime" / "windows-adapters.json"
            active = {
                "schemaVersion": 1,
                "sessionId": "fixture-session",
                "sessionToken": "fixture-token",
                "package": str(package),
                "cssHash": compiled["cssHash"],
                "port": server.server_address[1],
                "allowedTargetSchemes": ["app"],
                "backupDir": str(backup_dir),
                "pid": 1,
                "executable": str(executable),
                "executableHash": hashlib.sha256(b"fixture").hexdigest(),
                "adapterId": "chatgpt-electron-26-707-9981",
                "adapterFile": str(adapter_file),
                "adapterFileHash": hashlib.sha256(adapter_file.read_bytes()).hexdigest(),
            }
            active_path = data_dir / "active.json"
            active_path.write_text(json.dumps(active), encoding="utf-8")
            result: list[int] = []
            thread = threading.Thread(
                target=lambda: result.append(
                    monitor_runtime(data_dir, "fixture-session", interval=0.1)
                ),
                daemon=True,
            )
            thread.start()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not server.fixture_state.present:
                time.sleep(0.05)
            self.assertTrue(server.fixture_state.present)
            active_path.unlink()
            thread.join(timeout=3)
            self.assertEqual(result, [0])

    def test_restore_allowlisted_config_key_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.toml"
            backup = root / "before.toml"
            backup.write_text(
                "model = 'gpt-test'\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'before'\n",
                encoding="utf-8",
            )
            config.write_text(
                "model = 'gpt-test'\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'after'\n",
                encoding="utf-8",
            )
            result = restore_allowlisted_config(config, backup)
            self.assertTrue(result["restored"])
            self.assertEqual(config.read_text(encoding="utf-8"), backup.read_text(encoding="utf-8"))

    def test_restore_preserves_nonvolatile_user_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.toml"
            backup = root / "before.toml"
            backup.write_text(
                "model = 'before'\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'before'\n",
                encoding="utf-8",
            )
            config.write_text(
                "model = 'user-change'\nSKY_CUA_NATIVE_PIPE_DIRECTORY = 'after'\n",
                encoding="utf-8",
            )
            result = restore_allowlisted_config(config, backup)
            self.assertFalse(result["restored"])
            self.assertIn("user-change", config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
