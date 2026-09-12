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
    _launch_codex,
    codex_locale_status,
    inspect_runtime_locale,
    activate_runtime,
    atomic_json,
    close_matching_codex_processes,
    compile_skin,
    detect_app_version,
    load_adapters,
    monitor_runtime,
    redact_result,
    refresh_active_runtime_css,
    refresh_preference_for_runtime_update,
    remember_preference,
    runtime_lock,
    runtime_status,
    resume_runtime,
    restore_runtime,
    restore_allowlisted_config,
    _print_result,
    select_adapter,
    _process_identity_status,
    _terminate_process_tree,
    _verify_renderer_readback,
)
try:
    from tests.test_validate_skin_package import make_v2_package  # type: ignore  # noqa: E402
except ImportError:
    from test_validate_skin_package import make_v2_package  # type: ignore  # noqa: E402


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+Xn4XAAAAAElFTkSuQmCC"
)

STANDALONE_EXECUTABLE_IDENTITY = {
    "fileVersion": "150.0.7871.115",
    "productVersion": "150.0.7871.115",
    "productName": "Codex",
    "companyName": "OpenAI OpCo, LLC",
    "fileDescription": "Codex",
    "originalFilename": "chrome.exe",
    "internalName": "chrome_exe",
    "signatureStatus": "NotSigned",
    "signerSubject": None,
    "sha256": "28c3e8b6c55fff39ecb12a5eb27f493abf997804247517aa7a46c277ca5d9e93",
}

APPX_EXECUTABLE_IDENTITY = {
    "fileVersion": "151.0.7922.76",
    "productVersion": "151.0.7922.76",
    "productName": "Codex",
    "companyName": "OpenAI OpCo, LLC",
    "fileDescription": "Codex",
    "originalFilename": "chrome.exe",
    "internalName": "chrome_exe",
    "signatureStatus": "Valid",
    "signerSubject": 'CN="OpenAI OpCo, LLC", O="OpenAI OpCo, LLC", C=US',
    "sha256": "0" * 64,
}

