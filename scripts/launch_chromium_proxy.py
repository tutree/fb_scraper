#!/usr/bin/env python3
"""
Open Playwright's bundled Chromium with a proxy from PROXY_LIST in .env.

Default: walk **every** `PROXY_LIST` entry **in order**: open Chromium with that proxy,
**wait until you close the window**, then open the next (only one SOCKS session at a time).
Use **`--one`** to open **only** a single proxy (`-n` picks which).

Chromium/Playwright do not support SOCKS5 proxy *authentication*. If your URL has
user:pass@, we start a tiny local HTTP proxy that logs into SOCKS5 (PySocks) and
point the browser at http://127.0.0.1:<port> with no credentials.

Playwright drives **Chromium** (open-source), not Google Chrome, unless you point
`--chromium-exe` / env `CHROMIUM_EXECUTABLE` at another Chromium build.

**Cookies:** Fresh profile (like incognito) unless **`--load-storage-state PATH`** is set
(Playwright `storage_state` JSON from a prior export). On **close**, session JSON is
**copied to the clipboard** by default (Ctrl+V). **`--no-clipboard`** turns that off.
Optional **`--save-storage PATH`** also writes the same JSON to disk (see `--help`).

**This repo / scraper:** use **`--fb-session`** with **`--url https://www.facebook.com`** (and
usually **`--one`**). On close you get **`cookies/<c_user>.json`** — only `facebook.com` cookies
and matching `origins` (no Google noise). Same format as `manual_login.py` / dashboard upload.

Optional: --chrome uses Google Chrome + CLI flags (SOCKS auth usually still broken).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from shutil import which
from urllib.parse import unquote, urlparse

def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_text_to_clipboard(text: str) -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()
        root.update()
        root.destroy()
        return True
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            fd, tmp = tempfile.mkstemp(suffix=".txt", text=True)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(text)
                lit = str(tmp).replace("'", "''")
                r = subprocess.run(
                    [
                        "powershell",
                        "-NoProfile",
                        "-Sta",
                        "-Command",
                        f"Set-Clipboard (Get-Content -Raw -LiteralPath '{lit}')",
                    ],
                    capture_output=True,
                    timeout=60,
                )
                return r.returncode == 0
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except Exception:
            pass
    return False


def _resolve_project_path(p: str | Path) -> Path:
    """Resolve path; relative paths are under project root."""
    t = Path(p)
    if not t.is_absolute():
        t = project_root() / t
    return t.resolve()


def _is_facebook_cookie_domain(domain: str) -> bool:
    """Host-only / domain cookies for facebook.com and subdomains (not fbcdn etc.)."""
    if not domain:
        return False
    d = domain.lstrip(".").lower()
    return d == "facebook.com" or d.endswith(".facebook.com")


def _is_facebook_origin(origin: str) -> bool:
    try:
        u = urlparse(origin)
        h = (u.hostname or "").lower()
    except Exception:
        return False
    return h == "facebook.com" or h.endswith(".facebook.com")


def _filter_storage_state_facebook_only(state: dict) -> dict:
    """Drop non-Facebook cookies and localStorage origins (smaller, scraper-aligned export)."""
    raw_cookies = state.get("cookies") if isinstance(state.get("cookies"), list) else []
    cookies = [
        c
        for c in raw_cookies
        if isinstance(c, dict) and _is_facebook_cookie_domain(str(c.get("domain", "") or ""))
    ]
    raw_origins = state.get("origins") if isinstance(state.get("origins"), list) else []
    origins: list = []
    for o in raw_origins:
        if not isinstance(o, dict):
            continue
        ou = o.get("origin")
        if isinstance(ou, str) and _is_facebook_origin(ou):
            origins.append(o)
    return {"cookies": cookies, "origins": origins}


def _extract_c_user_from_storage_state(state: dict) -> str | None:
    for c in state.get("cookies") or []:
        if isinstance(c, dict) and c.get("name") == "c_user":
            v = c.get("value")
            if v:
                return str(v).strip()
    return None


def _export_storage_path(base: str, proxy_index: int, *, numbered: bool) -> Path:
    """Target .json for context.storage_state(). numbered=True → stem-01.json, stem-02.json, …"""
    t = Path(base.strip())
    if not t.is_absolute():
        t = project_root() / t
    if t.suffix.lower() == ".json":
        t.parent.mkdir(parents=True, exist_ok=True)
        if numbered:
            return t.parent / f"{t.stem}-{proxy_index:02d}{t.suffix}"
        return t
    t.mkdir(parents=True, exist_ok=True)
    return t / f"facebook-proxy-{proxy_index:02d}-storage.json"


def _parse_proxy_list_from_env_file(env_path: Path) -> str:
    """Minimal .env reader for PROXY_LIST (no python-dotenv required)."""
    text = env_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("PROXY_LIST="):
            v = s.split("=", 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v
    return ""


def load_proxies(env_path: Path) -> list[str]:
    if not env_path.is_file():
        print(f"No .env at {env_path}", file=sys.stderr)
        sys.exit(1)
    try:
        from dotenv import dotenv_values

        raw = (dotenv_values(env_path).get("PROXY_LIST") or "").strip()
    except ImportError:
        raw = _parse_proxy_list_from_env_file(env_path).strip()
    if not raw:
        print("PROXY_LIST is empty in .env", file=sys.stderr)
        sys.exit(1)
    proxies = [p.strip() for p in raw.split(",") if p.strip()]
    if not proxies:
        print("PROXY_LIST has no entries after parsing", file=sys.stderr)
        sys.exit(1)
    return proxies


def _parse_proxy_url(proxy: str) -> tuple[str, str, int, str | None, str | None]:
    """Return (scheme, host, port, username, password)."""
    raw = proxy.strip()
    if "://" not in raw:
        raw = "http://" + raw
    u = urlparse(raw)
    if not u.hostname:
        raise ValueError(f"Invalid proxy URL (no host): {proxy!r}")
    port = u.port
    if port is None:
        if u.scheme in ("socks5", "socks4", "socks4a"):
            port = 1080
        else:
            port = 80
    user = unquote(u.username) if u.username else None
    pwd = unquote(u.password) if u.password is not None else None
    return (u.scheme.lower(), u.hostname, port, user, pwd)


def parse_proxy_for_playwright(proxy: str) -> dict:
    """Playwright proxy dict. No SOCKS user/pass (Chromium rejects it)."""
    scheme, host, port, user, pwd = _parse_proxy_url(proxy)
    server = f"{scheme}://{host}:{port}"
    out: dict = {"server": server}
    if user:
        out["username"] = user
    if pwd is not None:
        out["password"] = pwd
    return out


def _socks_proxy_type(scheme: str):
    import socks

    if scheme in ("socks5", "socks5h"):
        return socks.SOCKS5  # rdns=True on connect handles remote DNS
    if scheme in ("socks4", "socks4a"):
        return socks.SOCKS4
    raise ValueError(f"Not a SOCKS scheme: {scheme}")


def _read_http_headers(sock: socket.socket, max_bytes: int = 262144) -> bytes:
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < max_bytes:
        chunk = sock.recv(8192)
        if not chunk:
            break
        buf += chunk
    return buf


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            src.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


def _handle_proxy_client(client: socket.socket, cfg: dict) -> None:
    """HTTP proxy on client: CONNECT tunneling + absolute-form HTTP via SOCKS upstream."""
    try:
        import socks
    except ImportError:
        client.sendall(b"HTTP/1.1 500 PySocks missing\r\n\r\npip install PySocks")
        return

    try:
        buf = _read_http_headers(client)
        if not buf:
            return
        hdr_end = buf.find(b"\r\n\r\n")
        if hdr_end < 0:
            return
        head = buf[:hdr_end]
        body_tail = buf[hdr_end + 4 :]
        first_line = head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")

        def open_upstream(dest_host: str, dest_port: int) -> socket.socket | None:
            s = socks.socksocket()
            try:
                s.set_proxy(
                    _socks_proxy_type(cfg["scheme"]),
                    cfg["host"],
                    cfg["port"],
                    rdns=True,
                    username=cfg.get("username"),
                    password=cfg.get("password"),
                )
                s.settimeout(120)
                s.connect((dest_host, dest_port))
            except OSError:
                try:
                    s.close()
                except OSError:
                    pass
                return None
            return s

        if first_line.upper().startswith("CONNECT "):
            parts = first_line.split()
            if len(parts) < 2:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            target = parts[1]
            host, _, ps = target.partition(":")
            try:
                dport = int(ps) if ps else 443
            except ValueError:
                client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return
            remote = open_upstream(host, dport)
            if remote is None:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                return
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if body_tail:
                try:
                    remote.sendall(body_tail)
                except OSError:
                    pass
            t1 = threading.Thread(target=_pump, args=(client, remote), daemon=True)
            t2 = threading.Thread(target=_pump, args=(remote, client), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            try:
                remote.close()
            except OSError:
                pass
            return

        # GET http://host/path HTTP/1.1
        sp = first_line.split()
        if len(sp) < 3:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        method, url, ver = sp[0], sp[1], sp[2]
        if not url.startswith("http://"):
            client.sendall(b"HTTP/1.1 501 Not Implemented (use HTTPS or full http:// URL)\r\n\r\n")
            return
        pu = urlparse(url)
        if not pu.hostname:
            client.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        dport = pu.port or 80
        path = pu.path or "/"
        if pu.query:
            path += "?" + pu.query
        remote = open_upstream(pu.hostname, dport)
        if remote is None:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        rest = head.split(b"\r\n", 1)[1] if b"\r\n" in head else b""
        new_first = f"{method} {path} {ver}".encode("latin-1")
        new_head = new_first + b"\r\n" + rest + b"\r\n\r\n"
        try:
            remote.sendall(new_head + body_tail)
        except OSError:
            pass
        t1 = threading.Thread(target=_pump, args=(client, remote), daemon=True)
        t2 = threading.Thread(target=_pump, args=(remote, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        try:
            remote.close()
        except OSError:
            pass
    finally:
        try:
            client.close()
        except OSError:
            pass


def start_socks_auth_bridge(proxy_url: str) -> tuple[socketserver.ThreadingTCPServer, int]:
    """Local HTTP proxy -> authenticated SOCKS. Returns (server, port). Caller must shutdown()."""
    try:
        import socks  # noqa: F401
    except ImportError:
        print("SOCKS proxy has user/password; install PySocks: pip install PySocks", file=sys.stderr)
        sys.exit(1)

    scheme, host, port, user, pwd = _parse_proxy_url(proxy_url)
    if scheme not in ("socks5", "socks5h", "socks4", "socks4a"):
        raise ValueError("Internal: bridge only for SOCKS upstream")

    cfg = {"scheme": scheme, "host": host, "port": port, "username": user, "password": pwd}

    class _H(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            _handle_proxy_client(self.request, cfg)

    class _Srv(socketserver.ThreadingMixIn, socketserver.TCPServer):
        daemon_threads = True
        allow_reuse_address = True

    srv = _Srv(("127.0.0.1", 0), _H)
    _, bound_port = srv.server_address
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, bound_port


def find_google_chrome_executable() -> str | None:
    override = (os.environ.get("CHROME_PATH") or "").strip()
    if override and Path(override).is_file():
        return override

    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for c in candidates:
            if c and Path(c).is_file():
                return c
    elif sys.platform == "darwin":
        mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if Path(mac).is_file():
            return mac
    else:
        for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
            p = which(name)
            if p:
                return p
    return None


def launch_with_playwright(
    chosen: str,
    start_url: str,
    proxy_index: int,
    total_proxies: int,
    chromium_executable: str | None = None,
    save_storage: Path | None = None,
    copy_to_clipboard: bool = True,
    storage_state_file: Path | None = None,
    *,
    facebook_only: bool = False,
    fb_session: bool = False,
) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Install Playwright: pip install playwright", file=sys.stderr)
        print("Then install Chromium: playwright install chromium", file=sys.stderr)
        sys.exit(1)

    scheme, _h, _p, user, pwd = _parse_proxy_url(chosen)
    bridge: socketserver.ThreadingTCPServer | None = None
    try:
        if scheme in ("socks5", "socks5h", "socks4", "socks4a") and (user or pwd is not None):
            bridge, local_port = start_socks_auth_bridge(chosen)
            proxy = {"server": f"http://127.0.0.1:{local_port}"}
            print(
                "Browser: Chromium via Playwright"
                + (f" ({chromium_executable})" if chromium_executable else " (Playwright-managed build; not Google Chrome)"),
            )
            print(
                f"Using PROXY_LIST entry {proxy_index} of {total_proxies} from .env: "
                f"{_redact_proxy_for_display(chosen)}",
            )
            print(f"Local HTTP bridge: {proxy['server']} -> SOCKS (authenticated)")
        else:
            try:
                proxy = parse_proxy_for_playwright(chosen)
            except ValueError as e:
                print(e, file=sys.stderr)
                sys.exit(1)
            print(
                "Browser: Chromium via Playwright"
                + (f" ({chromium_executable})" if chromium_executable else " (Playwright-managed build; not Google Chrome)"),
            )
            print(
                f"Using PROXY_LIST entry {proxy_index} of {total_proxies} from .env: "
                f"{_redact_proxy_for_display(chosen)}",
            )
            print(f"Proxy server: {proxy['server']}")

        print("Close the browser window when you are done (this terminal waits until then).\n")
        if fb_session:
            print(
                "On close: Facebook-only storage_state → cookies/<c_user>.json (plus clipboard unless disabled).\n",
                flush=True,
            )
        elif facebook_only:
            print(
                "On close: only facebook.com cookies + origins"
                + (" — copied to the clipboard (Ctrl+V).\n" if copy_to_clipboard else ".\n"),
                flush=True,
            )
        elif copy_to_clipboard:
            print(
                "When you close it, the session JSON (cookies + origins) is copied to the clipboard — Ctrl+V to paste.\n",
                flush=True,
            )
        if save_storage is not None:
            print(
                f"Also saving to file:\n  {save_storage.resolve()}\n"
                + (
                    "(Facebook-filtered JSON.)\n"
                    if (facebook_only or fb_session)
                    else "(Same JSON — rename to cookies/<facebook_uid>.json or paste from clipboard in admin.)\n"
                ),
                flush=True,
            )
        if storage_state_file is not None:
            print(
                f"Loading session from:\n  {storage_state_file.resolve()}\n"
                "(Playwright storage_state: cookies + localStorage for listed origins.)\n",
                flush=True,
            )

        with sync_playwright() as p:
            # Playwright requires proxy on launch (not only on new_context); context uses the same routing.
            launch_kw: dict = {
                "headless": False,
                "proxy": proxy,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if chromium_executable:
                p_exe = Path(chromium_executable)
                if not p_exe.is_file():
                    print(f"CHROMIUM_EXECUTABLE not found: {p_exe}", file=sys.stderr)
                    sys.exit(1)
                launch_kw["executable_path"] = str(p_exe.resolve())
            browser = p.chromium.launch(**launch_kw)
            ctx_kw: dict = {"ignore_https_errors": True}
            if storage_state_file is not None:
                ctx_kw["storage_state"] = str(storage_state_file.resolve())
            context = browser.new_context(**ctx_kw)
            page = context.new_page()
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=120_000)
            except Exception as exc:
                print(f"Warning: first navigation failed ({exc}). You can still use the address bar.", file=sys.stderr)
            try:
                while browser.is_connected():
                    page.wait_for_timeout(500)
            except Exception:
                pass
            need_export = (
                save_storage is not None or copy_to_clipboard or facebook_only or fb_session
            )
            if need_export:
                try:
                    state = context.storage_state()
                    if facebook_only or fb_session:
                        state = _filter_storage_state_facebook_only(state)
                    payload = json.dumps(state, indent=2, ensure_ascii=False)

                    fb_path: Path | None = None
                    if fb_session:
                        uid = _extract_c_user_from_storage_state(state)
                        if not uid:
                            print(
                                "\n--fb-session: no c_user cookie after Facebook-only filter. "
                                "Log in at https://www.facebook.com in this window, then close again.\n",
                                file=sys.stderr,
                                flush=True,
                            )
                        else:
                            fb_path = project_root() / "cookies" / f"{uid}.json"
                            fb_path.parent.mkdir(parents=True, exist_ok=True)
                            fb_path.write_text(payload, encoding="utf-8")
                            print(
                                f"\nSaved Facebook session for scraper / dashboard:\n  {fb_path.resolve()}\n"
                                f"({len(state.get('cookies', []))} cookies, {len(state.get('origins', []))} origins)\n",
                                flush=True,
                            )

                    if save_storage is not None:
                        if fb_path is None or save_storage.resolve() != fb_path.resolve():
                            save_storage.write_text(payload, encoding="utf-8")
                            print(f"\nSaved storage state to:\n  {save_storage.resolve()}\n", flush=True)

                    if copy_to_clipboard:
                        if _copy_text_to_clipboard(payload):
                            print(
                                f"Copied {len(payload)} characters to the clipboard (storage_state JSON).\n",
                                flush=True,
                            )
                        else:
                            print(
                                "Warning: could not copy to clipboard. "
                                "Install/use a GUI session or use --save-storage PATH.",
                                file=sys.stderr,
                                flush=True,
                            )
                except Exception as exc:
                    print(f"Warning: could not export storage state: {exc}", file=sys.stderr, flush=True)
            try:
                browser.close()
            except Exception:
                pass
    except Exception as exc:
        msg = str(exc).lower()
        if "executable doesn't exist" in msg or "could not find browser" in msg:
            print("Chromium browser not installed for Playwright.", file=sys.stderr)
            print("Run: playwright install chromium", file=sys.stderr)
            sys.exit(1)
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        if bridge is not None:
            bridge.shutdown()
            bridge.server_close()


def launch_with_chrome_subprocess(chosen: str, start_url: str, proxy_index: int, *, wait: bool = False) -> None:
    exe = find_google_chrome_executable()
    if not exe:
        print("Could not find Google Chrome. Set CHROME_PATH or omit --chrome.", file=sys.stderr)
        sys.exit(1)

    user_data = Path(tempfile.mkdtemp(prefix="chromium-proxy-"))
    proxy_arg = chosen if "://" in chosen else f"http://{chosen}"
    cmd = [
        exe,
        f"--user-data-dir={user_data}",
        f"--proxy-server={proxy_arg}",
        "--no-first-run",
        "--no-default-browser-check",
        start_url,
    ]
    print(f"Browser: {exe} (--chrome; SOCKS auth in URL may be ignored)")
    print(f"Proxy #{proxy_index}: {_redact_proxy_for_display(chosen)}")
    print(f"Profile (temp): {user_data}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=sys.platform != "win32",
    )
    if wait:
        proc.wait()


def _redact_proxy_for_display(proxy: str) -> str:
    if "@" not in proxy:
        return proxy
    try:
        scheme, rest = proxy.split("://", 1)
        if "@" in rest:
            hostpart = rest.rsplit("@", 1)[-1]
            return f"{scheme}://***@{hostpart}"
    except ValueError:
        pass
    return proxy


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Playwright Chromium with PROXY_LIST (SOCKS5 auth via local bridge).",
    )
    parser.add_argument(
        "-n",
        "--index",
        type=int,
        default=1,
        metavar="N",
        help="With --one: which PROXY_LIST entry (1-based). Ignored when walking all proxies (default).",
    )
    parser.add_argument("-l", "--list", action="store_true", help="Print proxies (redacted) and exit")
    parser.add_argument(
        "--url",
        default="https://www.google.com/search?q=what+is+my+ip",
        help="Initial URL",
    )
    parser.add_argument("--env-file", type=Path, default=None, help="Path to .env")
    parser.add_argument(
        "--chromium-exe",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to chromium.exe (optional). Default: Playwright's Chromium build. Env: CHROMIUM_EXECUTABLE.",
    )
    parser.add_argument(
        "--chrome",
        action="store_true",
        help="Use Google Chrome + --proxy-server (SOCKS auth usually broken)",
    )
    parser.add_argument(
        "--one",
        action="store_true",
        help="Open only one Chromium window (-n selects proxy; default 1). Omit to walk all proxies in order.",
    )
    parser.add_argument(
        "--save-storage",
        metavar="PATH",
        default=None,
        help=(
            "Also write storage_state JSON to this path when you close (optional). "
            ".json file or directory; with multiple proxies, name-01.json, name-02.json, … "
            "Requires Playwright (not --chrome)."
        ),
    )
    parser.add_argument(
        "--clipboard",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Copy session JSON to clipboard on close (default: on). Use --no-clipboard to disable.",
    )
    parser.add_argument(
        "--load-storage-state",
        metavar="PATH",
        type=Path,
        default=None,
        help=(
            "Playwright storage_state JSON to restore at launch (cookies + origins localStorage). "
            "Save with --save-storage or paste clipboard JSON into a .json file. "
            "In sequential multi-proxy mode, this file is loaded for every window; use --one for a single proxy."
        ),
    )
    parser.add_argument(
        "--facebook-only",
        action="store_true",
        help=(
            "On close, export only facebook.com cookies + matching origins (smaller JSON). "
            "Use with --save-storage and/or clipboard; see also --fb-session."
        ),
    )
    parser.add_argument(
        "--fb-session",
        action="store_true",
        help=(
            "Recommended for this project: same as --facebook-only and always write cookies/<c_user>.json "
            "(Playwright format). Requires a logged-in Facebook session (c_user cookie). "
            "Use --url https://www.facebook.com."
        ),
    )
    args = parser.parse_args()

    chromium_exe: str | None = None
    if args.chromium_exe is not None:
        chromium_exe = str(args.chromium_exe.resolve())
    else:
        from_env = (os.environ.get("CHROMIUM_EXECUTABLE") or "").strip()
        chromium_exe = from_env or None

    env_path = args.env_file or (project_root() / ".env")
    proxies = load_proxies(env_path)

    if args.save_storage and args.chrome:
        print("--save-storage only works with Playwright (omit --chrome).", file=sys.stderr)
        sys.exit(1)

    if args.load_storage_state and args.chrome:
        print("--load-storage-state only works with Playwright (omit --chrome).", file=sys.stderr)
        sys.exit(1)

    if args.chrome and (args.facebook_only or args.fb_session):
        print("--facebook-only / --fb-session only work with Playwright (omit --chrome).", file=sys.stderr)
        sys.exit(1)

    if args.facebook_only and not args.fb_session and not args.save_storage and not args.clipboard:
        print(
            "--facebook-only needs --save-storage and/or clipboard (remove --no-clipboard), or use --fb-session.",
            file=sys.stderr,
        )
        sys.exit(1)

    load_storage_path: Path | None = None
    if args.load_storage_state is not None:
        load_storage_path = _resolve_project_path(args.load_storage_state)
        if not load_storage_path.is_file():
            print(f"--load-storage-state is not a file: {load_storage_path}", file=sys.stderr)
            sys.exit(1)
        try:
            raw = load_storage_path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("root must be a JSON object")
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"--load-storage-state: invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)

    if args.list:
        for i, p in enumerate(proxies, start=1):
            print(f"{i}. {_redact_proxy_for_display(p)}")
        return

    open_all = not args.one

    if open_all:
        if len(proxies) == 1:
            chosen = proxies[0]
            if args.chrome:
                launch_with_chrome_subprocess(chosen, args.url, 1)
            else:
                sp = (
                    _export_storage_path(args.save_storage, 1, numbered=False)
                    if args.save_storage
                    else None
                )
                launch_with_playwright(
                    chosen,
                    args.url,
                    1,
                    1,
                    chromium_exe,
                    save_storage=sp,
                    copy_to_clipboard=args.clipboard,
                    storage_state_file=load_storage_path,
                    facebook_only=args.facebook_only or args.fb_session,
                    fb_session=args.fb_session,
                )
            return
        print(
            f"Sequential mode: {len(proxies)} proxies — close each browser to open the next.\n",
        )
        for idx, chosen in enumerate(proxies, start=1):
            print(
                f"\n{'=' * 60}\n"
                f"  Proxy {idx} of {len(proxies)} — close the window when done to continue\n"
                f"{'=' * 60}\n",
            )
            if args.chrome:
                launch_with_chrome_subprocess(chosen, args.url, idx, wait=True)
            else:
                sp = (
                    _export_storage_path(args.save_storage, idx, numbered=True)
                    if args.save_storage
                    else None
                )
                launch_with_playwright(
                    chosen,
                    args.url,
                    idx,
                    len(proxies),
                    chromium_exe,
                    save_storage=sp,
                    copy_to_clipboard=args.clipboard,
                    storage_state_file=load_storage_path,
                    facebook_only=args.facebook_only or args.fb_session,
                    fb_session=args.fb_session,
                )
        print(f"\nFinished all {len(proxies)} proxies.\n")
        return

    if args.index < 1 or args.index > len(proxies):
        print(f"--index must be 1..{len(proxies)} (you have {len(proxies)} proxies)", file=sys.stderr)
        sys.exit(1)

    chosen = proxies[args.index - 1]
    if args.chrome:
        launch_with_chrome_subprocess(chosen, args.url, args.index)
    else:
        sp = (
            _export_storage_path(args.save_storage, args.index, numbered=False)
            if args.save_storage
            else None
        )
        launch_with_playwright(
            chosen,
            args.url,
            args.index,
            len(proxies),
            chromium_exe,
            save_storage=sp,
            copy_to_clipboard=args.clipboard,
            storage_state_file=load_storage_path,
            facebook_only=args.facebook_only or args.fb_session,
            fb_session=args.fb_session,
        )


if __name__ == "__main__":
    main()
