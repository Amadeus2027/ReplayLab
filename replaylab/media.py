"""Bounded yt-dlp worker. Network restrictions are confined to this process."""

import ipaddress
import json
import socket
import sys
import urllib.request
from pathlib import Path

import yt_dlp
from yt_dlp.networking._urllib import UrllibRH

from .models import origin

MAX_BYTES = 200 * 1024 * 1024
DOWNLOAD_TIMEOUT = 120


def public_address(host: str) -> bool:
    if "%" in host:
        return False
    address = ipaddress.ip_address(host)
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not getattr(address, "ipv4_mapped", None)
        and not getattr(address, "sixtofour", None)
        and not getattr(address, "teredo", None)
        and address not in ipaddress.ip_network("64:ff9b::/96")
        and address not in ipaddress.ip_network("64:ff9b:1::/48")
    )


def validate_url(url: str):
    origin(url)  # HTTP(S), valid port, no embedded credentials.
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    addresses = socket.getaddrinfo(
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    if not addresses or any(not public_address(item[4][0]) for item in addresses):
        raise ValueError("Media URLs must resolve only to public Internet addresses")


def network_guard(event, args):
    if event == "socket.connect":
        # urllib resolves first; checking the actual numeric destination also blocks
        # DNS rebinding between URL validation and the connection attempt.
        address = args[1]
        if not isinstance(address, tuple) or not public_address(address[0]):
            raise ValueError("Blocked non-public media connection")
    elif event in {"subprocess.Popen", "os.system", "os.posix_spawn"}:
        raise ValueError("External media downloaders are disabled")


class ByteBudget:
    def __init__(self, limit=MAX_BYTES):
        self.remaining = limit


class LimitedResponse:
    def __init__(self, response, budget):
        self.response, self.budget = response, budget

    def __getattr__(self, name):
        return getattr(self.response, name)

    def read(self, size=None):
        limit = self.budget.remaining + 1
        data = self.response.read(limit if size is None or size < 0 else min(size, limit))
        self.budget.remaining -= len(data)
        if self.budget.remaining < 0:
            self.response.close()
            raise ValueError("Media acquisition exceeds the 200 MB total transfer limit")
        return data


class PolicyHandler(urllib.request.BaseHandler):
    handler_order = 100

    def __init__(self, budget):
        self.budget = budget

    def http_request(self, request):
        # Opener request processors also run before following every redirect.
        validate_url(request.full_url)
        return request

    https_request = http_request
    ftp_request = http_request

    def http_response(self, request, response):
        encoding = response.headers.get("Content-Encoding", "identity").lower()
        length = response.headers.get("Content-Length")
        if encoding != "identity" or (length and int(length) > self.budget.remaining):
            response.close()
            raise ValueError("Compressed or oversized media responses are not supported")
        return LimitedResponse(response, self.budget)

    https_response = http_response


class SafeUrllibRH(UrllibRH):
    _SUPPORTED_URL_SCHEMES = ("http", "https")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.budget = ByteBudget()

    def _create_instance(self, **kwargs):
        opener = super()._create_instance(**kwargs)
        opener.add_handler(PolicyHandler(self.budget))
        return opener


class SingleVideoDL(yt_dlp.YoutubeDL):
    def process_ie_result(self, result, *args, **kwargs):
        if result.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("Playlists are not supported")
        return super().process_ie_result(result, *args, **kwargs)


def download(source: str, directory: Path):
    # A proxy resolves destinations independently, so local DNS/socket checks cannot
    # enforce its onward routing. Fail closed without changing inherited proxy settings.
    if any(key != "no" for key in urllib.request.getproxies()):
        raise ValueError("Proxy-based media acquisition is not supported; upload a local video")
    validate_url(source)
    sys.addaudithook(network_guard)
    with SingleVideoDL(
        {
            "outtmpl": str(directory / "media.%(ext)s"),
            "format": "best[protocol=https][height<=720]/best[protocol=http][height<=720]"
            "/best[protocol=https]/best[protocol=http]",
            "noplaylist": True,
            "max_filesize": MAX_BYTES,
            "socket_timeout": 15,
            "retries": 0,
            "extractor_retries": 0,
            "fragment_retries": 0,
            "concurrent_fragment_downloads": 1,
            "fixup": "never",
            "js_runtimes": {},
            "remote_components": [],
            "http_headers": {"Accept-Encoding": "identity"},
            "quiet": True,
            "noprogress": True,
            "overwrites": False,
        }
    ) as downloader:
        # Restrict all extractor and download requests to the guarded stdlib transport.
        downloader._request_director = downloader.build_request_director([SafeUrllibRH], [])
        info = downloader.extract_info(source, download=True)
        if not info or info.get("entries") is not None:
            raise ValueError("Playlists are not supported")
        path = Path(downloader.prepare_filename(info)).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("Media downloader did not produce a file")
        if not 0 < path.stat().st_size <= MAX_BYTES:
            raise ValueError("Video must be between 1 byte and 200 MB")
        (directory / "result.json").write_text(json.dumps({"filename": path.name}))


if __name__ == "__main__":
    try:
        download(sys.argv[1], Path(sys.argv[2]))
    except Exception as exc:
        print(f"{type(exc).__name__}: {str(exc)[-1200:]}", file=sys.stderr)
        raise SystemExit(1) from None
