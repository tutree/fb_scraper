import asyncio
import socket
import struct
import threading
from typing import Optional, Dict
from sqlalchemy.orm import Session
from datetime import datetime
from ..models.proxy_log import ProxyLog
from ..core.config import settings
from ..core.logging_config import get_logger

logger = get_logger(__name__)


class _Socks5AuthBridge:
    """Local SOCKS5 proxy that forwards through an upstream SOCKS5 proxy with auth.

    Chromium does not support SOCKS5 + username/password authentication natively.
    This bridge listens locally without auth and relays every connection through
    the authenticated upstream, transparently handling the SOCKS5 handshake.
    """

    def __init__(self, upstream_host: str, upstream_port: int,
                 username: str, password: str):
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.username = username
        self.password = password
        self._server: Optional[asyncio.AbstractServer] = None
        self._local_port: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def local_port(self) -> Optional[int]:
        return self._local_port

    def _upstream_connect_sync(self, dest_addr: bytes, dest_port: int) -> socket.socket:
        """Open an authenticated SOCKS5 tunnel to dest through the upstream proxy (blocking)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((self.upstream_host, self.upstream_port))

        sock.sendall(b"\x05\x01\x02")
        resp = sock.recv(2)
        if resp[1] != 0x02:
            sock.close()
            raise RuntimeError("Upstream proxy rejected username/password auth method")

        auth_pkt = (b"\x01"
                    + bytes([len(self.username)]) + self.username.encode()
                    + bytes([len(self.password)]) + self.password.encode())
        sock.sendall(auth_pkt)
        auth_resp = sock.recv(2)
        if auth_resp[1] != 0x00:
            sock.close()
            raise RuntimeError("Upstream SOCKS5 auth failed")

        connect_pkt = (b"\x05\x01\x00\x03"
                       + bytes([len(dest_addr)]) + dest_addr
                       + struct.pack(">H", dest_port))
        sock.sendall(connect_pkt)
        conn_resp = sock.recv(10)
        if conn_resp[1] != 0x00:
            sock.close()
            raise RuntimeError(f"Upstream SOCKS5 connect failed: code {conn_resp[1]}")

        sock.setblocking(False)
        return sock

    async def _relay(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter):
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_client(self, client_reader: asyncio.StreamReader,
                             client_writer: asyncio.StreamWriter):
        upstream_writer = None
        try:
            greeting = await asyncio.wait_for(client_reader.read(256), timeout=10)
            if len(greeting) < 2 or greeting[0] != 0x05:
                client_writer.close()
                return

            client_writer.write(b"\x05\x00")
            await client_writer.drain()

            req = await asyncio.wait_for(client_reader.read(256), timeout=10)
            if len(req) < 4 or req[1] != 0x01:
                client_writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
                await client_writer.drain()
                client_writer.close()
                return

            atyp = req[3]
            if atyp == 0x01:
                dest_addr = socket.inet_ntoa(req[4:8]).encode()
                dest_port = struct.unpack(">H", req[8:10])[0]
            elif atyp == 0x03:
                alen = req[4]
                dest_addr = req[5:5 + alen]
                dest_port = struct.unpack(">H", req[5 + alen:7 + alen])[0]
            elif atyp == 0x04:
                dest_addr = socket.inet_ntop(socket.AF_INET6, req[4:20]).encode()
                dest_port = struct.unpack(">H", req[20:22])[0]
            else:
                client_writer.write(b"\x05\x08\x00\x01" + b"\x00" * 6)
                await client_writer.drain()
                client_writer.close()
                return

            loop = asyncio.get_event_loop()
            upstream_sock = await loop.run_in_executor(
                None, self._upstream_connect_sync, dest_addr, dest_port
            )

            client_writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
            await client_writer.drain()

            upstream_reader, upstream_writer = await asyncio.open_connection(
                sock=upstream_sock
            )

            await asyncio.gather(
                self._relay(client_reader, upstream_writer),
                self._relay(upstream_reader, client_writer),
            )

        except Exception as e:
            logger.debug(f"Bridge connection error: {e}")
        finally:
            try:
                client_writer.close()
            except Exception:
                pass
            if upstream_writer:
                try:
                    upstream_writer.close()
                except Exception:
                    pass

    async def _start_server(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        self._local_port = sock.getsockname()[1]
        sock.close()

        self._server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", self._local_port
        )
        logger.info(
            f"SOCKS5 auth bridge listening on 127.0.0.1:{self._local_port} "
            f"-> {self.upstream_host}:{self.upstream_port}"
        )
        await self._server.serve_forever()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start_server())

    def start(self) -> int:
        """Start the bridge in a background thread. Returns the local port."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        for _ in range(50):
            if self._local_port is not None:
                return self._local_port
            import time
            time.sleep(0.1)
        raise RuntimeError("SOCKS5 bridge failed to start within 5 seconds")

    def stop(self):
        if self._server and self._loop:
            self._loop.call_soon_threadsafe(self._server.close)


