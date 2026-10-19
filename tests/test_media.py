"""Network boundary regressions; no external sites or paid APIs."""

import io
import socket
import subprocess
import urllib.request
from email.message import Message
from urllib.response import addinfourl

import pytest

from replaylab import media, video


def resolved(ip):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))]


def test_private_mixed_and_special_addresses_are_rejected(monkeypatch):
    for address in [
        "127.0.0.1",
        "0.0.0.0",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "64:ff9b::a00:1",
        "2002:7f00:1::",
    ]:
        assert not media.public_address(address), address
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: resolved("93.184.216.34"))
    media.validate_url("https://public.example/video.mp4")
    for url in [
        "file:///etc/passwd",
        "ftp://public.example/x",
        "https://user:pass@public.example/x",
    ]:
        with pytest.raises(ValueError):
            media.validate_url(url)
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: resolved("93.184.216.34") + resolved("10.0.0.1")
    )
    with pytest.raises(ValueError, match="public"):
        media.validate_url("https://mixed.example/x")


def test_actual_connect_guard_blocks_rebinding_and_external_tools():
    media.network_guard("socket.connect", (None, ("93.184.216.34", 443)))
    for target in [("127.0.0.1", 80), ("169.254.169.254", 80), ("rebound.example", 80)]:
        with pytest.raises(ValueError):
            media.network_guard("socket.connect", (None, target))
    with pytest.raises(ValueError, match="External"):
        media.network_guard("subprocess.Popen", ())


def test_real_urllib_redirect_chain_is_checked_before_next_request(monkeypatch):
    seen = []
    destination = "http://127.0.0.1/private"

    def resolve(host, *a, **kw):
        return resolved("127.0.0.1" if host == "127.0.0.1" else "93.184.216.34")

    class Wire(urllib.request.BaseHandler):
        handler_order = 400

        def http_open(self, request):
            seen.append(request.full_url)
            headers = Message()
            headers["Location"] = destination
            response = addinfourl(io.BytesIO(b""), headers, request.full_url, code=302)
            response.msg = "Found"
            return response

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    handler = media.SafeUrllibRH(logger=None)
    opener = handler._create_instance(proxies={}, cookiejar=None)
    opener.add_handler(Wire())
    for destination in ["http://127.0.0.1/private", "ftp://public.example/video"]:
        seen.clear()
        with pytest.raises(ValueError):
            opener.open("http://public.example/start")
        assert seen == ["http://public.example/start"]


def test_transfer_budget_bounds_chunked_reads_and_rejects_large_headers():
    budget = media.ByteBudget(5)
    first = media.LimitedResponse(io.BytesIO(b"abc"), budget)
    assert first.read() == b"abc"
    second = media.LimitedResponse(io.BytesIO(b"def"), budget)
    assert second.read(2) == b"de"
    with pytest.raises(ValueError, match="transfer limit"):
        second.read()
    for headers in [{"Content-Length": "6"}, {"Content-Encoding": "gzip"}]:
        response = addinfourl(io.BytesIO(b"not read"), headers, "http://public.example", code=200)
        with pytest.raises(ValueError, match="Compressed or oversized"):
            media.PolicyHandler(media.ByteBudget(5)).http_response(None, response)
        assert response.closed


def test_deadline_cleans_partial_downloads_and_proxy_fails_closed(tmp_path, monkeypatch):
    def timeout(args, **kwargs):
        assert kwargs["timeout"] == media.DOWNLOAD_TIMEOUT
        directory = tmp_path / args[-1]
        (directory / "media.mp4.part").write_bytes(b"partial")
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(video.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        video.acquire("https://public.example/video.mp4", tmp_path)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://proxy.example"})
    with pytest.raises(ValueError, match="Proxy-based"):
        media.download("https://public.example/video.mp4", tmp_path)


def test_worker_uses_guarded_yt_dlp_transport_and_installs_socket_guard(tmp_path):
    """Real yt-dlp, fake public DNS/wire; the audit hook stays in the child process."""
    import sys
    from pathlib import Path

    script = r"""
import io, socket, sys, urllib.request
from email.message import Message
from pathlib import Path
from urllib.response import addinfourl
from replaylab import media

payload = Path("examples/real-video/source.webm").read_bytes()
original = media.SafeUrllibRH._create_instance
class Wire(urllib.request.BaseHandler):
    handler_order = 400
    def http_open(self, request):
        headers = Message()
        headers["Content-Type"] = "video/webm"
        headers["Content-Length"] = str(len(payload))
        response = addinfourl(io.BytesIO(payload), headers, request.full_url, code=200)
        response.msg = "OK"
        return response
    https_open = http_open

def instance(self, **kwargs):
    opener = original(self, **kwargs)
    opener.add_handler(Wire())
    return opener
media.SafeUrllibRH._create_instance = instance
media.urllib.request.getproxies = lambda: {}
socket.getaddrinfo = lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
media.download("https://public.example/video.webm", Path(sys.argv[1]))
assert (Path(sys.argv[1]) / "media.webm").read_bytes() == payload
with socket.socket() as connection:
    try:
        connection.connect(("127.0.0.1", 1))
    except ValueError:
        pass
    else:
        raise AssertionError("Actual socket was not blocked")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
