"""S-UI HTTP API helpers."""

from __future__ import annotations

import json
import socket
import ssl
from contextlib import contextmanager
from http.cookiejar import CookieJar
from typing import Iterator
from urllib.parse import urlencode, urljoin
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener


class SuiApiError(RuntimeError):
    """Raised when the S-UI API returns an unsuccessful response."""


class SuiWebApi:
    def __init__(self, base_url: str, resolve_ip: str | None = None, verify_tls: bool = True):
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        handlers = [ProxyHandler({}), HTTPCookieProcessor(CookieJar())]
        if not verify_tls:
            handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
        self._opener = build_opener(*handlers)
        self._resolve_ip = resolve_ip

    def login(self, username: str, password: str) -> None:
        response = self.post("api/login", {"user": username, "pass": password})
        if not response.get("success"):
            raise SuiApiError(f"login failed: {response.get('msg')}")

    def get(self, path: str) -> dict:
        url = urljoin(self.base_url, path)
        with _forced_dns(self._resolve_ip):
            with self._opener.open(url, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, data: dict[str, str]) -> dict:
        url = urljoin(self.base_url, path)
        body = urlencode(data).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        with _forced_dns(self._resolve_ip):
            try:
                with self._opener.open(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise SuiApiError(f"HTTP {exc.code}: {body[:500]}") from exc


class SuiApiV2:
    def __init__(self, base_url: str, token: str, resolve_ip: str | None = None, verify_tls: bool = True):
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.token = token
        handlers = [ProxyHandler({})]
        if not verify_tls:
            handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
        self._opener = build_opener(*handlers)
        self._resolve_ip = resolve_ip

    def get(self, path: str) -> dict:
        url = urljoin(self.base_url, path)
        request = Request(url, headers={"Token": self.token}, method="GET")
        with _forced_dns(self._resolve_ip):
            with self._opener.open(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, data: dict[str, str]) -> dict:
        url = urljoin(self.base_url, path)
        body = urlencode(data).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Token": self.token,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            method="POST",
        )
        with _forced_dns(self._resolve_ip):
            try:
                with self._opener.open(request, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise SuiApiError(f"HTTP {exc.code}: {body[:500]}") from exc


def web_base_url(values: dict[str, str], scheme: str = "http", host: str | None = None) -> str:
    target_host = host or values.get("VPS_HOST") or values["DOMAIN"]
    port = values.get("WEB_PORT", "2095")
    path = values.get("WEB_PATH", "/")
    return f"{scheme}://{target_host}:{port}{path}"


@contextmanager
def _forced_dns(resolve_ip: str | None) -> Iterator[None]:
    if not resolve_ip:
        yield
        return

    original_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto or socket.IPPROTO_TCP, "", (resolve_ip, port))]

    socket.getaddrinfo = patched_getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo
