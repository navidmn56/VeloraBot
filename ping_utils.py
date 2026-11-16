import asyncio
import re
import time
from typing import Optional


async def real_ping_tcp(host: str, port: int = 443, timeout: int = 3) -> Optional[float]:
    try:
        import socket
        start = time.time()

        try:
            ip = socket.gethostbyname(host)
        except Exception:
            ip = host

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )

        elapsed = (time.time() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return elapsed

    except asyncio.TimeoutError:
        return None
    except Exception:
        return None


async def real_ping_icmp(host: str, timeout: int = 3) -> Optional[float]:
    try:
        import shutil
        if not shutil.which("ping"):
            return None

        process = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(timeout), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout + 1,
        )

        if process.returncode != 0:
            return None

        match = re.search(r"time[=<]([\d.]+)", stdout.decode())
        return float(match.group(1)) if match else None

    except Exception:
        return None


async def smart_ping(host: str, timeout: int = 3) -> Optional[float]:
    tcp_result = await real_ping_tcp(host, timeout=timeout)
    if tcp_result is not None:
        return tcp_result

    return await real_ping_icmp(host, timeout=timeout)
