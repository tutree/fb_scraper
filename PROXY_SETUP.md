# Proxy Setup Guide

## Current Configuration

**Proxy Type:** SOCKS5  
**Proxy Host:** 127.0.0.1 (localhost)  
**Proxy Port:** 1080  
**US PC Tailscale IP:** 100.85.92.28  
**US PC Username:** shakil

## Setup Instructions

### 1. Start SSH Tunnel (On Your Local PC)

Open a terminal and run:

```bash
ssh -D 1080 shakil@100.85.92.28
```

**What this does:**
- Creates a SOCKS5 proxy on your local machine at `127.0.0.1:1080`
- All traffic through this proxy will route through the US PC
- Your scraper will appear to be accessing Facebook from the US

### 2. Keep the SSH Tunnel Running

The SSH tunnel must stay active while scraping. Options:

**Option A: Run in background**
```bash
ssh -D 1080 -N -f shakil@100.85.92.28
```
- `-N` = Don't execute remote commands
- `-f` = Run in background

**Option B: Run in a separate terminal**
Just keep the terminal window open with the SSH connection active.

### 3. Verify Proxy is Working

Test the proxy connection:

```bash
# From your local PC (outside Docker)
curl -x socks5://127.0.0.1:1080 https://api.ipify.org?format=json
```

Should return the US PC's public IP address.

### 4. Docker Configuration

The `.env` file is already configured:

```env
PROXY_LIST=socks5://host.docker.internal:1080
```

**Note:** Docker containers use `host.docker.internal:1080` to access `127.0.0.1:1080` on your host machine.

## Optimized SSH Tunnel (Faster Connection)

For better performance, use these optimized settings:

```bash
ssh -D 1080 -C -N -f \
  -o Compression=yes \
  -o CompressionLevel=6 \
  -o TCPKeepAlive=yes \
  -o ServerAliveInterval=60 \
  -c aes128-gcm@openssh.com \
  shakil@100.85.92.28
```

**Optimizations:**
- `-C` = Enable compression
- `CompressionLevel=6` = Balance speed/compression
- `TCPKeepAlive` = Keep connection alive
- `ServerAliveInterval=60` = Send keepalive every 60s
- `aes128-gcm` = Faster encryption cipher

## SSH Config File (Recommended)

Create/edit `~/.ssh/config`:

```
Host us-proxy
    HostName 100.85.92.28
    User shakil
    DynamicForward 1080
    Compression yes
    CompressionLevel 6
    TCPKeepAlive yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
    Cipher aes128-gcm@openssh.com
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m
```

Then connect with just:
```bash
ssh -N -f us-proxy
```

## Troubleshooting

### Proxy Connection Failed

**Check if SSH tunnel is running:**
```bash
# Windows
netstat -an | findstr 1080

# Should show: TCP 127.0.0.1:1080 ... LISTENING
```

**Restart the tunnel:**
```bash
# Kill existing
taskkill /F /IM ssh.exe

# Start new
ssh -D 1080 -N -f shakil@100.85.92.28
```

### Slow Connection

**Test latency:**
```bash
# Ping the US server
ping 100.85.92.28

# Tailscale-specific ping
tailscale ping 100.85.92.28
```

**Check Tailscale status:**
```bash
tailscale status
```

Look for "direct" connection. If it says "relay", your connection is slower.

### Timeout Errors in Scraper

If pages are timing out:

1. **Check connection speed** (see above)
2. **Increase timeouts** in the scraper code
3. **Use optimized SSH tunnel** (see above)

## Traffic Flow

```
Your PC → SSH Tunnel (127.0.0.1:1080) → Tailscale → US PC (100.85.92.28) → Internet → Facebook
```

Docker containers see it as:
```
Docker Container → host.docker.internal:1080 → Your PC → US PC → Facebook
```

## Security Notes

- The SSH tunnel encrypts all traffic between your PC and the US server
- Facebook sees requests coming from the US PC's IP address
- Keep your SSH credentials secure
- Use SSH keys instead of passwords for better security

## Testing the Setup

Run the connection diagnostic:

```bash
docker-compose run --rm api python test_connection.py
```

This will test:
- Proxy connectivity
- Connection speed
- Facebook accessibility
- Profile page load times

All tests should pass with reasonable load times (<10 seconds per page).
