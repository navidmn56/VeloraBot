"""
services/server_guard.py
------------------------
Lightweight continuous server health, panel reachability, and IP spam/flood monitor.
Sends telemetry logs to Log Bot and mentions Admin's Telegram @username ONLY when
real problems or security anomalies occur.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import logging
import os
import re
import shutil
import socket
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from core.task_manager import (
    consume_force_run,
    get_task_interval,
    is_task_enabled,
    record_task_finish,
    record_task_start,
    sleep_interruptible,
    wait_until_task_enabled,
)

logger = logging.getLogger(__name__)

# Optional psutil support (degrades gracefully if unavailable)
try:
    import psutil
    try:
        # Initial non-blocking baseline call so later cpu_percent(interval=None) is accurate
        psutil.cpu_percent(interval=None)
    except Exception:
        pass
except ImportError:
    psutil = None

# ═══════════════════════════════════════════════════════════
# Tunable Alert Thresholds & Cooldowns
# ═══════════════════════════════════════════════════════════

CPU_ALERT_PERCENT = 85.0
CPU_CRITICAL_PERCENT = 94.0
RAM_ALERT_PERCENT = 88.0
RAM_CRITICAL_PERCENT = 95.0
SWAP_ALERT_PERCENT = 85.0
BOT_RSS_ALERT_MB = 700.0
DISK_FREE_MIN_GB = 1.0
DISK_ALERT_PERCENT = 92.0

TCP_CONNS_PER_IP_THRESHOLD = 120
SYN_RECV_PER_IP_THRESHOLD = 25
SYN_RECV_TOTAL_THRESHOLD = 60

WEBHOOK_REQ_PER_MIN_ALERT = 40
WEBHOOK_AUTH_FAIL_ALERT = 10
NGINX_REQ_90S_THRESHOLD = 150
BOT_SPAM_BLOCK_ALERT = 15

ALERT_COOLDOWN_SECONDS = 900.0   # 15 minutes per alert key
HEALTHY_LOG_INTERVAL = 1800.0    # 30 minutes periodic check-in to Log Bot (no tag)

# Sliding windows for application-level flood detection (bounded)
_HTTP_IP_HITS: Dict[str, List[float]] = defaultdict(list)
_HTTP_AUTH_FAILS: Dict[str, List[float]] = defaultdict(list)
_BOT_USER_BLOCKS: Dict[int, List[float]] = defaultdict(list)

# Runtime state & cooldown caches
_ALERT_COOLDOWNS: Dict[str, float] = {}
_ACTIVE_ISSUES: set[str] = set()
_CPU_HIGH_STREAK = 0
_PANEL_FAIL_STREAK = 0
_LAST_HEALTHY_LOG_AT = 0.0
_ADMIN_MENTION_CACHE: Tuple[int, str, float] = (0, "", 0.0)
_NGINX_LOG_CANDIDATES = ("/var/log/nginx/access.log", "/var/log/caddy/access.log")
_NGINX_LINE_RE = re.compile(
    r'^(\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"[A-Z]+\s+([^"\s]+)'
)


def _prune_dict_window(store: dict, max_keys: int = 500, cutoff: float = 0.0) -> None:
    if len(store) <= max_keys:
        return
    if cutoff > 0:
        stale = [k for k, vals in store.items() if not vals or vals[-1] < cutoff]
        for k in stale:
            store.pop(k, None)
    if len(store) > max_keys:
        for k in list(store.keys())[:len(store) - (max_keys // 2)]:
            store.pop(k, None)


def record_http_request(source: str, client_ip: str, path: str = "", status_code: int = 200) -> Tuple[int, int]:
    """
    Record an HTTP request (e.g. from SMS webhook) into sliding windows.
    Returns (requests_last_60s, auth_failures_last_300s).
    """
    now = time.monotonic()
    ip_str = (client_ip or "unknown").strip()[:64]
    key = f"{source}:{ip_str}"

    hits = _HTTP_IP_HITS[key]
    hits.append(now)
    cutoff_60 = now - 60.0
    if len(hits) > 10 and hits[0] < cutoff_60:
        hits[:] = [t for t in hits if t >= cutoff_60]
    req_count = len(hits)

    fail_count = 0
    if status_code in (401, 403, 429):
        fails = _HTTP_AUTH_FAILS[key]
        fails.append(now)
        cutoff_300 = now - 300.0
        if len(fails) > 5 and fails[0] < cutoff_300:
            fails[:] = [t for t in fails if t >= cutoff_300]
        fail_count = len(fails)

    _prune_dict_window(_HTTP_IP_HITS, max_keys=500, cutoff=now - 120.0)
    _prune_dict_window(_HTTP_AUTH_FAILS, max_keys=500, cutoff=now - 360.0)
    return req_count, fail_count


def record_bot_user_block(user_id: int, action: str = "default") -> int:
    """Record a rate-limit block for a Telegram user; returns blocks in last 60s."""
    now = time.monotonic()
    uid = int(user_id)
    blocks = _BOT_USER_BLOCKS[uid]
    blocks.append(now)
    cutoff = now - 60.0
    if len(blocks) > 5 and blocks[0] < cutoff:
        blocks[:] = [t for t in blocks if t >= cutoff]
    _prune_dict_window(_BOT_USER_BLOCKS, max_keys=500, cutoff=cutoff)
    return len(blocks)


def _is_external_ip(ip_str: str) -> bool:
    if not ip_str:
        return False
    clean = ip_str.strip()
    if clean.startswith("::ffff:"):
        clean = clean[7:]
    try:
        addr = ipaddress.ip_address(clean)
        return not (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_unspecified
        )
    except ValueError:
        return False


def _resolve_panel_host_ips() -> set[str]:
    ips: set[str] = set()
    try:
        from config import SENAI_PANEL_URL
        host = urlparse(SENAI_PANEL_URL).hostname
        if host:
            for info in socket.getaddrinfo(host, None):
                if info and info[4]:
                    ips.add(info[4][0])
    except Exception:
        pass
    return ips


def _inspect_tcp_connections_sync(ignored_ips: set[str]) -> Dict[str, Any]:
    """Inspect active TCP sockets per remote external IP (blocking I/O run off-thread)."""
    ip_total: Counter[str] = Counter()
    ip_syn: Counter[str] = Counter()
    ip_ports: Dict[str, Counter[int]] = defaultdict(Counter)
    total_conns = 0
    total_syn = 0

    if psutil is not None:
        try:
            conns = psutil.net_connections(kind="inet")
            for c in conns:
                status = getattr(c, "status", "")
                if status == "LISTEN":
                    continue
                total_conns += 1
                if status == "SYN_RECV":
                    total_syn += 1
                raddr = getattr(c, "raddr", None)
                laddr = getattr(c, "laddr", None)
                rip = getattr(raddr, "ip", None) if raddr else None
                if not rip or rip in ignored_ips or not _is_external_ip(rip):
                    continue
                if rip.startswith("::ffff:"):
                    rip = rip[7:]
                ip_total[rip] += 1
                if status == "SYN_RECV":
                    ip_syn[rip] += 1
                lport = getattr(laddr, "port", None) if laddr else None
                if lport:
                    ip_ports[rip][lport] += 1
        except Exception as e:
            logger.debug(f"psutil.net_connections unavailable: {e}")

    top_ips = [
        {
            "ip": ip,
            "count": cnt,
            "syn": ip_syn.get(ip, 0),
            "ports": [p for p, _ in ip_ports[ip].most_common(3)],
        }
        for ip, cnt in ip_total.most_common(5)
    ]
    return {
        "total_conns": total_conns,
        "total_syn": total_syn,
        "top_ips": top_ips,
        "ip_total": dict(ip_total),
        "ip_syn": dict(ip_syn),
    }


def _scan_nginx_tail_sync(ignored_ips: set[str]) -> Optional[Dict[str, Any]]:
    """Inspect last <=256KB of Nginx access log on Linux for high request bursts per IP."""
    log_path = next((p for p in _NGINX_LOG_CANDIDATES if os.path.isfile(p)), None)
    if not log_path:
        return None
    try:
        size = os.path.getsize(log_path)
        if size <= 0:
            return None
        read_bytes = min(size, 262144)
        with open(log_path, "rb") as f:
            f.seek(size - read_bytes)
            chunk = f.read().decode("utf-8", errors="ignore")
        lines = chunk.splitlines()
        if size > read_bytes and lines:
            lines = lines[1:]  # Drop partial leading line

        now_utc = datetime.now(timezone.utc)
        ip_counts: Counter[str] = Counter()
        ip_paths: Dict[str, Counter[str]] = defaultdict(Counter)

        for line in lines[-2500:]:
            m = _NGINX_LINE_RE.match(line)
            if not m:
                continue
            ip, ts_raw, path = m.group(1), m.group(2), m.group(3)
            if ip in ignored_ips or not _is_external_ip(ip):
                continue
            try:
                dt = datetime.strptime(ts_raw, "%d/%b/%Y:%H:%M:%S %z")
                if (now_utc - dt.astimezone(timezone.utc)).total_seconds() > 90.0:
                    continue
            except Exception:
                continue
            ip_counts[ip] += 1
            ip_paths[ip][path[:40]] += 1

        hot = [
            {
                "ip": ip,
                "count": cnt,
                "top_path": ip_paths[ip].most_common(1)[0][0] if ip_paths[ip] else "/",
            }
            for ip, cnt in ip_counts.most_common(3)
            if cnt >= NGINX_REQ_90S_THRESHOLD
        ]
        return {"log_path": log_path, "hot_ips": hot}
    except Exception as e:
        logger.debug(f"Nginx log inspection skipped: {e}")
        return None


def collect_server_metrics_sync() -> Dict[str, Any]:
    """Collect CPU, RAM, swap, disk, TCP connections, and proxy logs synchronously off-thread."""
    metrics: Dict[str, Any] = {
        "cpu_percent": 0.0,
        "cpu_count": os.cpu_count() or 1,
        "load1": None,
        "load_ratio": 0.0,
        "ram_percent": 0.0,
        "ram_used_gb": 0.0,
        "ram_total_gb": 0.0,
        "ram_avail_mb": 0.0,
        "swap_percent": 0.0,
        "swap_total_mb": 0.0,
        "bot_rss_mb": 0.0,
        "disk_free_gb": 0.0,
        "disk_total_gb": 0.0,
        "disk_percent": 0.0,
        "network": {"total_conns": 0, "total_syn": 0, "top_ips": []},
        "nginx": None,
    }

    if psutil is not None:
        try:
            metrics["cpu_percent"] = float(psutil.cpu_percent(interval=None))
            metrics["cpu_count"] = int(psutil.cpu_count(logical=True) or os.cpu_count() or 1)
            vm = psutil.virtual_memory()
            metrics["ram_percent"] = float(vm.percent)
            metrics["ram_used_gb"] = vm.used / (1024 ** 3)
            metrics["ram_total_gb"] = vm.total / (1024 ** 3)
            metrics["ram_avail_mb"] = vm.available / (1024 ** 2)
            sw = psutil.swap_memory()
            metrics["swap_percent"] = float(sw.percent)
            metrics["swap_total_mb"] = sw.total / (1024 ** 2)
            rss = psutil.Process().memory_info().rss
            metrics["bot_rss_mb"] = rss / (1024 ** 2)
        except Exception as e:
            logger.debug(f"Error collecting psutil metrics: {e}")

    try:
        if hasattr(os, "getloadavg"):
            l1, _, _ = os.getloadavg()
            metrics["load1"] = round(l1, 2)
            metrics["load_ratio"] = l1 / max(1, metrics["cpu_count"])
    except Exception:
        pass

    try:
        total, used, free = shutil.disk_usage(".")
        metrics["disk_free_gb"] = free / (1024 ** 3)
        metrics["disk_total_gb"] = total / (1024 ** 3)
        metrics["disk_percent"] = (used / total) * 100.0 if total > 0 else 0.0
    except Exception as e:
        logger.debug(f"Error reading disk usage: {e}")

    ignored = _resolve_panel_host_ips()
    metrics["network"] = _inspect_tcp_connections_sync(ignored)
    metrics["nginx"] = _scan_nginx_tail_sync(ignored)
    return metrics


async def _check_panel_health() -> Dict[str, Any]:
    """Probe panel HTTP endpoint & session using shared HTTP_SESSION."""
    from config import SENAI_PANEL_URL, is_senai_panel_enabled

    if not is_senai_panel_enabled():
        return {"enabled": False, "ok": True, "latency_ms": None, "error": None}

    start = time.monotonic()
    try:
        import aiohttp
        from services.panel_api import _ensure_session
        session = await _ensure_session()
        async with session.get(
            SENAI_PANEL_URL,
            timeout=aiohttp.ClientTimeout(total=6),
        ) as resp:
            latency_ms = int((time.monotonic() - start) * 1000)
            if resp.status >= 500:
                return {
                    "enabled": True,
                    "ok": False,
                    "latency_ms": latency_ms,
                    "error": f"HTTP {resp.status}",
                }
            return {
                "enabled": True,
                "ok": True,
                "latency_ms": latency_ms,
                "error": None,
            }
    except asyncio.TimeoutError:
        return {"enabled": True, "ok": False, "latency_ms": None, "error": "Timeout (>6s)"}
    except Exception as e:
        return {"enabled": True, "ok": False, "latency_ms": None, "error": str(e)[:120]}


async def resolve_admin_mention(bot: Any, admin_id: int) -> str:
    """Resolve and cache the bot admin's Telegram @username for tagging urgent alerts."""
    global _ADMIN_MENTION_CACHE
    now = time.monotonic()
    cached_id, cached_mention, cached_at = _ADMIN_MENTION_CACHE
    if cached_id == admin_id and cached_mention and (now - cached_at) < 21600:
        return cached_mention

    username = None
    if bot is not None and admin_id:
        try:
            chat = await bot.get_chat(admin_id)
            raw_u = getattr(chat, "username", None)
            if isinstance(raw_u, str) and raw_u.strip():
                username = raw_u.strip().lstrip("@")
        except Exception:
            pass

    if not username and admin_id:
        try:
            from database import users
            u = users.get(str(admin_id), {})
            for field in ("telegram_username", "username"):
                cand = str(u.get(field) or "").strip().lstrip("@")
                if cand and re.fullmatch(r"[A-Za-z0-9_]{3,32}", cand):
                    username = cand
                    break
        except Exception:
            pass

    mention = (
        f"@{html.escape(username)}"
        if username
        else f'<a href="tg://user?id={admin_id}">Admin ({admin_id})</a>'
    )
    _ADMIN_MENTION_CACHE = (admin_id, mention, now)
    return mention


