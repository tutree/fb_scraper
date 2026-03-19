"""Local SOCKS5 bridge: no-auth on localhost, forwards through authenticated upstream."""
import socket
import struct
import asyncio

UPSTREAM_HOST = "200.229.27.28"
UPSTREAM_PORT = 59101
USERNAME = "paidpostingcards"
PASSWORD = "myLr3d5kIZ"
LOCAL_PORT = 9055


def upstream_connect(dest_addr: bytes, dest_port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect((UPSTREAM_HOST, UPSTREAM_PORT))

    # SOCKS5 greeting: offer username/password auth
    sock.sendall(b"\x05\x01\x02")
    resp = sock.recv(2)
    if resp[1] != 0x02:
        sock.close()
        raise RuntimeError("Upstream rejected auth method")

    # Authenticate
    auth = (b"\x01"
            + bytes([len(USERNAME)]) + USERNAME.encode()
            + bytes([len(PASSWORD)]) + PASSWORD.encode())
    sock.sendall(auth)
    if sock.recv(2)[1] != 0x00:
        sock.close()
        raise RuntimeError("Upstream auth failed")

    # CONNECT to destination
    req = (b"\x05\x01\x00\x03"
           + bytes([len(dest_addr)]) + dest_addr
           + struct.pack(">H", dest_port))
    sock.sendall(req)
    r = sock.recv(10)
    if r[1] != 0x00:
        sock.close()
        raise RuntimeError(f"Upstream connect failed: code {r[1]}")

    sock.setblocking(False)
    return sock


async def relay(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle_client(client_reader, client_writer):
    upstream_writer = None
    try:
        # Read SOCKS5 greeting from Chrome
        await asyncio.wait_for(client_reader.read(256), timeout=10)
        # Reply: no auth required
        client_writer.write(b"\x05\x00")
        await client_writer.drain()

        # Read CONNECT request
        req = await asyncio.wait_for(client_reader.read(256), timeout=10)
        if len(req) < 4:
            client_writer.close()
            return

        atyp = req[3]
        if atyp == 0x01:  # IPv4
            dest_addr = socket.inet_ntoa(req[4:8]).encode()
            dest_port = struct.unpack(">H", req[8:10])[0]
        elif atyp == 0x03:  # Domain
            alen = req[4]
            dest_addr = req[5:5 + alen]
            dest_port = struct.unpack(">H", req[5 + alen:7 + alen])[0]
        elif atyp == 0x04:  # IPv6
            dest_addr = socket.inet_ntop(socket.AF_INET6, req[4:20]).encode()
            dest_port = struct.unpack(">H", req[20:22])[0]
        else:
            client_writer.close()
            return

        # Connect through upstream SOCKS5 proxy (blocking, run in thread)
        loop = asyncio.get_event_loop()
        upstream_sock = await loop.run_in_executor(
            None, upstream_connect, dest_addr, dest_port
        )

        # Tell Chrome: connection succeeded
        client_writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
        await client_writer.drain()

        # Bridge data both ways
        upstream_reader, upstream_writer = await asyncio.open_connection(
            sock=upstream_sock
        )
        await asyncio.gather(
            relay(client_reader, upstream_writer),
            relay(upstream_reader, client_writer),
        )

    except Exception:
        pass
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


async def main():
    server = await asyncio.start_server(handle_client, "127.0.0.1", LOCAL_PORT)
    print(f"SOCKS5 bridge running on 127.0.0.1:{LOCAL_PORT}")
    print(f"Forwarding to {UPSTREAM_HOST}:{UPSTREAM_PORT}")
    print()
    print("Open Chrome with:")
    print(f'  & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
          f'--proxy-server="socks5://127.0.0.1:{LOCAL_PORT}" '
          f'--user-data-dir="C:\\temp\\chrome-proxy"')
    print()
    print("Press Ctrl+C to stop")
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