class ProxyManager:
    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self.proxies = settings.proxies
        self.current_index = 0
        self._bridge: Optional[_Socks5AuthBridge] = None

        if self.proxies:
            logger.info(f"ProxyManager: {len(self.proxies)} proxy(ies) loaded")
            for i, p in enumerate(self.proxies):
                try:
                    proto, rest = p.split("://")
                    if "@" in rest:
                        creds, host = rest.split("@")
                        user = creds.split(":")[0]
                        logger.info(f"  Proxy [{i}]: {proto}://{user}:***@{host}")
                    else:
                        logger.info(f"  Proxy [{i}]: {p}")
                except Exception:
                    logger.info(f"  Proxy [{i}]: {p}")
        else:
            logger.warning("ProxyManager: No proxies configured -- traffic will go DIRECT (no PROXY_LIST set)")

    def _needs_socks5_bridge(self, proxy_string: str) -> bool:
        """Return True if this is a socks5:// proxy with username:password."""
        return proxy_string.startswith("socks5://") and "@" in proxy_string

    def _ensure_bridge(self, proxy_string: str) -> Dict:
        """Start a local SOCKS5 bridge if needed and return Playwright proxy dict."""
        if self._bridge is None:
            protocol, rest = proxy_string.split("://")
            credentials, host_port = rest.split("@")
            username, password = credentials.split(":")
            host, port = host_port.rsplit(":", 1)

            self._bridge = _Socks5AuthBridge(host, int(port), username, password)
            local_port = self._bridge.start()
            logger.info(f"SOCKS5 auth bridge started on local port {local_port}")

        return {"server": f"socks5://127.0.0.1:{self._bridge.local_port}"}

    def get_next_proxy(self) -> Optional[Dict]:
        """Get next working proxy in round-robin fashion."""
        if not self.proxies:
            return None

        for _ in range(len(self.proxies)):
            proxy_url = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)

            try:
                if self.db:
                    proxy_log = (
                        self.db.query(ProxyLog)
                        .filter(ProxyLog.proxy_url == proxy_url)
                        .first()
                    )
                    if proxy_log and not proxy_log.is_active:
                        continue
            except Exception as e:
                logger.warning(f"DB unavailable for proxy check, using proxy directly: {e}")

            logger.info(f"Using proxy: {proxy_url}")
            if self._needs_socks5_bridge(proxy_url):
                return self._ensure_bridge(proxy_url)
            return self.parse_proxy_string(proxy_url)

        logger.warning("All proxies inactive, forcing next proxy")
        proxy_url = self.proxies[self.current_index]
        if self._needs_socks5_bridge(proxy_url):
            return self._ensure_bridge(proxy_url)
        return self.parse_proxy_string(proxy_url)

    def parse_proxy_string(self, proxy_string: str) -> Dict:
        """Parse proxy string into Playwright format.

        Supports:
          - protocol://user:pass@host:port
          - protocol://host:port
        """
        if "@" in proxy_string:
            protocol, rest = proxy_string.split("://")
            credentials, host = rest.split("@")
            username, password = credentials.split(":")
            return {
                "server": f"{protocol}://{host}",
                "username": username,
                "password": password,
            }
        else:
            return {"server": proxy_string}

    def report_proxy_result(self, proxy_url: str, success: bool) -> None:
        """Report proxy success/failure to update stats."""
        try:
            if not self.db:
                return
            proxy_log = (
                self.db.query(ProxyLog)
                .filter(ProxyLog.proxy_url == proxy_url)
                .first()
            )

            if proxy_log:
                if success:
                    proxy_log.success_count += 1
                else:
                    proxy_log.fail_count += 1
                    if proxy_log.fail_count > 10:
                        proxy_log.is_active = False
                        logger.warning(f"Proxy deactivated due to failures: {proxy_url}")
                proxy_log.last_used = datetime.now()
            else:
                proxy_log = ProxyLog(
                    proxy_url=proxy_url,
                    success_count=1 if success else 0,
                    fail_count=0 if success else 1,
                )
                self.db.add(proxy_log)

            self.db.commit()
        except Exception as e:
            logger.warning(f"DB unavailable, skipping proxy result logging: {e}")

    def close(self):
        """Stop the local bridge if running."""
        if self._bridge:
            self._bridge.stop()
            self._bridge = None