def _can_emit_alert(alert_key: str, cooldown: float = ALERT_COOLDOWN_SECONDS) -> bool:
    now = time.monotonic()
    last = _ALERT_COOLDOWNS.get(alert_key, 0.0)
    if (now - last) < cooldown:
        return False
    _ALERT_COOLDOWNS[alert_key] = now
    if len(_ALERT_COOLDOWNS) > 500:
        cutoff = now - cooldown
        stale = [k for k, t in _ALERT_COOLDOWNS.items() if t < cutoff]
        for k in stale:
            _ALERT_COOLDOWNS.pop(k, None)
    return True


async def _send_server_log(
    title: str,
    body_html: str,
    is_important: bool = False,
    bot: Any = None,
) -> None:
    """Send server/security monitor log to Log Bot, tagging admin @username ONLY if important."""
    from config import ADMIN_ID_INT
    from services.background_tasks import get_bot, get_log_system

    active_bot = bot or get_bot()
    log_sys = get_log_system()
    mention = await resolve_admin_mention(active_bot, ADMIN_ID_INT) if is_important else ""

    if log_sys is not None:
        if hasattr(log_sys, "log_server_event"):
            await log_sys.log_server_event(
                title=title,
                body_html=body_html,
                is_important=is_important,
                admin_mention=mention,
            )
        else:
            footer = f"\n\n🔔 {mention}" if (is_important and mention) else ""
            await log_sys.send_log(f"<b>{html.escape(title)}</b>\n{body_html}{footer}")
        return

    # If Log Bot is not configured and issue is critical, notify admin DM so outage isn't missed
    if is_important and active_bot is not None and ADMIN_ID_INT:
        try:
            await active_bot.send_message(
                ADMIN_ID_INT,
                f"🚨 <b>{html.escape(title)}</b>\n{body_html}",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"Failed to send fallback critical server alert to admin: {e}")