CURRENT_APPX_EXECUTABLE_IDENTITY = {
    "fileVersion": "152.0.7977.64",
    "productVersion": "152.0.7977.64",
    "productName": "Codex",
    "companyName": "OpenAI OpCo, LLC",
    "fileDescription": "Codex",
    "originalFilename": "chrome.exe",
    "internalName": "chrome_exe",
    "signatureStatus": "Valid",
    "signerSubject": 'CN="OpenAI OpCo, LLC", O="OpenAI OpCo, LLC", C=US',
    "sha256": "a7b0a4f38508d69a85ea51af9f6bd6a42c24a3904159ddff4d4d181eaadfff1c",
}


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
    def test_codex_locale_status_reads_and_normalises_desktop_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.toml"
            config.write_text(
                "localeOverride = 'en-US'\n[desktop]\nlocaleOverride = 'zh_cn'\n",
                encoding="utf-8",
            )
            result = codex_locale_status(config)
            self.assertTrue(result["valid"])
            self.assertEqual(result["requested"], "zh-CN")
            self.assertEqual(result["source"], "desktop.localeOverride")

    def test_codex_locale_status_rejects_non_locale_value_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config.toml"
            config.write_text('[desktop]\nlocaleOverride = "zh-CN --inspect"\n', encoding="utf-8")
            result = codex_locale_status(config)
            self.assertFalse(result["valid"])
            self.assertIsNone(result["requested"])
            self.assertIn("not a valid locale", result["error"])

    def test_launch_codex_passes_normalised_locale_as_one_argument(self) -> None:
        executable = Path("C:/Codex/app-26.707.9981.0/ChatGPT.exe")
        process = mock.Mock()
        with mock.patch("windows_runtime.subprocess.Popen", return_value=process) as popen:
            result = _launch_codex(executable, 54321, None, "zh_cn")
        self.assertIs(result, process)
        args = popen.call_args.args[0]
        self.assertIn("--lang=zh-CN", args)
        self.assertEqual(args.count("--lang=zh-CN"), 1)

    def test_launch_codex_dispatches_appx_strategy_without_direct_popen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "profile"
            executable = Path("C:/WindowsApps/OpenAI.Codex_26.901.1978.0_x64/app/ChatGPT.exe")
            process = mock.Mock(pid=101)
            adapter = {
                "launchStrategy": {
                    "kind": "appx-activation-manager",
                    "appUserModelId": "OpenAI.Codex_2p2nqsd0c76g0!App",
                }
            }
            with mock.patch(
                "windows_runtime._launch_packaged_codex", return_value=process
            ) as packaged, mock.patch("windows_runtime.subprocess.Popen") as popen:
                result = _launch_codex(
                    executable,
                    54321,
                    profile,
                    "zh-CN",
                    adapter,
                )
            self.assertIs(result, process)
            popen.assert_not_called()
            self.assertEqual(packaged.call_args.args[0], executable)
            switches = packaged.call_args.args[1]
            self.assertIn("--lang=zh-CN", switches)
            self.assertIn(f"--user-data-dir={profile}", switches)

    def test_inspect_runtime_locale_requires_main_document_and_navigator_match(self) -> None:
        target = mock.Mock(id="main", url="app://-/index.html")
        endpoint = mock.Mock()
        endpoint.targets.return_value = [target]
        endpoint.evaluate.return_value = {
            "navigatorLanguage": "zh-cn",
            "documentLanguage": "zh-CN",
        }
        result = inspect_runtime_locale(endpoint, {"app"}, "zh_CN")
        self.assertTrue(result["matches"])
        self.assertEqual(result["requested"], "zh-CN")

        endpoint.evaluate.return_value = {
            "navigatorLanguage": "zh-CN",
            "documentLanguage": "en",
        }
        result = inspect_runtime_locale(endpoint, {"app"}, "zh-CN")
        self.assertFalse(result["matches"])

    def test_runtime_lock_ignores_leftover_metadata_after_owner_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            lock = data_dir / ".runtime.lock"
            lock.write_text("pid=999999 time=old\n", encoding="utf-8")
            with runtime_lock(data_dir):
                self.assertTrue(lock.is_file())
            self.assertIn(f"pid={os.getpid()}", lock.read_text(encoding="utf-8"))
            with runtime_lock(data_dir):
                self.assertTrue(lock.is_file())

    def test_runtime_lock_rejects_concurrent_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with runtime_lock(data_dir):
                with self.assertRaises(RuntimeFailure) as context:
                    with runtime_lock(data_dir):
                        pass
            self.assertIn("another ChromaPaw runtime operation", str(context.exception))

    def test_process_identity_rejects_pid_reuse_at_same_path(self) -> None:
        executable = Path("C:/fixture/app-26.707.9981.0/ChatGPT.exe").resolve()
        with mock.patch(
            "windows_runtime._windows_process_paths", return_value={101: executable}
        ), mock.patch(
            "windows_runtime._windows_process_creation_times", return_value={101: 222}
        ), mock.patch("windows_runtime.sha256_file", return_value="a" * 64):
            identity = _process_identity_status(101, str(executable), 111, "a" * 64)
        self.assertTrue(identity["pathMatches"])
        self.assertFalse(identity["creationTimeMatches"])
        self.assertFalse(identity["matches"])

    def test_process_termination_refuses_pid_reuse_at_same_path(self) -> None:
        executable = Path("C:/fixture/app-26.707.9981.0/ChatGPT.exe").resolve()
        with mock.patch(
            "windows_runtime._windows_process_paths", return_value={101: executable}
        ), mock.patch(
            "windows_runtime._windows_process_creation_times", return_value={101: 222}
        ), mock.patch("windows_runtime.sha256_file", return_value="a" * 64), mock.patch(
            "windows_runtime.subprocess.run"
        ) as taskkill:
            with self.assertRaises(RuntimeFailure) as context:
                _terminate_process_tree(
                    101,
                    str(executable),
                    label="Codex",
                    creation_time=111,
                    executable_hash="a" * 64,
                )
        taskkill.assert_not_called()
        self.assertIn("creationTimeMatches", str(context.exception))

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
            with mock.patch("windows_runtime.build_preflight", return_value=preflight):
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
            with mock.patch("windows_runtime.build_preflight", return_value=preflight):
                with self.assertRaises(RuntimeFailure) as context:
                    refresh_preference_for_runtime_update(
                        data_dir,
                        ROOT / "runtime" / "windows-adapters.json",
                        acknowledged=True,
                    )
            self.assertIn("manifestHash", str(context.exception))
            saved = json.loads((data_dir / "preferred-skin.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cssHash"], "b" * 64)

    def test_refresh_preference_rejects_any_active_state_while_holding_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "active.json").write_text(
                json.dumps({"schemaVersion": 1, "sessionId": "stale-session"}),
                encoding="utf-8",
            )
            with mock.patch("windows_runtime.build_preflight") as preflight, mock.patch(
                "windows_runtime.remember_preference"
            ) as remember:
                with self.assertRaises(RuntimeFailure) as context:
                    refresh_preference_for_runtime_update(
                        data_dir,
                        ROOT / "runtime" / "windows-adapters.json",
                        acknowledged=True,
                    )
            preflight.assert_not_called()
            remember.assert_not_called()
            self.assertIn("active runtime session", str(context.exception))

    def test_refresh_preference_obeys_runtime_operation_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with runtime_lock(data_dir):
                with self.assertRaises(RuntimeFailure) as context:
                    refresh_preference_for_runtime_update(
                        data_dir,
                        acknowledged=True,
                    )
            self.assertIn("another ChromaPaw runtime operation", str(context.exception))

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
            compiled = {
                "css": "body { color: white; }",
                "cssHash": "e" * 64,
                "manifest": {"id": "fixture-skin"},
            }
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
                "windows_runtime._process_identity_status",
                side_effect=[{"matches": True}, {"matches": True, "running": True}],
            ), mock.patch(
                "windows_runtime._snapshot_runtime_css",
                return_value={"css": "old css", "cssHash": "b" * 64},
            ), mock.patch("windows_runtime._terminate_monitor_process") as terminate, mock.patch(
                "windows_runtime.inject_until_ready",
                return_value=[{"targetId": "fixture", "result": {"applied": True}}],
            ), mock.patch("windows_runtime._launch_monitor", return_value=monitor) as launch, mock.patch(
                "windows_runtime._record_process_creation_time", return_value=333
            ):
                result = refresh_active_runtime_css(
                    data_dir,
                    adapters,
                    acknowledged=True,
                )
            terminate.assert_called_once()
            launch.assert_called_once_with(data_dir, "fixture-session", "e" * 64)
            self.assertEqual(result["status"], "refreshed")
            self.assertEqual(result["monitorPid"], 303)
            saved = json.loads((data_dir / "active.json").read_text(encoding="utf-8"))
            preferred = json.loads(
                (data_dir / "preferred-skin.json").read_text(encoding="utf-8")
            )
            self.assertEqual(saved["cssHash"], "e" * 64)
            self.assertEqual(saved["monitorPid"], 303)
            self.assertEqual(preferred["cssHash"], "e" * 64)

    def test_refresh_active_runtime_css_rolls_back_when_monitor_restart_fails(self) -> None:
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
            state = {
                "schemaVersion": 1,
                "runtimeVersion": "0.4.7",
                "sessionId": "fixture-session",
                "sessionToken": "fixture-token",
                "status": "active",
                "pid": 101,
                "executable": str(executable),
                "executableHash": hashlib.sha256(b"fixture-app").hexdigest(),
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
                "monitorExecutableHash": "f" * 64,
            }
            (data_dir / "active.json").write_text(json.dumps(state), encoding="utf-8")
            preflight = {**state, "cssHash": "e" * 64}
            compiled = {
                "css": "new css",
                "cssHash": "e" * 64,
                "manifest": {"id": "fixture-skin"},
            }
            previous = {"css": "old css", "cssHash": "b" * 64}
            endpoint = mock.Mock()
            endpoint.version.return_value = {"Browser": "Chrome/fixture"}
            failed_monitor = mock.Mock(pid=303)
            failed_monitor.poll.return_value = 1
            restored_monitor = mock.Mock(pid=404)
            with mock.patch("windows_runtime.build_preflight", return_value=preflight), mock.patch(
                "windows_runtime.compile_skin", return_value=compiled
            ), mock.patch("windows_runtime.CdpEndpoint", return_value=endpoint), mock.patch(
                "windows_runtime._adapter_for_state", return_value={"id": "fixture-adapter"}
            ), mock.patch("windows_runtime._validate_browser_identity"), mock.patch(
                "windows_runtime._process_identity_status",
                side_effect=[{"matches": True}, {"matches": True, "running": True}],
            ), mock.patch(
                "windows_runtime._snapshot_runtime_css", return_value=previous
            ), mock.patch("windows_runtime._terminate_monitor_process"), mock.patch(
                "windows_runtime.inject_until_ready",
                return_value=[{"targetId": "fixture", "result": {"applied": True}}],
            ), mock.patch("windows_runtime._rollback_css_refresh") as rollback, mock.patch(
                "windows_runtime._launch_monitor",
                side_effect=[failed_monitor, restored_monitor],
            ), mock.patch("windows_runtime._record_process_creation_time", return_value=444):
                with self.assertRaises(RuntimeFailure) as context:
                    refresh_active_runtime_css(data_dir, adapters, acknowledged=True)
            rollback.assert_called_once_with(
                endpoint,
                previous,
                "e" * 64,
                "fixture-token",
                {"app"},
            )
            saved = json.loads((data_dir / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cssHash"], "b" * 64)
            self.assertEqual(saved["monitorPid"], 404)
            self.assertIn("rolled back", str(context.exception))

    def _assert_refresh_write_failure_rolls_back(self, failure_index: int) -> None:
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
            state = {
                "schemaVersion": 1,
                "runtimeVersion": "0.4.7",
                "sessionId": "fixture-session",
                "sessionToken": "fixture-token",
                "status": "active",
                "pid": 101,
                "executable": str(executable),
                "executableHash": hashlib.sha256(b"fixture-app").hexdigest(),
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
                "monitorExecutableHash": "f" * 64,
            }
            old_bytes = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            (data_dir / "active.json").write_bytes(old_bytes)
            (backup_dir / "active.json").write_bytes(old_bytes)
            old_preference = b'{"old":true}\n'
            (data_dir / "preferred-skin.json").write_bytes(old_preference)
            (backup_dir / "preferred-skin.json").write_bytes(old_preference)
            compiled = {"css": "new css", "cssHash": "e" * 64}
            preflight = {**state, "cssHash": "e" * 64}
            previous = {"css": "old css", "cssHash": "b" * 64}
            endpoint = mock.Mock()
            endpoint.version.return_value = {"Browser": "Chrome/fixture"}
            new_monitor = mock.Mock(pid=303)
            new_monitor.poll.return_value = None
            restored_monitor = mock.Mock(pid=404)

            import windows_runtime

            original_atomic_json = windows_runtime.atomic_json
            call_count = 0

            def fail_selected_write(path: Path, value: object) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == failure_index:
                    raise OSError(f"fixture write failure {failure_index}")
                original_atomic_json(path, value)

            with mock.patch("windows_runtime.build_preflight", return_value=preflight), mock.patch(
                "windows_runtime.compile_skin", return_value=compiled
            ), mock.patch("windows_runtime.CdpEndpoint", return_value=endpoint), mock.patch(
                "windows_runtime._adapter_for_state", return_value={"id": "fixture-adapter"}
            ), mock.patch("windows_runtime._validate_browser_identity"), mock.patch(
                "windows_runtime._process_identity_status",
                side_effect=[{"matches": True}, {"matches": True, "running": True}],
            ), mock.patch("windows_runtime._snapshot_runtime_css", return_value=previous), mock.patch(
                "windows_runtime._terminate_monitor_process"
            ), mock.patch(
                "windows_runtime.inject_until_ready",
                return_value=[{"targetId": "fixture", "result": {"applied": True}}],
            ), mock.patch("windows_runtime._rollback_css_refresh") as rollback, mock.patch(
                "windows_runtime._launch_monitor", side_effect=[new_monitor, restored_monitor]
            ), mock.patch(
                "windows_runtime._record_process_creation_time", return_value=444
            ), mock.patch("windows_runtime.atomic_json", side_effect=fail_selected_write):
                with self.assertRaises(RuntimeFailure) as context:
                    refresh_active_runtime_css(data_dir, adapters, acknowledged=True)
            rollback.assert_called_once()
            saved = json.loads((data_dir / "active.json").read_text(encoding="utf-8"))
            backup_saved = json.loads((backup_dir / "active.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["cssHash"], "b" * 64)
            self.assertEqual(saved["monitorPid"], 404)
            self.assertEqual(backup_saved, saved)
            self.assertEqual((data_dir / "preferred-skin.json").read_bytes(), old_preference)
            self.assertEqual((backup_dir / "preferred-skin.json").read_bytes(), old_preference)
            self.assertIn("rolled back", str(context.exception))

    def test_refresh_active_css_rolls_back_on_active_state_write_failure(self) -> None:
        self._assert_refresh_write_failure_rolls_back(1)

    def test_refresh_active_css_rolls_back_on_backup_state_write_failure(self) -> None:
        self._assert_refresh_write_failure_rolls_back(2)

    def test_refresh_active_css_rolls_back_on_preference_write_failure(self) -> None:
        self._assert_refresh_write_failure_rolls_back(3)

    def test_renderer_readback_retries_only_transient_timeout(self) -> None:
        timeout = CdpError("CDP websocket request failed: timed out")
        timeout.__cause__ = TimeoutError("timed out")
        checks = [{"targetId": "main", "result": {"matches": True}}]
        state = {"cssHash": "a" * 64, "sessionToken": "fixture"}
        with mock.patch("windows_runtime.verify_css", side_effect=[timeout, checks]) as verify, mock.patch(
            "windows_runtime.time.sleep"
        ) as sleep:
            result = _verify_renderer_readback(mock.Mock(), state, {"app"})
        self.assertEqual(result, (checks, None, True))
        self.assertEqual(verify.call_count, 2)
        sleep.assert_called_once_with(0.4)

    def test_renderer_readback_persistent_timeout_remains_failure(self) -> None:
        timeout = CdpError("CDP websocket request failed: timed out")
        timeout.__cause__ = TimeoutError("timed out")
        with mock.patch("windows_runtime.verify_css", side_effect=timeout) as verify, mock.patch(
            "windows_runtime.time.sleep"
        ) as sleep:
            with self.assertRaises(CdpError):
                _verify_renderer_readback(mock.Mock(), {"cssHash": "a", "sessionToken": "b"}, {"app"})
        self.assertEqual(verify.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_renderer_readback_does_not_retry_identity_or_script_errors(self) -> None:
        with mock.patch("windows_runtime.verify_css", side_effect=CdpError("invalid target identity")) as verify, mock.patch(
            "windows_runtime.time.sleep"
        ) as sleep:
            with self.assertRaises(CdpError):
                _verify_renderer_readback(mock.Mock(), {"cssHash": "a", "sessionToken": "b"}, {"app"})
        verify.assert_called_once()
        sleep.assert_not_called()

    def test_renderer_readback_preserves_style_mismatch(self) -> None:
        checks = [{"targetId": "main", "result": {"matches": False}}]
        with mock.patch("windows_runtime.verify_css", return_value=checks) as verify:
            result = _verify_renderer_readback(mock.Mock(), {"cssHash": "a", "sessionToken": "b"}, {"app"})
        self.assertEqual(result[0], checks)
        verify.assert_called_once()

    def test_renderer_readback_retries_locale_timeout_and_rechecks_css(self) -> None:
        timeout = CdpError("CDP websocket request failed: timed out")
        timeout.__cause__ = TimeoutError("timed out")
        state = {"cssHash": "a", "sessionToken": "b", "locale": {"requested": "zh-CN"}}
        checks = [{"targetId": "main", "result": {"matches": True}}]
        with mock.patch("windows_runtime.verify_css", return_value=checks) as verify, mock.patch(
            "windows_runtime.codex_locale_status", return_value={"valid": True, "requested": "zh-CN"}
        ), mock.patch("windows_runtime.inspect_runtime_locale", side_effect=[timeout, {"matches": False}]), mock.patch(
            "windows_runtime.time.sleep"
        ):
            result = _verify_renderer_readback(mock.Mock(), state, {"app"})
        self.assertEqual(verify.call_count, 2)
        self.assertFalse(result[2])

    def test_runtime_status_requires_process_adapter_browser_and_style_continuity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            executable = data_dir / "ChatGPT.exe"
            executable.write_bytes(b"fixture")
            adapter_file = data_dir / "adapters.json"
            adapter_file.write_text("{}", encoding="utf-8")
            package = data_dir / "skin"
            package.mkdir()
            manifest = package / "skin.json"
            manifest.write_text("{}", encoding="utf-8")
            state = {
                "schemaVersion": 1,
                "sessionId": "fixture-session",
                "sessionToken": "fixture-token",
                "pid": 101,
                "processCreationTime": 111,
                "executable": str(executable),
                "executableHash": hashlib.sha256(b"fixture").hexdigest(),
                "monitorPid": 202,
                "monitorCreationTime": 222,
                "monitorExecutable": str(Path(sys.executable).resolve()),
                "monitorExecutableHash": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                "port": 12345,
                "adapterFile": str(adapter_file),
                "adapterFileHash": hashlib.sha256(b"{}").hexdigest(),
                "adapterId": "fixture-adapter",
                "package": str(package),
                "packageId": "fixture-skin",
                "manifestHash": hashlib.sha256(b"{}").hexdigest(),
                "cssHash": "a" * 64,
                "allowedTargetSchemes": ["app"],
                "appVersion": "26.707.9981.0",
            }
            (data_dir / "active.json").write_text(json.dumps(state), encoding="utf-8")
            endpoint = mock.Mock()
            endpoint.version.return_value = {"Browser": "Chrome/fixture"}
            checks = [{"targetId": "fixture", "result": {"matches": True}}]
            with mock.patch(
                "windows_runtime._process_identity_status",
                side_effect=[{"matches": True}, {"matches": True}],
            ), mock.patch(
                "windows_runtime.compile_skin", return_value={"cssHash": "a" * 64}
            ), mock.patch(
                "windows_runtime.CdpEndpoint", return_value=endpoint
            ), mock.patch(
                "windows_runtime._adapter_for_state", return_value={"id": "fixture-adapter"}
            ), mock.patch("windows_runtime._validate_browser_identity"), mock.patch(
                "windows_runtime.verify_css", return_value=checks
            ):
                result = runtime_status(data_dir)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "active")
            self.assertTrue(all(result["continuity"].values()))
            self.assertEqual(result["targets"], checks)

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
                "sessionId": "fixture-session",
                "package": str(package),
                "executable": str(executable),
            }
            (data_dir / "active.json").write_text(json.dumps(active), encoding="utf-8")
            healthy = {"ok": True, "status": "active", "packageId": "fixture-skin"}
            healthy["sessionId"] = "fixture-session"
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
                json.dumps({"schemaVersion": 1, "sessionId": "fixture-session"}),
                encoding="utf-8",
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
                "windows_runtime.runtime_status",
                return_value={
                    "ok": False,
                    "status": "stale",
                    "sessionId": "fixture-session",
                },
            ), mock.patch("windows_runtime.restore_runtime", return_value={"status": "restored"}) as restore, mock.patch(
                "windows_runtime.build_preflight", return_value=preflight
            ), mock.patch("windows_runtime.activate_runtime", return_value=activated) as activate:
                result = resume_runtime(
                    data_dir, adapters, acknowledged=True, wait_seconds=4.0
                )
            restore.assert_called_once_with(
                data_dir,
                operation="restore",
                expected_session_id=mock.ANY,
                recover_stale_identities=True,
            )
            activate.assert_called_once()
            self.assertTrue(result["resumed"])
            self.assertTrue(result["staleSessionRecovered"])
            self.assertTrue(all(result["continuity"].values()))

    def test_resume_restore_is_guarded_by_the_observed_session(self) -> None:
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
                json.dumps({"schemaVersion": 1, "sessionId": "observed-session"}),
                encoding="utf-8",
            )
            with mock.patch(
                "windows_runtime.runtime_status",
                return_value={
                    "ok": False,
                    "status": "stale",
                    "sessionId": "observed-session",
                },
            ), mock.patch(
                "windows_runtime.restore_runtime", return_value={"status": "restored"}
            ) as restore, mock.patch(
                "windows_runtime.build_preflight", return_value=preference
            ), mock.patch(
                "windows_runtime.activate_runtime", return_value={"status": "active"}
            ):
                resume_runtime(data_dir, adapters, acknowledged=True)
            restore.assert_called_once_with(
                data_dir,
                operation="restore",
                expected_session_id="observed-session",
                recover_stale_identities=True,
            )

    def test_stale_restore_skips_reused_monitor_after_codex_exits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            backup_dir = data_dir / "sessions" / "fixture-session"
            backup_dir.mkdir(parents=True)
            state = {
                "schemaVersion": 1,
                "sessionId": "fixture-session",
                "sessionToken": "fixture-token",
                "pid": 101,
                "processCreationTime": 111,
                "executable": "C:/fixture/ChatGPT.exe",
                "executableHash": "a" * 64,
                "monitorPid": 202,
                "monitorCreationTime": 222,
                "monitorExecutable": str(Path(sys.executable).resolve()),
                "monitorExecutableHash": "b" * 64,
                "port": 12345,
                "allowedTargetSchemes": ["app"],
                "cssHash": "c" * 64,
                "backupDir": str(backup_dir),
                "packageId": "fixture-skin",
                "appVersion": "26.707.9981.0",
            }
            (data_dir / "active.json").write_text(json.dumps(state), encoding="utf-8")
            reused = {
                "running": True,
                "pathMatches": True,
                "creationTimeMatches": False,
                "executableHashMatches": True,
                "matches": False,
            }
            exited = {
                "running": False,
                "pathMatches": False,
                "creationTimeMatches": False,
                "executableHashMatches": True,
                "matches": False,
            }
            with mock.patch(
                "windows_runtime._process_identity_status", side_effect=[reused, exited]
            ), mock.patch(
                "windows_runtime._terminate_monitor_process"
            ) as terminate_monitor, mock.patch(
                "windows_runtime._terminate_runtime_process"
            ) as terminate_codex, mock.patch(
                "windows_runtime.CdpEndpoint"
            ) as endpoint, mock.patch(
                "windows_runtime.remove_css"
            ) as remove, mock.patch(
                "windows_runtime._config_backup_status", return_value={"unchanged": True}
            ):
                result = restore_runtime(
                    data_dir,
                    expected_session_id="fixture-session",
                    recover_stale_identities=True,
                )

            terminate_monitor.assert_not_called()
            terminate_codex.assert_not_called()
            endpoint.assert_not_called()
            remove.assert_not_called()
            self.assertFalse((data_dir / "active.json").exists())
            self.assertFalse(result["process"]["skipped"])
            self.assertEqual(result["process"]["reason"], "already-exited")
            self.assertTrue(result["monitor"]["skipped"])
            self.assertIsNone(result["transportClosed"])
            final = json.loads((backup_dir / "final.json").read_text(encoding="utf-8"))
            self.assertTrue(final["staleIdentityRecovery"])

    def test_resume_rejects_session_change_between_status_and_state_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            preference = {
                "schemaVersion": 1,
                "package": str(data_dir / "skin"),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
                "executable": str(data_dir / "ChatGPT.exe"),
                "executableHash": "c" * 64,
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
            }
            (data_dir / "preferred-skin.json").write_text(
                json.dumps(preference), encoding="utf-8"
            )
            (data_dir / "active.json").write_text(
                json.dumps({"schemaVersion": 1, "sessionId": "replacement-session"}),
                encoding="utf-8",
            )
            with mock.patch(
                "windows_runtime.runtime_status",
                return_value={
                    "ok": False,
                    "status": "stale",
                    "sessionId": "observed-session",
                },
            ), mock.patch("windows_runtime.restore_runtime") as restore:
                with self.assertRaises(RuntimeFailure) as context:
                    resume_runtime(data_dir, acknowledged=True)
            restore.assert_not_called()
            self.assertIn("session changed", str(context.exception))

    def test_restore_expected_session_guard_runs_before_process_or_css_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            (data_dir / "active.json").write_text(
                json.dumps(
                    {"schemaVersion": 1, "sessionId": "replacement-session"}
                ),
                encoding="utf-8",
            )
            with mock.patch(
                "windows_runtime._terminate_monitor_process"
            ) as terminate_monitor, mock.patch(
                "windows_runtime.remove_css"
            ) as remove, mock.patch(
                "windows_runtime._terminate_runtime_process"
            ) as terminate_codex:
                with self.assertRaises(RuntimeFailure) as context:
                    restore_runtime(
                        data_dir,
                        expected_session_id="observed-session",
                    )
            terminate_monitor.assert_not_called()
            remove.assert_not_called()
            terminate_codex.assert_not_called()
            self.assertIn("session changed", str(context.exception))

    def _assert_activation_write_failure_is_fully_compensated(
        self, failure_index: int
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "runtime-state"
            backup_dir = data_dir / "sessions" / "fixture-session"
            backup_dir.mkdir(parents=True)
            package = root / "skin"
            package.mkdir()
            executable = root / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            preference_before = b'{"preferred":"before"}\n'
            backup_preference_before = b'{"backupPreferred":"before"}\n'
            (data_dir / "preferred-skin.json").write_bytes(preference_before)
            (backup_dir / "preferred-skin.json").write_bytes(
                backup_preference_before
            )
            preflight = {
                "runningPids": [],
                "executable": str(executable.resolve()),
                "executableHash": hashlib.sha256(b"fixture").hexdigest(),
                "appVersion": "26.707.9981.0",
                "adapterId": "fixture-adapter",
                "adapterFile": str(ROOT / "runtime" / "windows-adapters.json"),
                "adapterFileHash": "d" * 64,
                "package": str(package.resolve()),
                "packageId": "fixture-skin",
                "manifestHash": "a" * 64,
                "cssHash": "b" * 64,
            }
            compiled = {"css": "fixture css", "cssHash": "b" * 64}
            process = mock.Mock(pid=101)
            process.poll.return_value = None
            monitor = mock.Mock(pid=202)
            monitor.poll.return_value = None

            import windows_runtime

            original_atomic_json = windows_runtime.atomic_json
            call_count = 0

            def fail_selected_write(path: Path, value: object) -> None:
                nonlocal call_count
                call_count += 1
                if call_count == failure_index:
                    raise OSError(f"fixture activation write failure {failure_index}")
                original_atomic_json(path, value)

            with mock.patch(
                "windows_runtime.build_preflight", return_value=preflight
            ), mock.patch(
                "windows_runtime.compile_skin", return_value=compiled
            ), mock.patch(
                "windows_runtime.select_adapter",
                return_value={"allowedTargetSchemes": ["app"]},
            ), mock.patch(
                "windows_runtime.create_backup",
                return_value={"backupDir": str(backup_dir)},
            ), mock.patch(
                "windows_runtime.choose_ephemeral_port", return_value=12345
            ), mock.patch(
                "windows_runtime._launch_codex", return_value=process
            ), mock.patch(
                "windows_runtime.wait_for_endpoint",
                return_value={"Browser": "Chrome/fixture"},
            ), mock.patch(
                "windows_runtime.inject_until_ready",
                return_value=[{"targetId": "fixture", "result": {"applied": True}}],
            ), mock.patch(
                "windows_runtime._record_process_creation_time",
                side_effect=[111, 222],
            ), mock.patch(
                "windows_runtime._launch_monitor", return_value=monitor
            ), mock.patch(
                "windows_runtime._terminate_monitor_process"
            ) as terminate_monitor, mock.patch(
                "windows_runtime._terminate_runtime_process"
            ) as terminate_codex, mock.patch(
                "windows_runtime.remove_css"
            ) as remove, mock.patch(
                "windows_runtime._config_backup_status",
                return_value={"unchanged": True},
            ), mock.patch(
                "windows_runtime.atomic_json", side_effect=fail_selected_write
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
            self.assertFalse((data_dir / "active.json").exists())
            self.assertFalse((backup_dir / "active.json").exists())
            self.assertEqual(
                (data_dir / "preferred-skin.json").read_bytes(), preference_before
            )
            self.assertEqual(
                (backup_dir / "preferred-skin.json").read_bytes(),
                backup_preference_before,
            )
            remove.assert_called_once()
            terminate_codex.assert_called_once()
            if failure_index >= 3:
                terminate_monitor.assert_called_once()
            else:
                terminate_monitor.assert_not_called()
            self.assertIn("rolled back", str(context.exception))
            failure = json.loads(
                (backup_dir / "failure.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failure["status"], "activation-failed")

    def test_activation_rolls_back_initial_active_write_failure(self) -> None:
        self._assert_activation_write_failure_is_fully_compensated(1)

    def test_activation_rolls_back_initial_backup_active_write_failure(self) -> None:
        self._assert_activation_write_failure_is_fully_compensated(2)

    def test_activation_rolls_back_monitored_active_write_failure(self) -> None:
        self._assert_activation_write_failure_is_fully_compensated(3)

    def test_activation_rolls_back_monitored_backup_active_write_failure(self) -> None:
        self._assert_activation_write_failure_is_fully_compensated(4)

    def test_activation_rolls_back_global_preference_write_failure(self) -> None:
        self._assert_activation_write_failure_is_fully_compensated(5)

    def test_activation_rolls_back_backup_preference_write_failure(self) -> None:
        self._assert_activation_write_failure_is_fully_compensated(6)

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

    def test_cdp_evaluate_normalises_transient_socket_timeout(self) -> None:
        endpoint = CdpEndpoint(54321)
        target = mock.Mock(websocket_url="ws://127.0.0.1:54321/devtools/page/fixture")
        connection = mock.MagicMock()
        connection.__enter__.return_value.send_json.side_effect = TimeoutError("timed out")
        with mock.patch("cdp_client.WebSocketConnection", return_value=connection):
            with self.assertRaises(CdpError) as context:
                endpoint.evaluate(target, "1")
        self.assertIn("websocket request failed", str(context.exception))

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
            adapter = select_adapter(
                executable,
                require_enabled=False,
                _identity_probe=lambda _path: APPX_EXECUTABLE_IDENTITY,
            )
            self.assertFalse(adapter["activationEnabled"])
            with self.assertRaises(RuntimeFailure) as context:
                select_adapter(executable)
            self.assertIn("activation is disabled", str(context.exception))

    def test_matching_path_without_matching_pe_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"renamed unrelated executable")
            impostor = {
                **STANDALONE_EXECUTABLE_IDENTITY,
                "productName": "Unrelated App",
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            }
            with self.assertRaises(RuntimeFailure) as context:
                select_adapter(executable, _identity_probe=lambda _path: impostor)
            self.assertIn("rejected the executable identity", str(context.exception))
            self.assertIn("productName", str(context.exception))
            self.assertIn("sha256", str(context.exception))

    def test_matching_explicit_pe_identity_selects_enabled_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "app-26.707.9981.0" / "ChatGPT.exe"
            executable.parent.mkdir()
            executable.write_bytes(b"fixture")
            adapter = select_adapter(
                executable,
                _identity_probe=lambda _path: STANDALONE_EXECUTABLE_IDENTITY,
            )
            self.assertEqual(adapter["id"], "chatgpt-electron-26-707-9981")
            self.assertEqual(
                adapter["verifiedExecutableIdentity"]["productName"], "Codex"
            )

    def test_matching_current_appx_selects_activation_manager_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = (
                Path(temporary)
                / "OpenAI.Codex_26.901.1978.0_x64__2p2nqsd0c76g0"
                / "app"
                / "ChatGPT.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"fixture")
            adapter = select_adapter(
                executable,
                _identity_probe=lambda _path: CURRENT_APPX_EXECUTABLE_IDENTITY,
            )
            self.assertTrue(adapter["activationEnabled"])
            self.assertEqual(
                adapter["launchStrategy"]["kind"], "appx-activation-manager"
            )

    def test_updated_appx_pins_exact_build_hash(self) -> None:
        builds = {
            "2854": "59569ff256d3e93ec5ec30505201cf11156b15c6c24130d66ff24105e4161fcf",
            "5003": "39e59e44d3f3aa4f6b7813d61b018ec0389ff28b6671f3d20bf258f2c167cc6c",
        }
        for build, digest in builds.items():
            with self.subTest(build=build), tempfile.TemporaryDirectory() as temporary:
                identity = {**CURRENT_APPX_EXECUTABLE_IDENTITY, "sha256": digest}
                executable = Path(temporary) / f"app-26.901.{build}.0" / "ChatGPT.exe"
                executable.parent.mkdir()
                executable.write_bytes(b"fixture")
                adapter = select_adapter(
                    executable, _identity_probe=lambda _path: identity
                )
                self.assertEqual(adapter["id"], f"chatgpt-electron-26-901-{build}-appx")
                self.assertEqual(adapter["launchStrategy"]["kind"], "appx-activation-manager")
                with self.assertRaisesRegex(RuntimeFailure, "sha256"):
                    select_adapter(
                        executable, _identity_probe=lambda _path: CURRENT_APPX_EXECUTABLE_IDENTITY,
                    )

    def test_runtime_compiles_modern_menu_guard_without_package_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = make_v2_package(Path(temporary))
            before = {path: path.read_bytes() for path in package.rglob('*') if path.is_file()}
            compiled = compile_skin(package)
            self.assertIn('[data-app-shell-unified-tab-strip] > div:has(> [role="menubar"])', compiled['css'])
            self.assertIn('var(--chromapaw-titlebar-surface, var(--chromapaw-surface-elevated))', compiled['css'])
            self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_appx_activation_cannot_adopt_preexisting_process(self) -> None:
        import windows_runtime
        executable = Path("C:/WindowsApps/OpenAI.Codex_26.901.2854.0_x64/app/ChatGPT.exe").resolve()
        response = mock.Mock(returncode=0, stdout=json.dumps({"pid": 314}), stderr="")
        with mock.patch.object(windows_runtime, "_windows_process_paths", return_value={314: executable}), \
             mock.patch.object(windows_runtime, "_discover_appx_install_locations", return_value=[executable.parent.parent]), \
             mock.patch.object(windows_runtime.subprocess, "run", return_value=response), \
             mock.patch.object(windows_runtime, "_terminate_runtime_process") as terminate:
            with self.assertRaisesRegex(RuntimeFailure, "reused an existing process"):
                windows_runtime._launch_packaged_codex(executable, [], {
                    "kind": "appx-activation-manager",
                    "appUserModelId": "OpenAI.Codex_2p2nqsd0c76g0!App",
                })
            terminate.assert_not_called()

    def test_adapter_registry_rejects_invalid_appx_application_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapters.json"
            registry = json.loads(
                (ROOT / "runtime" / "windows-adapters.json").read_text(encoding="utf-8")
            )
            registry["adapters"][-1]["launchStrategy"]["appUserModelId"] = "unsafe value"
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(RuntimeFailure) as context:
                load_adapters(path)
            self.assertIn("application user model id", str(context.exception))

    def test_enabled_adapter_requires_strong_identity_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapters.json"
            registry = json.loads(
                (ROOT / "runtime" / "windows-adapters.json").read_text(encoding="utf-8")
            )
            identity = registry["adapters"][0]["executableIdentity"]
            identity.pop("allowedSha256")
            identity.pop("fileVersion")
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaises(RuntimeFailure) as context:
                load_adapters(path)
            self.assertIn("must pin an executable hash", str(context.exception))

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
                "windows_runtime.probe_executable_identity",
                return_value=STANDALONE_EXECUTABLE_IDENTITY,
            ), mock.patch(
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

    def test_json_output_falls_back_to_utf8_when_console_cannot_encode(self) -> None:
        class LegacyConsole:
            encoding = "gbk"

            def write(self, value: str) -> int:
                raise UnicodeEncodeError("gbk", value, 0, 1, "fixture")

        class BinaryCapture:
            def __init__(self) -> None:
                self.data = b""

            def write(self, value: bytes) -> int:
                self.data += value
                return len(value)

        capture = BinaryCapture()
        console = LegacyConsole()
        console.buffer = capture
        with mock.patch.object(sys, "stdout", console):
            _print_result({"message": "Kyoto Rooftop �"}, True)

        self.assertIn("Kyoto Rooftop �", capture.data.decode("utf-8"))

    def test_launcher_only_runtime_upgrade_keeps_compiled_css_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = make_v2_package(Path(temporary))
            before = compile_skin(package)
            with mock.patch("windows_runtime.RUNTIME_VERSION", "99.0.0"):
                after = compile_skin(package)

            self.assertEqual(after["cssHash"], before["cssHash"])
            self.assertEqual(after["css"], before["css"])

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
            def run_monitor() -> None:
                with mock.patch(
                    "windows_runtime.probe_executable_identity",
                    return_value=STANDALONE_EXECUTABLE_IDENTITY,
                ):
                    result.append(
                        monitor_runtime(data_dir, "fixture-session", interval=0.1)
                    )

            thread = threading.Thread(target=run_monitor, daemon=True)
            thread.start()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and not server.fixture_state.present:
                time.sleep(0.05)
            self.assertTrue(server.fixture_state.present)
            active_path.unlink()
            thread.join(timeout=3)
            self.assertEqual(result, [0])

    def test_monitor_waits_for_reviewed_css_refresh_state_commit(self) -> None:
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
                "cssHash": "b" * 64,
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

            def run_monitor() -> None:
                with mock.patch(
                    "windows_runtime.probe_executable_identity",
                    return_value=STANDALONE_EXECUTABLE_IDENTITY,
                ):
                    result.append(
                        monitor_runtime(
                            data_dir,
                            "fixture-session",
                            interval=0.1,
                            expected_css_hash=compiled["cssHash"],
                            startup_wait_seconds=2.0,
                        )
                    )

            thread = threading.Thread(target=run_monitor, daemon=True)
            thread.start()
            time.sleep(0.15)
            self.assertTrue(thread.is_alive())
            active["cssHash"] = compiled["cssHash"]
            # Match the production refresh transaction: the concurrent monitor
            # must observe either the old state or the complete new JSON.
            atomic_json(active_path, active)
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
