#!/usr/bin/env python3
"""Small dependency-free Chrome DevTools Protocol client for loopback targets."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class CdpError(RuntimeError):
    """Raised when the loopback DevTools endpoint cannot be used safely."""


def _loopback_host(host: str) -> bool:
    return host.lower() in {"127.0.0.1", "localhost", "::1"}


def http_json(port: int, path: str, timeout: float = 3.0) -> Any:
    """Read JSON from a loopback CDP HTTP endpoint without proxy inheritance."""
    if not 1 <= port <= 65535:
        raise CdpError("CDP port must be between 1 and 65535")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"User-Agent": "ChromaPaw-Windows-Runtime/0.4"},
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise CdpError(f"CDP endpoint returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CdpError(f"CDP endpoint cannot be read: {exc}") from exc


class WebSocketConnection:
    """Minimal RFC 6455 client sufficient for local CDP request/response calls."""

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
            raise CdpError("CDP websocket URL must use ws://host:port/path")
        if not _loopback_host(parsed.hostname):
            raise CdpError("CDP websocket must stay on the loopback device")
        self._host = parsed.hostname
        self._port = parsed.port
        self._path = parsed.path or "/"
        if parsed.query:
            self._path += "?" + parsed.query
        self._timeout = timeout
        self._socket: socket.socket | None = None

    def __enter__(self) -> "WebSocketConnection":
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        try:
            stream = socket.create_connection((self._host, self._port), self._timeout)
            stream.settimeout(self._timeout)
            request = (
                f"GET {self._path} HTTP/1.1\r\n"
                f"Host: {self._host}:{self._port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n"
                f"Origin: http://127.0.0.1:{self._port}\r\n\r\n"
            )
            stream.sendall(request.encode("ascii"))
            response = self._read_headers(stream)
        except OSError as exc:
            raise CdpError(f"CDP websocket connection failed: {exc}") from exc

        lines = response.decode("iso-8859-1").split("\r\n")
        if not lines or " 101 " not in f" {lines[0]} ":
            stream.close()
            raise CdpError(f"CDP websocket upgrade failed: {lines[0] if lines else 'empty response'}")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            stream.close()
            raise CdpError("CDP websocket handshake integrity check failed")
        self._socket = stream
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self._socket is not None:
            try:
                self._send_frame(b"", opcode=0x8)
            except OSError:
                pass
            self._socket.close()
            self._socket = None

    @staticmethod
    def _read_headers(stream: socket.socket) -> bytes:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            block = stream.recv(4096)
            if not block:
                break
            data.extend(block)
            if len(data) > 65536:
                raise CdpError("CDP websocket response headers are too large")
        return bytes(data).split(b"\r\n\r\n", 1)[0]

    @staticmethod
    def _read_exact(stream: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            block = stream.recv(length - len(data))
            if not block:
                raise CdpError("CDP websocket closed unexpectedly")
            data.extend(block)
        return bytes(data)

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        if self._socket is None:
            raise CdpError("CDP websocket is not connected")
        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length <= 0xFFFF:
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._socket.sendall(header + mask + masked)

    def _recv_message(self) -> str:
        if self._socket is None:
            raise CdpError("CDP websocket is not connected")
        fragments = bytearray()
        message_opcode: int | None = None
        while True:
            first, second = self._read_exact(self._socket, 2)
            final = bool(first & 0x80)
            opcode = first & 0x0F
            masked = bool(second & 0x80)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(self._socket, 2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(self._socket, 8))[0]
            mask = self._read_exact(self._socket, 4) if masked else b""
            payload = self._read_exact(self._socket, length)
            if masked:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 0x8:
                raise CdpError("CDP websocket closed before returning a result")
            if opcode == 0x9:
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode in {0x1, 0x2}:
                message_opcode = opcode
                fragments = bytearray(payload)
            elif opcode == 0x0 and message_opcode is not None:
                fragments.extend(payload)
            else:
                continue
            if final:
                if message_opcode != 0x1:
                    raise CdpError("CDP returned an unexpected binary websocket message")
                try:
                    return fragments.decode("utf-8")
                except UnicodeError as exc:
                    raise CdpError("CDP returned invalid UTF-8") from exc

    def send_json(self, payload: dict[str, Any], request_id: int) -> dict[str, Any]:
        self._send_frame(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        while True:
            try:
                message = json.loads(self._recv_message())
            except json.JSONDecodeError as exc:
                raise CdpError(f"CDP returned invalid JSON: {exc}") from exc
            if isinstance(message, dict) and message.get("id") == request_id:
                return message


@dataclass(frozen=True)
class CdpTarget:
    id: str
    url: str
    title: str
    websocket_url: str


class CdpEndpoint:
    def __init__(self, port: int, timeout: float = 5.0) -> None:
        if not 1 <= port <= 65535:
            raise CdpError("CDP port must be between 1 and 65535")
        self.port = port
        self.timeout = timeout

    def version(self) -> dict[str, Any]:
        value = http_json(self.port, "/json/version", self.timeout)
        if not isinstance(value, dict):
            raise CdpError("CDP /json/version must return an object")
        return value

    def targets(self, allowed_schemes: set[str]) -> list[CdpTarget]:
        value = http_json(self.port, "/json/list", self.timeout)
        if not isinstance(value, list):
            raise CdpError("CDP /json/list must return an array")
        targets = []
        for item in value:
            if not isinstance(item, dict) or item.get("type") != "page":
                continue
            url = item.get("url")
            websocket_url = item.get("webSocketDebuggerUrl")
            target_id = item.get("id")
            if not all(isinstance(field, str) and field for field in (url, websocket_url, target_id)):
                continue
            if urllib.parse.urlparse(url).scheme not in allowed_schemes:
                continue
            parsed_ws = urllib.parse.urlparse(websocket_url)
            if parsed_ws.scheme != "ws" or not parsed_ws.hostname or not _loopback_host(parsed_ws.hostname):
                raise CdpError("CDP advertised a non-loopback websocket target")
            if parsed_ws.port != self.port:
                raise CdpError("CDP websocket target changed the expected loopback port")
            targets.append(
                CdpTarget(
                    id=target_id,
                    url=url,
                    title=str(item.get("title") or ""),
                    websocket_url=websocket_url,
                )
            )
        return targets

    def evaluate(self, target: CdpTarget, expression: str) -> Any:
        request_id = 1
        payload = {
            "id": request_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": False,
            },
        }
        try:
            with WebSocketConnection(target.websocket_url, self.timeout) as connection:
                response = connection.send_json(payload, request_id)
        except OSError as exc:
            raise CdpError(f"CDP websocket request failed: {exc}") from exc
        if "error" in response:
            raise CdpError(f"CDP Runtime.evaluate failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict) or result.get("exceptionDetails"):
            raise CdpError(f"CDP evaluation raised an exception: {result}")
        remote = result.get("result")
        if not isinstance(remote, dict):
            raise CdpError("CDP evaluation did not return a result object")
        return remote.get("value")

    def capture_png(self, target: CdpTarget) -> bytes:
        request_id = 2
        payload = {
            "id": request_id,
            "method": "Page.captureScreenshot",
            "params": {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
        }
        try:
            with WebSocketConnection(target.websocket_url, self.timeout) as connection:
                response = connection.send_json(payload, request_id)
        except OSError as exc:
            raise CdpError(f"CDP websocket request failed: {exc}") from exc
        if "error" in response:
            raise CdpError(f"CDP Page.captureScreenshot failed: {response['error']}")
        result = response.get("result")
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, str):
            raise CdpError("CDP screenshot did not return PNG data")
        try:
            return base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise CdpError("CDP screenshot returned invalid base64") from exc


def _injection_expression(css: str, css_hash: str, session_token: str) -> str:
    return """(() => {
  const id = "chromapaw-runtime-style";
  const expectedHash = %s;
  const session = %s;
  let style = document.getElementById(id);
  if (style && style.dataset.chromapawSession !== session) {
    return {applied: false, reason: "marker-owned-by-another-session"};
  }
  if (!style) {
    style = document.createElement("style");
    style.id = id;
    (document.head || document.documentElement).appendChild(style);
  }
  style.dataset.chromapawHash = expectedHash;
  style.dataset.chromapawSession = session;
  style.textContent = %s;
  return {
    applied: style.isConnected,
    hash: style.dataset.chromapawHash,
    session: style.dataset.chromapawSession,
    url: location.href
  };
})()""" % (json.dumps(css_hash), json.dumps(session_token), json.dumps(css))


def _verification_expression(css_hash: str, session_token: str) -> str:
    return """(() => {
  const style = document.getElementById("chromapaw-runtime-style");
  return {
    present: Boolean(style && style.isConnected),
    hash: style ? style.dataset.chromapawHash || null : null,
    session: style ? style.dataset.chromapawSession || null : null,
    matches: Boolean(style && style.dataset.chromapawHash === %s && style.dataset.chromapawSession === %s),
    url: location.href
  };
})()""" % (json.dumps(css_hash), json.dumps(session_token))


def _removal_expression(css_hash: str, session_token: str) -> str:
    return """(() => {
  const style = document.getElementById("chromapaw-runtime-style");
  if (!style) return {removed: true, reason: "already-absent", url: location.href};
  if (style.dataset.chromapawHash !== %s || style.dataset.chromapawSession !== %s) {
    return {removed: false, reason: "marker-identity-mismatch", url: location.href};
  }
  style.remove();
  return {removed: !document.getElementById("chromapaw-runtime-style"), url: location.href};
})()""" % (json.dumps(css_hash), json.dumps(session_token))


def inject_css(
    endpoint: CdpEndpoint,
    css: str,
    css_hash: str,
    session_token: str,
    allowed_schemes: set[str],
) -> list[dict[str, Any]]:
    results = []
    for target in endpoint.targets(allowed_schemes):
        value = endpoint.evaluate(target, _injection_expression(css, css_hash, session_token))
        results.append({"targetId": target.id, "title": target.title, "url": target.url, "result": value})
    return results


def verify_css(
    endpoint: CdpEndpoint,
    css_hash: str,
    session_token: str,
    allowed_schemes: set[str],
) -> list[dict[str, Any]]:
    results = []
    for target in endpoint.targets(allowed_schemes):
        value = endpoint.evaluate(target, _verification_expression(css_hash, session_token))
        results.append({"targetId": target.id, "title": target.title, "url": target.url, "result": value})
    return results


def remove_css(
    endpoint: CdpEndpoint,
    css_hash: str,
    session_token: str,
    allowed_schemes: set[str],
) -> list[dict[str, Any]]:
    results = []
    for target in endpoint.targets(allowed_schemes):
        value = endpoint.evaluate(target, _removal_expression(css_hash, session_token))
        results.append({"targetId": target.id, "title": target.title, "url": target.url, "result": value})
    return results