def _collect_app_floods() -> List[Dict[str, Any]]:
    now = time.monotonic()
    findings: List[Dict[str, Any]] = []

    cutoff_60 = now - 60.0
    cutoff_300 = now - 300.0
    for key, hits in list(_HTTP_IP_HITS.items()):
        recent = [t for t in hits if t >= cutoff_60]
        if recent:
            hits[:] = recent
        else:
            _HTTP_IP_HITS.pop(key, None)
            continue
        if len(recent) >= WEBHOOK_REQ_PER_MIN_ALERT:
            src, ip = key.split(":", 1) if ":" in key else ("http", key)
            findings.append({
                "kind": "webhook_flood",
                "key": f"webhook_flood:{ip}",
                "ip": ip,
                "source": src,
                "count": len(recent),
            })

    for key, fails in list(_HTTP_AUTH_FAILS.items()):
        recent_f = [t for t in fails if t >= cutoff_300]
        if recent_f:
            fails[:] = recent_f
        else:
            _HTTP_AUTH_FAILS.pop(key, None)
            continue
        if len(recent_f) >= WEBHOOK_AUTH_FAIL_ALERT:
            src, ip = key.split(":", 1) if ":" in key else ("http", key)
            findings.append({
                "kind": "webhook_auth",
                "key": f"webhook_auth:{ip}",
                "ip": ip,
                "source": src,
                "count": len(recent_f),
            })

    for uid, blocks in list(_BOT_USER_BLOCKS.items()):
        recent_b = [t for t in blocks if t >= cutoff_60]
        if recent_b:
            blocks[:] = recent_b
        else:
            _BOT_USER_BLOCKS.pop(uid, None)
            continue
        if len(recent_b) >= BOT_SPAM_BLOCK_ALERT:
            findings.append({
                "kind": "bot_spam",
                "key": f"bot_spam:{uid}",
                "user_id": uid,
                "count": len(recent_b),
            })

    return findings


