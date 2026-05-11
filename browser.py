import socket
import ssl
from enum import Enum
import html
import re
import gzip
import time


class Scheme(str, Enum):
    HTTP = "http"
    HTTPS = "https"
    FILE = "file"
    DATA = "data"
    VIEW_SOURCE = "view-source"

    @property
    def default_port(self) -> int | None:
        return {Scheme.HTTP: 80, Scheme.HTTPS: 443}.get(self)

    @property
    def is_http(self) -> bool:
        return self in (Scheme.HTTP, Scheme.HTTPS)

    @classmethod
    def of(cls, scheme: str) -> Scheme:
        return cls(scheme.casefold())


MAX_REDIRECTS = 5
SOCKET_KEY_TEMPLATE = "{scheme}_{host}_{port}"

open_connections: dict = {}
cache: dict = {}


class URL:

    def __init__(self, url: str):
        self.full_url = url
        self.is_view_source = False

        scheme_str, hier_part = url.split(":", 1)
        self.scheme = Scheme.of(scheme_str)

        if self.scheme == Scheme.VIEW_SOURCE:
            scheme_str, hier_part = hier_part.split(":", 1)
            self.scheme = Scheme.of(scheme_str)
            self.is_view_source = True

        match self.scheme:
            case Scheme.FILE:
                self._build_file(hier_part)
            case Scheme.DATA:
                self._build_data(hier_part)
            case _ if self.scheme.is_http:
                self._build_authority(hier_part)
            case _:
                raise ValueError(f"Unsupported scheme: {self.scheme!r}")

    def _build_data(self, hier_part: str) -> None:

        assert not hier_part.startswith("//")

        # base64 is not supported
        self.content_type, self.data = hier_part.split(",", 1)

    def _build_file(self, hier_part: str) -> None:

        # Non empty authority and (file:/path) is not supported; only
        # file:///path is accepted.
        assert hier_part.startswith("//")
        self.url = hier_part.removeprefix("//")

    def _build_authority(self, hier_part: str) -> None:

        assert hier_part.startswith("//")

        self.port = self.scheme.default_port

        _, url = hier_part.split("//", 1)

        if "/" not in url:
            url = url + "/"
        self.host, url = url.split("/", 1)
        self.path = "/" + url

        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)

    @classmethod
    def _from_redirect(cls, location: str, scheme: Scheme, host: str) -> URL:
        if location.startswith("/"):
            location = f"{scheme.value}://{host}{location}"
        return cls(location)

    def request(self, n_redirects: int = 0) -> tuple[str, str]:
        if self.scheme.is_http:
            return self._request_http(n_redirects)
        if self.scheme == Scheme.FILE:
            return self._request_file()
        if self.scheme == Scheme.DATA:
            return self.data, self.content_type

    def _request_file(self) -> tuple[str, str]:
        with open(self.url, "r") as file:
            return file.read(), "text/plain"

    def _socket_key(self) -> str:
        return SOCKET_KEY_TEMPLATE.format(
            scheme=self.scheme, host=self.host, port=self.port
        )

    def _connect_socket(self):
        s = socket.socket(
            family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
        s.connect((self.host, self.port))
        if self.scheme == Scheme.HTTPS:
            cxt = ssl.create_default_context()
            s = cxt.wrap_socket(s, server_hostname=self.host)
        return s

    @staticmethod
    def _cache_is_fresh(max_age: float, stored_at: float) -> bool:
        return (time.monotonic() - stored_at) < max_age

    def _request_http(self, n_redirects: int) -> tuple[str, str]:

        if n_redirects > MAX_REDIRECTS:
            raise RuntimeError("too many redirects")

        cached = cache.get(self.full_url)

        if cached and self._cache_is_fresh(cached["max-age"], cached["stored-at"]):
            return cached["content"], cached["content-type"]

        key = self._socket_key()
        s = open_connections.get(key) or self._connect_socket()

        request = "GET {} HTTP/1.1\r\n".format(self.path)
        request += self._default_headers()
        request += "\r\n"

        # Check whether the connection is still open.
        try:
            s.send(request.encode("utf8"))
        except:
            s = self._connect_socket()
            s.send(request.encode("utf8"))

        response = s.makefile("rb")

        result = self._parse_http_response(response, n_redirects)
        open_connections[key] = s
        return result

    @staticmethod
    def _is_cacheable(status: int, cache_control: str) -> bool:
        return ("max-age" in cache_control) and (
            200 <= status < 300 or status in (301, 404)
        )

    def _parse_http_response(self, response, n_redirects):
        statusline = response.readline().decode("utf-8")
        version, status, explanation = statusline.split(" ", 2)
        status = int(status)

        response_headers = {}
        for line in response:
            line = line.decode("utf-8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        cache_control_header = response_headers.get("cache-control", "")

        content_encoding = response_headers.get("content-encoding")

        assert not content_encoding or content_encoding == "gzip"

        self.content_type = response_headers.get("content-type")

        if not content_encoding:
            content_length = int(response_headers["content-length"])
            content = response.read(content_length)
            content = content.decode("utf-8")
        else:
            chunks = []
            while True:
                chunk_size = int(response.readline().strip(), 16)

                if chunk_size == 0:
                    break

                compressed_chunk = response.read(chunk_size)
                response.read(2)  # consume trailing \r\n

                chunks.append(gzip.decompress(compressed_chunk))
            content = b"".join(chunks).decode()

        if self._is_cacheable(status, cache_control_header):
            _, max_age_str = cache_control_header.split("=", 1)
            cache[self.full_url] = {
                "max-age": float(max_age_str),
                "stored-at": time.monotonic(),
                "content-type": self.content_type,
                "content": content,
            }

        if 300 <= status < 400:
            location = response_headers["location"]
            redirectUrl = URL._from_redirect(location, self.scheme, self.host)
            return redirectUrl.request(n_redirects + 1)

        if self.is_view_source:
            self.content_type = "text/plain"

        return (content, self.content_type)

    def _default_headers(self):
        headers = self._build_header("Host", self.host)
        headers += self._build_header("Connection", "keep-alive")
        headers += self._build_header("User-Agent", "browser-engineering")
        headers += self._build_header("Accept-Encoding", "gzip")
        return headers

    def _build_header(self, key, value):
        return "{}: {}\r\n".format(key, value)


def show_html(body):
    text = re.sub(r"<[^>]*>", "", body)
    print(html.unescape(text), end="")


def show_text(body):
    print(body)


def load(url):
    body, content_type = url.request()
    if content_type == "text/html":
        show_html(body)
    else:
        show_text(body)


if __name__ == "__main__":
    while True:
        raw = input("Enter url: ")
        load(URL(raw))
        if input("Exit [y/n]: ").strip().lower() == "y":
            break