async def run_server_guard_check(bot: Any = None, force_summary: bool = False) -> Dict[str, Any]:
    """Run one complete server + panel + IP flood inspection cycle."""
    global _CPU_HIGH_STREAK, _PANEL_FAIL_STREAK, _LAST_HEALTHY_LOG_AT

    metrics, panel_res = await asyncio.gather(
        asyncio.to_thread(collect_server_metrics_sync),
        _check_panel_health(),
    )

    issues: List[Tuple[str, str, str]] = []  # (issue_key, title, body_html)
    current_issue_keys: set[str] = set()

    # 1. CPU & Load
    cpu = metrics["cpu_percent"]
    load_ratio = metrics["load_ratio"]
    if cpu >= CPU_ALERT_PERCENT or load_ratio >= 1.8:
        _CPU_HIGH_STREAK += 1
    else:
        _CPU_HIGH_STREAK = 0

    if cpu >= CPU_CRITICAL_PERCENT or ((cpu >= CPU_ALERT_PERCENT or load_ratio >= 1.8) and _CPU_HIGH_STREAK >= 2):
        current_issue_keys.add("cpu")
        load_txt = f"{metrics['load1']} (ratio {load_ratio:.2f})" if metrics["load1"] is not None else "N/A"
        issues.append((
            "cpu",
            "🚨 هشدار مصرف بالای CPU سرور",
            f"• <b>مصرف CPU:</b> <code>{cpu:.1f}%</code>\n"
            f"• <b>Load Average (1m):</b> <code>{load_txt}</code>\n"
            f"• <b>تعداد هسته:</b> {metrics['cpu_count']}",
        ))

    # 2. RAM / Swap / Bot RSS
    ram_pct = metrics["ram_percent"]
    swap_pct = metrics["swap_percent"]
    bot_rss = metrics["bot_rss_mb"]
    ram_low_mb = metrics["ram_total_gb"] >= 0.5 and metrics["ram_avail_mb"] > 0 and metrics["ram_avail_mb"] < 150.0
    if (
        ram_pct >= RAM_ALERT_PERCENT
        or ram_low_mb
        or (metrics["swap_total_mb"] > 10 and swap_pct >= SWAP_ALERT_PERCENT)
        or bot_rss >= BOT_RSS_ALERT_MB
    ):
        current_issue_keys.add("ram")
        issues.append((
            "ram",
            "🚨 هشدار مصرف بالای حافظه (RAM)",
            f"• <b>RAM سرور:</b> <code>{metrics['ram_used_gb']:.2f}/{metrics['ram_total_gb']:.2f} GB ({ram_pct:.1f}%)</code>\n"
            f"• <b>حافظه آزاد:</b> <code>{metrics['ram_avail_mb']:.0f} MB</code>\n"
            f"• <b>رم پروسه ربات:</b> <code>{bot_rss:.1f} MB</code> | Swap: <code>{swap_pct:.1f}%</code>",
        ))
        # Defensive cleanup if bot RSS itself is elevated
        if bot_rss >= 500.0:
            try:
                import gc
                from db_storage import _db_cache, _storage_lock
                from services.background_tasks import cleanup_expired_states
                with _storage_lock:
                    _db_cache.clear()
                cleanup_expired_states()
                gc.collect()
            except Exception:
                pass

    # 3. Disk Space
    if metrics["disk_total_gb"] > 0 and (
        metrics["disk_free_gb"] < DISK_FREE_MIN_GB or metrics["disk_percent"] >= DISK_ALERT_PERCENT
    ):
        current_issue_keys.add("disk")
        issues.append((
            "disk",
            "🚨 هشدار کمبود فضای دیسک سرور",
            f"• <b>فضای خالی:</b> <code>{metrics['disk_free_gb']:.2f} GB</code> از <code>{metrics['disk_total_gb']:.1f} GB</code>\n"
            f"• <b>درصد اشغال:</b> <code>{metrics['disk_percent']:.1f}%</code>",
        ))

    # 4. Panel Connectivity
    if panel_res.get("enabled"):
        if not panel_res.get("ok"):
            _PANEL_FAIL_STREAK += 1
            current_issue_keys.add("panel")
            issues.append((
                "panel",
                "🔴 خطای اتصال یا عدم پاسخگویی پنل 3X-UI",
                f"• <b>خطا:</b> <code>{html.escape(str(panel_res.get('error') or 'Unknown'))}</code>\n"
                f"• <b>تعداد خطای متوالی:</b> {_PANEL_FAIL_STREAK}",
            ))
        else:
            _PANEL_FAIL_STREAK = 0

    # 5. TCP Connections / IP Flood on Server
    net = metrics["network"]
    if net.get("total_syn", 0) >= SYN_RECV_TOTAL_THRESHOLD:
        current_issue_keys.add("syn_flood")
        issues.append((
            "syn_flood",
            "🛡️ هشدار احتمال SYN Flood روی سرور",
            f"• <b>تعداد اتصالات SYN_RECV:</b> <code>{net['total_syn']}</code>\n"
            f"• <b>کل اتصالات باز:</b> <code>{net['total_conns']}</code>",
        ))

    for entry in net.get("top_ips", []):
        ip = entry["ip"]
        cnt = entry["count"]
        syn = entry["syn"]
        if cnt >= TCP_CONNS_PER_IP_THRESHOLD or syn >= SYN_RECV_PER_IP_THRESHOLD:
            ikey = f"ip_conn:{ip}"
            current_issue_keys.add(ikey)
            ports_str = ", ".join(str(p) for p in entry.get("ports") or []) or "-"
            issues.append((
                ikey,
                "🛡️ هشدار اتصال/اسپم زیاد از یک IP روی سرور",
                f"• <b>IP مهاجم/پرمصرف:</b> <code>{html.escape(ip)}</code>\n"
                f"• <b>تعداد کانکشن هم‌زمان:</b> <code>{cnt}</code> (SYN_RECV: <code>{syn}</code>)\n"
                f"• <b>پورت‌های هدف:</b> <code>{ports_str}</code>",
            ))

    # 6. Nginx high request rate per IP
    nginx = metrics.get("nginx")
    if nginx and nginx.get("hot_ips"):
        for h in nginx["hot_ips"]:
            ikey = f"nginx:{h['ip']}"
            current_issue_keys.add(ikey)
            issues.append((
                ikey,
                "🛡️ هشدار ریکوعست زیاد HTTP از یک IP (Nginx)",
                f"• <b>IP:</b> <code>{html.escape(h['ip'])}</code>\n"
                f"• <b>تعداد درخواست در ۹۰ ثانیه اخیر:</b> <code>{h['count']}</code>\n"
                f"• <b>مسیر پرتکرار:</b> <code>{html.escape(h['top_path'])}</code>",
            ))

    # 7. Application-level Webhook & Telegram Spam Floods
    for f in _collect_app_floods():
        ikey = f["key"]
        current_issue_keys.add(ikey)
        if f["kind"] == "webhook_flood":
            issues.append((
                ikey,
                "🛡️ هشدار اسپم/ریکوعست زیاد به وب‌هوک سرور",
                f"• <b>IP:</b> <code>{html.escape(f['ip'])}</code>\n"
                f"• <b>منبع:</b> <code>{html.escape(f['source'])}</code>\n"
                f"• <b>تعداد درخواست در ۱ دقیقه:</b> <code>{f['count']}</code>",
            ))
        elif f["kind"] == "webhook_auth":
            issues.append((
                ikey,
                "🚨 هشدار تلاش مشکوک/احراز هویت نامعتبر روی وب‌هوک",
                f"• <b>IP:</b> <code>{html.escape(f['ip'])}</code>\n"
                f"• <b>خطاهای 401/429 در ۵ دقیقه:</b> <code>{f['count']}</code>",
            ))
        elif f["kind"] == "bot_spam":
            issues.append((
                ikey,
                "⚠️ هشدار اسپم مکرر کاربر در ربات تلگرام",
                f"• <b>آیدی کاربر:</b> <code>{f['user_id']}</code>\n"
                f"• <b>درخواست‌های مسدودشده در ۱ دقیقه:</b> <code>{f['count']}</code>",
            ))

    # Emit important alerts WITH admin @username mention (cooldown-protected)
    for ikey, title, body in issues:
        _ACTIVE_ISSUES.add(ikey)
        if _can_emit_alert(ikey):
            await _send_server_log(title=title, body_html=body, is_important=True, bot=bot)

    # Emit recovery notifications WITHOUT admin @username mention
    resolved = [k for k in list(_ACTIVE_ISSUES) if k not in current_issue_keys]
    for rkey in resolved:
        _ACTIVE_ISSUES.discard(rkey)
        _ALERT_COOLDOWNS.pop(rkey, None)
        await _send_server_log(
            title="✅ رفع مشکل سرور / سرویس",
            body_html=f"• مورد <code>{html.escape(rkey)}</code> به وضعیت عادی بازگشت.",
            is_important=False,
            bot=bot,
        )

    # Periodic healthy heartbeat to Log Bot WITHOUT @username mention
    now = time.monotonic()
    if not issues and (force_summary or _LAST_HEALTHY_LOG_AT == 0.0 or (now - _LAST_HEALTHY_LOG_AT) >= HEALTHY_LOG_INTERVAL):
        _LAST_HEALTHY_LOG_AT = now
        panel_str = (
            f"🟢 OK ({panel_res['latency_ms']}ms)"
            if panel_res.get("enabled") and panel_res.get("ok")
            else ("🔴 OFF" if not panel_res.get("enabled") else f"🔴 {panel_res.get('error')}")
        )
        top_ip_txt = ""
        if net.get("top_ips"):
            t0 = net["top_ips"][0]
            top_ip_txt = f"\n• <b>پرمصرف‌ترین IP خارجی:</b> <code>{html.escape(t0['ip'])}</code> ({t0['count']} اتصال)"
        await _send_server_log(
            title="🖥️ گزارش دوره‌ای وضعیت سرور",
            body_html=(
                f"• <b>CPU:</b> <code>{cpu:.1f}%</code> | <b>RAM:</b> <code>{ram_pct:.1f}%</code> (ربات: <code>{bot_rss:.1f} MB</code>)\n"
                f"• <b>دیسک آزاد:</b> <code>{metrics['disk_free_gb']:.1f}/{metrics['disk_total_gb']:.1f} GB</code>\n"
                f"• <b>اتصالات TCP:</b> <code>{net.get('total_conns', 0)}</code> | <b>پنل:</b> {html.escape(str(panel_str))}"
                f"{top_ip_txt}"
            ),
            is_important=False,
            bot=bot,
        )

    return {"metrics": metrics, "panel": panel_res, "issues_count": len(issues)}


async def report_immediate_security_event(alert_key: str, title: str, body_html: str) -> None:
    """Immediately emit an important security alert (e.g., webhook attack) to Log Bot with cooldown."""
    if _can_emit_alert(alert_key):
        _ACTIVE_ISSUES.add(alert_key)
        await _send_server_log(title=title, body_html=body_html, is_important=True)


async def server_guard_worker(bot: Any = None) -> None:
    """Essential continuous background worker monitoring server resources, panel, and IP floods."""
    logger.info("🛡️ Server & security guard worker started")
    await sleep_interruptible("server_guard", 25.0)

    while True:
        try:
            await wait_until_task_enabled("server_guard")
            force = consume_force_run("server_guard")
            started = record_task_start("server_guard")
            try:
                await run_server_guard_check(bot=bot, force_summary=force)
                record_task_finish("server_guard", started)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                record_task_finish("server_guard", started, str(e))
                logger.error(f"Error in server_guard check: {e}", exc_info=True)
                await _send_server_log(
                    title="⚠️ خطا در اجرای پایشگر سرور",
                    body_html=f"<code>{html.escape(str(e)[:200])}</code>",
                    is_important=False,
                    bot=bot,
                )

            interval = get_task_interval("server_guard")
            await sleep_interruptible("server_guard", interval)
        except asyncio.CancelledError:
            logger.info("Server guard worker canceled")
            break
        except Exception as e:
            logger.error(f"Unexpected error in server_guard_worker: {e}", exc_info=True)
            await sleep_interruptible("server_guard", 60.0)
