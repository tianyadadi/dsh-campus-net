# -*- coding: utf-8 -*-
"""校园网（Srun 深澜）连接核心 —— 供 DSH 插件调用。

已验证的流程（2026-11-02）：
  1. GET http://2.2.2.2/            → 302 带 wlanuserip / wlanacname / vlan（已登录时）
                                      或 200 登录页（未登录时）
  2. GET http://<portal>/PortalJsonAction.do → portalForm + serverForm
  3. GET /quickauth.do?userid=&passwd=&...  → {"code":"0","message":"认证成功"}
  4. POST /quickauthdisconn.do               → 断开
  5. GET /portal/getOnlineUserName.do        → 查当前在线账号

🔴 安全设计（2026-11-02 事故后加）：
  * 未登录时门户可能返回 200 而不是 302 —— 这不算错误，用缓存的参数照样能登录
  * logout 默认带 30 秒自动重连保护，断开后没人管就自动连回来
  * 参数缓存到 state.json，断网时也有东西可用
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "campus-net.json")
STATE = os.path.join(BASE, "campus-net.state.json")

DEFAULT_CONFIG = {
    "portal": "2.2.2.2",
    "username": "",
    "password": "",
    "autoConnect": True,
    "autoReconnectSeconds": 30,
    "speedSampleMs": 1000,
    # 多账号：accounts 为空时沿用上面的 username/password（老配置零迁移）
    "accounts": [],
    "current": 0,
    # 挂件位置（像素，从视口左下角算）。别人的 DSH 侧边栏高度可能不一样，
    # 所以这个值可以在界面上拖动调整，拖完写回这里。
    "widgetLeft": 10,
    "widgetBottom": 96,
}


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, "r", encoding="utf-8-sig") as fh:
                cfg.update(json.load(fh) or {})
        except (OSError, ValueError):
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def load_state() -> dict:
    if os.path.exists(STATE):
        try:
            with open(STATE, "r", encoding="utf-8-sig") as fh:
                return json.load(fh) or {}
        except (OSError, ValueError):
            pass
    return {}


def save_state(**kw) -> None:
    st = load_state()
    st.update(kw)
    st["updated_at"] = now()
    try:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# --------------------------------------------------------------------------- 多账号
#
# 老配置只有 username/password 两个字段，不能逼用户去改文件。
# 规则：accounts 非空就用 accounts；为空就把 username/password 当成唯一账号。
# 切号时会把选中的账号镜像回 username/password，这样「救急重连.cmd」等老调用方不用改。

def _clean_accounts(raw) -> list[dict]:
    out = []
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        user = str(a.get("username") or "").strip()
        if not user:
            continue
        out.append({
            "name": str(a.get("name") or user).strip() or user,
            "username": user,
            "password": str(a.get("password") or ""),
        })
    return out


def accounts(cfg: dict | None = None) -> list[dict]:
    """所有可用账号。老配置会自动折成一条「默认」。"""
    cfg = cfg or load_config()
    acc = _clean_accounts(cfg.get("accounts"))
    if acc:
        return acc
    user = str(cfg.get("username") or "").strip()
    if user:
        return [{"name": "默认", "username": user, "password": str(cfg.get("password") or "")}]
    return []


def _current_index(cfg: dict, total: int) -> int:
    try:
        i = int(cfg.get("current") or 0)
    except (TypeError, ValueError):
        i = 0
    return i if 0 <= i < total else 0


def active_account(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    acc = accounts(cfg)
    if not acc:
        return {"name": "", "username": "", "password": ""}
    return acc[_current_index(cfg, len(acc))]


def switch_account(which) -> dict:
    """按序号（0 起）或名字/账号名切号。"""
    cfg = load_config()
    acc = accounts(cfg)
    if not acc:
        return {"ok": False, "error": "还没有账号，先在 campus-net.json 里填一个"}

    idx = None
    key = str(which).strip()
    if key.isdigit():
        i = int(key)
        if 0 <= i < len(acc):
            idx = i
    if idx is None:
        for i, a in enumerate(acc):
            if key and key in (a["name"], a["username"]):
                idx = i
                break
    if idx is None:
        return {"ok": False, "error": "没有这个账号：%s" % key,
                "accounts": [{"name": a["name"], "username": a["username"]} for a in acc]}

    cfg["accounts"] = acc
    cfg["current"] = idx
    # 镜像回老字段，保持兼容
    cfg["username"] = acc[idx]["username"]
    cfg["password"] = acc[idx]["password"]
    save_config(cfg)
    return {"ok": True, "current": idx, "name": acc[idx]["name"],
            "username": acc[idx]["username"]}


# --------------------------------------------------------------------------- HTTP

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _get(url: str, timeout: int = 15) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:
        return 0, str(e), {}


def _post(url: str, data: dict, timeout: int = 20) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


# --------------------------------------------------------------------------- 发现

def discover(cfg: dict | None = None) -> dict:
    """访问校园网入口。

    返回 {ok, online, host, params, online_user}
      * 302 + Location 带 username  → 已登录
      * 302 + Location 不带 username → 未登录，参数可用
      * 200 登录页                   → 未登录，参数用缓存
      * 连不上                       → ok=False（但缓存参数仍可用于 login）
    """
    cfg = cfg or load_config()
    portal_ip = str(cfg.get("portal") or "2.2.2.2").strip()
    state = load_state()
    cached_params = dict(state.get("last_params") or {})
    cached_host = state.get("last_host") or "172.16.253.121"

    url = "http://%s/" % portal_ip
    opener = urllib.request.build_opener(_NoRedirect)
    status, _, headers = 0, "", {}
    try:
        r = opener.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=12)
        status = r.status
        headers = dict(r.headers)
    except urllib.error.HTTPError as e:
        status = e.code
        headers = dict(e.headers)
    except Exception as e:
        # 连不上门户：网络可能真的断了，但缓存参数还能试着登录
        return {
            "ok": False, "online": False, "host": cached_host, "params": cached_params,
            "error": "连不上 %s：%s" % (portal_ip, str(e)[:70]),
            "used_cache": bool(cached_params),
        }

    loc = headers.get("Location", "") or headers.get("location", "")

    # 情况 A：302 跳转
    if status in (301, 302, 303, 307) and loc:
        parsed = urllib.parse.urlparse(loc)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        host = parsed.netloc or cached_host
        online_user = params.get("username", "")
        # 缓存好参数，下次断网也能用
        if params:
            save_state(last_params=params, last_host=host)
        return {
            "ok": True, "online": bool(online_user), "host": host,
            "params": params, "online_user": online_user,
        }

    # 情况 B：200 登录页（未登录，门户直接返回表单）
    if status == 200:
        return {
            "ok": True, "online": False, "host": cached_host,
            "params": cached_params, "online_user": "",
            "note": "未登录（门户直接返回登录页）",
            "used_cache": bool(cached_params),
        }

    # 情况 C：其它状态码
    return {
        "ok": bool(cached_params), "online": False, "host": cached_host,
        "params": cached_params,
        "error": "门户返回 HTTP %s" % status,
        "used_cache": bool(cached_params),
    }


def portal_info(host: str, params: dict) -> dict | None:
    q = urllib.parse.urlencode({
        "wlanuserip": params.get("wlanuserip", ""),
        "wlanacname": params.get("wlanacname", ""),
        "nasip": params.get("nasip", ""),
        "vlan": params.get("vlan", ""),
        "mac": params.get("mac", ""),
        "url": params.get("url", ""),
        "t": "wireless-v2",
        "viewStatus": "1",
    })
    status, body, _ = _get("http://%s/PortalJsonAction.do?%s" % (host, q))
    if status != 200:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


# --------------------------------------------------------------------------- 状态

def status(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()

    # ⭐ 先认网络：不在校园网就直接返回，别去碰门户（那要等 12 秒超时）
    net = network_info()
    if net.get("ok") and not net.get("is_campus"):
        out = {
            "online": False,
            "username": "",
            "ip": net.get("ip", ""),
            "host": "",
            "network": net,
            "note": "不在校园网（%s），无需登录" % (net.get("name") or ""),
            "ts": now(),
        }
        try:
            out["dead_path"] = dead_path()
        except Exception as e:
            out["dead_path"] = {"ok": False, "error": str(e)[:80]}
        # 不在校园网 ⇒ 没有在线时长；顺手把上次的会话标记清掉
        out["online_seconds"] = 0
        out["online_since"] = ""
        try:
            clear_session()
        except Exception:
            pass
        try:
            out["traffic"] = traffic_report()
        except Exception as e:
            out["traffic"] = {"ok": False, "error": str(e)[:80]}
        try:
            acc = active_account(cfg)
            out["account"] = {"name": acc.get("name", ""), "username": acc.get("username", "")}
            out["accounts"] = [{"name": a["name"], "username": a["username"]} for a in accounts(cfg)]
            out["current"] = _current_index(cfg, max(1, len(out["accounts"])))
        except Exception as e:
            out["account_error"] = str(e)[:80]
        save_state(last_status_at=now(), last_online=False)
        return out

    disc = discover(cfg)
    online = bool(disc.get("online"))
    out = {
        "online": online,
        "username": disc.get("online_user", "") if online else "",
        "ip": (disc.get("params") or {}).get("wlanuserip", ""),
        "host": disc.get("host", ""),
        "ts": now(),
    }
    # 在线时长：第一次看到 online 就记会话起点，离线就清掉
    try:
        if online:
            if not load_state().get("session_start"):
                mark_session_start()
            out["online_since"] = str(load_state().get("session_start") or "")
            out["online_seconds"] = online_duration_seconds()
        else:
            clear_session()
            out["online_seconds"] = 0
            out["online_since"] = ""
        # 加上当前账号名，面板要显示「用的是哪个号」
        acc = active_account(cfg)
        out["account"] = {"name": acc.get("name", ""), "username": acc.get("username", "")}
        out["accounts"] = [{"name": a["name"], "username": a["username"]} for a in accounts(cfg)]
        out["current"] = _current_index(cfg, max(1, len(out["accounts"])))
    except Exception as e:
        out["account_error"] = str(e)[:80]
    if disc.get("error"):
        out["error"] = disc["error"]
    if disc.get("note"):
        out["note"] = disc["note"]
    save_state(last_status_at=now(), last_online=online)
    # ⭐ 带上当前网络，前端靠它决定左边显示什么
    try:
        out["network"] = network_info()
    except Exception as e:
        out["network"] = {"ok": False, "error": str(e)[:80]}
    # ⭐ 顺带查有没有「挂着默认路由却走不通」的网卡（2026-11-03 那次 transport failed 的元凶）
    try:
        out["dead_path"] = dead_path()
    except Exception as e:
        out["dead_path"] = {"ok": False, "error": str(e)[:80]}
    return out


# --------------------------------------------------------------------------- 登录 / 断开

def login(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    acc = active_account(cfg)
    user = str(acc.get("username") or "").strip()
    pwd = str(acc.get("password") or "").strip()
    if not user or not pwd:
        return {"ok": False, "error": "还没填账号密码"}

    disc = discover(cfg)
    if disc.get("online_user") == user:
        return {"ok": True, "already": True, "message": "已经在线"}

    params = disc.get("params") or {}
    host = disc.get("host") or ""
    if not params or not host:
        return {"ok": False, "error": "拿不到门户参数（可能不在校园网里）"}

    info = portal_info(host, params)
    if not info:
        # 拿不到 portalForm 时用缓存参数兜底
        pf = {"wlanuserip": params.get("wlanuserip", ""),
              "wlanacname": params.get("wlanacname", ""),
              "vlan": params.get("vlan", "")}
        sf = {"serverip": params.get("wlanacip", "") or load_state().get("last_serverip", ""),
              "portalVer": 0}
        pc = {}
    else:
        pf = info.get("portalForm") or {}
        sf = info.get("serverForm") or {}
        pc = info.get("portalconfig") or {}
        if sf.get("serverip"):
            save_state(last_serverip=sf["serverip"])

    data = {
        "userid": user,
        "passwd": pwd,
        "wlanuserip": pf.get("wlanuserip", params.get("wlanuserip", "")),
        "wlanuseripv6": "",
        "wlanacname": pf.get("wlanacname", params.get("wlanacname", "")),
        "wlanacIp": sf.get("serverip", ""),
        "ssid": pf.get("ssid", ""),
        "vlan": pf.get("vlan", params.get("vlan", "")),
        "mac": pf.get("mac", ""),
        "version": sf.get("portalVer", 0),
        "portalpageid": pc.get("id", ""),
        "timestamp": "",
        "uuid": "",
        "portaltype": "",
        "hostname": "",
        "bindCtrlId": "",
        "validateType": "",
        "bindOperatorType": "2",
        "sendFttrNotice": "0",
        "validateCode": "",
    }

    q = urllib.parse.urlencode(data)
    st, body, _ = _get("http://%s/quickauth.do?%s" % (host, q), timeout=25)
    try:
        res = json.loads(body)
    except ValueError:
        return {"ok": False, "error": "响应非 JSON：%s" % body[:120]}

    ok = str(res.get("code")) == "0"
    save_state(last_login_at=now(), last_login_ok=ok,
               last_message=res.get("message", ""))
    if ok:
        try:
            mark_session_start()        # 记下本次会话起点和流量基线
        except Exception:
            pass
    return {
        "ok": ok,
        "message": res.get("message", ""),
        "group_id": res.get("groupId"),
        "raw_code": res.get("code"),
    }


def logout(cfg: dict | None = None, auto_reconnect: int | None = None) -> dict:
    """断开校园网。

    auto_reconnect：多少秒后自动重连（0 = 不重连）。默认取配置里的
    autoReconnectSeconds，避免断开后把自己锁在外面。
    """
    cfg = cfg or load_config()
    if auto_reconnect is None:
        auto_reconnect = int(cfg.get("autoReconnectSeconds") or 0)

    disc = discover(cfg)
    if not disc.get("online_user"):
        return {"ok": True, "already": True, "message": "本来就没登录"}

    params = disc.get("params") or {}
    host = disc.get("host") or ""
    data = {
        "wlanacip": params.get("wlanacip", ""),
        "wlanuserip": params.get("wlanuserip", ""),
        "wlanacname": params.get("wlanacname", ""),
        "version": params.get("version", "0"),
        "username": disc.get("online_user", ""),
    }
    st, body = _post("http://%s/quickauthdisconn.do" % host, data)
    try:
        res = json.loads(body)
        ok = str(res.get("code")) == "0"
        msg = res.get("message", "")
    except ValueError:
        ok, msg = st == 200, body[:80]

    save_state(last_logout_at=now(), last_logout_ok=ok)
    if ok:
        clear_session()          # 断开即结束本次在线时长

    out = {"ok": ok, "message": msg}
    if ok and auto_reconnect > 0:
        out["auto_reconnect_in"] = auto_reconnect
        _spawn_reconnect(auto_reconnect)
    return out


def _spawn_reconnect(seconds: int) -> None:
    """后台起一个脱离的进程，到点检查并重连。"""
    try:
        py = sys.executable
        if py.lower().endswith("python.exe"):
            pyw = py[:-10] + "pythonw.exe"
            if os.path.exists(pyw):
                py = pyw
        script = os.path.abspath(__file__)
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen(
            [py, script, "reconnect-after", "--seconds", str(seconds)],
            creationflags=creation, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def reconnect_after(seconds: int) -> dict:
    """等 N 秒，如果还离线就重连。"""
    time.sleep(max(1, seconds))
    s = status()
    if s.get("online"):
        return {"ok": True, "skipped": True, "message": "已经在线，不用重连"}
    return login()



# --------------------------------------------------------------------------- 网络识别

_PS_NET = r"""
$ErrorActionPreference = 'SilentlyContinue'
$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric, ifIndex | Select-Object -First 1
if (-not $route) { '{}'; exit }
$ifIdx = $route.ifIndex
$ip = Get-NetIPAddress -InterfaceIndex $ifIdx -AddressFamily IPv4 | Select-Object -First 1
$prof = Get-NetConnectionProfile -InterfaceIndex $ifIdx | Select-Object -First 1
$ad = Get-NetAdapter -InterfaceIndex $ifIdx | Select-Object -First 1
$o = [ordered]@{
  adapter    = if ($ad) { $ad.Name } else { '' }
  desc       = if ($ad) { $ad.InterfaceDescription } else { '' }
  ifIndex    = $ifIdx
  ip         = if ($ip) { $ip.IPAddress } else { '' }
  gateway    = [string]$route.NextHop
  metric     = [int]$route.RouteMetric
  profile    = if ($prof) { $prof.Name } else { '' }
  category   = if ($prof) { [string]$prof.NetworkCategory } else { '' }
  internet   = if ($prof) { [string]$prof.IPv4Connectivity } else { '' }
}
$o | ConvertTo-Json -Compress
"""


def _ps_json(script: str, timeout: int = 10) -> dict:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = (out.stdout or "").strip()
        if not raw:
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _wifi_ssid() -> dict:
    """从 netsh 读 WiFi SSID 和信号（只在 WLAN 连着时有）。"""
    try:
        out = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8", errors="replace")
        text = out.stdout or ""
    except Exception:
        return {}
    info = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if k in ("SSID",):
            info["ssid"] = v
        elif k in ("信号", "Signal"):
            info["signal"] = v
        elif k in ("状态", "State"):
            info["state"] = v
    if not info.get("ssid"):
        return {}
    return info


def campus_reachable(timeout: float = 2.0, force: bool = False) -> bool:
    """2.2.2.2:80 能不能连上 —— 判断"在不在校园网里"最直接的证据。

    磁盘缓存 30 秒：连不上时要白等一个 timeout，每次调用都等会很卡。
    """
    if not force:
        cached = _disk_cache_get("_campus_cache", _CAMPUS_TTL)
        if cached is not None:
            return bool(cached)
    ok = _campus_reachable_uncached(timeout)
    _disk_cache_put("_campus_cache", bool(ok))
    return ok


def _campus_reachable_uncached(timeout: float = 2.0) -> bool:
    import socket as _socket
    portal = "2.2.2.2"
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((portal, 80))
        s.close()
        return True
    except Exception:
        return False


def guess_kind(adapter: str, desc: str, ssid: str) -> str:
    """猜网络类型：wifi / 热点 / 有线 / 未知。

    热点和 WiFi 在系统层面分不开（都走 WLAN），只能按名字特征猜：
    手机热点通常带机型名（iPhone / OnePlus / Redmi / HUAWEI / 数字开头…）。
    """
    a = (adapter or "").lower()
    d = (desc or "").lower()
    if "wlan" in a or "wi-fi" in a or "wifi" in a or "wireless" in d:
        if ssid:
            hot = ("iphone", "ipad", "oneplus", "redmi", "xiaomi", "huawei", "honor",
                   "oppo", "vivo", "realme", "meizu", "samsung", "pixel", "hotspot", "热点")
            low = ssid.lower()
            if any(x in low for x in hot):
                return "hotspot"
            # 纯数字/带省份前缀的多半是运营商热点
            if any(x in low for x in ("cmcc", "china", "unicom", "telecom", "5g", "4g")):
                return "hotspot"
            return "wifi"
        return "wifi"
    if "以太网" in a or "ethernet" in a or "ethernet" in d:
        return "ethernet"
    if "cellular" in d or "移动" in a or "4g" in d or "5g" in d:
        return "cellular"
    return "unknown"


_NET_TTL = 30.0     # 网络变化不频繁，30 秒足够
_CAMPUS_TTL = 30.0


def _disk_cache_get(key: str, ttl: float):
    """磁盘缓存：每次请求都是新 Python 进程，内存缓存活不过一次调用。"""
    import time as _t
    st = load_state()
    c = st.get(key) or {}
    if c and (_t.time() - float(c.get("at") or 0)) < ttl:
        return c.get("data")
    return None


def _disk_cache_put(key: str, data) -> None:
    import time as _t
    st = load_state()
    st[key] = {"at": _t.time(), "data": data}
    st["updated_at"] = now()
    try:
        with open(STATE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def network_info(force: bool = False) -> dict:
    """当前走哪条网（按默认路由的最低 metric 判定）。磁盘缓存 30 秒。"""
    if not force:
        cached = _disk_cache_get("_net_cache", _NET_TTL)
        if cached:
            return cached
    data = _network_info_uncached()
    _disk_cache_put("_net_cache", data)
    return data


def _network_info_uncached() -> dict:
    base = _ps_json(_PS_NET)
    if not base:
        return {"ok": False, "error": "读不到路由表"}

    ssid_info = _wifi_ssid()
    ssid = ssid_info.get("ssid", "")
    adapter = str(base.get("adapter") or "")
    desc = str(base.get("desc") or "")

    kind = guess_kind(adapter, desc, ssid)

    # 显示名：WiFi/热点用 SSID；有线优先用网卡名（「以太网」比 Windows 的「网络 6」清楚）
    if ssid:
        name = ssid
    else:
        import re as _re
        prof = str(base.get("profile") or "").strip()
        # Windows 给没起名的有线连接会分配「网络 6」「Network 3」这种，别直接给用户看
        if not prof or _re.match(r"^(网络|Network)\s*\d+$", prof, _re.I):
            name = adapter or "有线网络"
        else:
            name = prof

    is_campus = campus_reachable()

    return {
        "ok": True,
        "name": name,
        "adapter": adapter,
        "desc": desc,
        "kind": kind,
        "ssid": ssid,
        "signal": ssid_info.get("signal", ""),
        "ip": str(base.get("ip") or ""),
        "gateway": str(base.get("gateway") or ""),
        "profile": str(base.get("profile") or ""),
        "category": str(base.get("category") or ""),
        "internet": "Internet" in str(base.get("internet") or ""),
        "is_campus": is_campus,
        "ts": now(),
    }


# --------------------------------------------------------------------------- 黑洞网卡
#
# 2026-11-03 的真实故障：校园网网卡（以太网）已经登出/未认证，但网卡还 up、
# 默认路由还挂着（跃点只是比热点高一点）。WiFi 一抖，系统就把流量切过去，
# SYN 发出去没人应答，客户端（Node/undici）10 秒后放弃 ——
# 表现出来就是三个模型服务商同时 "transport failed / Request timed out"。
#
# 所以这里要能提前发现「有默认路由但根本走不通」的网卡，并在挂件上标出来。

_PS_ROUTES = r"""
$ErrorActionPreference = 'SilentlyContinue'
$rows = @()
foreach ($r in Get-NetRoute -DestinationPrefix '0.0.0.0/0') {
  $ad  = Get-NetAdapter -InterfaceIndex $r.ifIndex
  $ip  = Get-NetIPAddress -InterfaceIndex $r.ifIndex -AddressFamily IPv4 | Select-Object -First 1
  $dns = @(Get-DnsClientServerAddress -InterfaceIndex $r.ifIndex -AddressFamily IPv4 |
             Select-Object -ExpandProperty ServerAddresses)
  $rows += [ordered]@{
    ifIndex = [int]$r.ifIndex
    adapter = if ($ad) { [string]$ad.Name } else { '' }
    desc    = if ($ad) { [string]$ad.InterfaceDescription } else { '' }
    status  = if ($ad) { [string]$ad.Status } else { '' }
    ip      = if ($ip) { [string]$ip.IPAddress } else { '' }
    gateway = [string]$r.NextHop
    metric  = [int]$r.InterfaceMetric
    dns     = $dns
  }
}
ConvertTo-Json -InputObject @($rows) -Compress -Depth 4
"""

_DEAD_TTL = 60.0        # 黑洞探测要真发包，缓存久一点（挂件每 3~8 秒轮询一次）
_DEAD_PROBE_TIMEOUT = 1.5
# 跃点 >= 这个值就认为「已经被处理过」：网卡还在、默认路由也还在，
# 但它抢不过当前网络，不会再造成 10 秒卡顿 —— 这时候不该继续报警。
# （fix_dead_path 抬到的正是 9999）
_NEUTERED_METRIC = 9000


def _routes() -> list[dict]:
    """所有 IPv4 默认路由（ConvertTo-Json 单条时会退化成对象，这里统一成列表）。"""
    data = _ps_json(_PS_ROUTES, timeout=12)
    if isinstance(data, dict):
        data = [data] if data else []
    return [d for d in data if isinstance(d, dict)]


def _tcp_via(src_ip: str, host: str, port: int, timeout: float) -> bool:
    """绑定某张网卡的源 IP 去握手 —— 这是判断「这条路能不能走」最直接的证据。

    ⚠️ 不能只 ping 网关：校园网网关 ping 得通（0ms），但没认证照样出不去。
    """
    import socket as _socket
    if not src_ip:
        return False
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.bind((src_ip, 0))
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def dead_path(force: bool = False) -> dict:
    """找出「有默认路由、但走不通」的网卡。没有就返回 present=False。

    判定：绑定源 IP 去连 223.5.5.5:443，1.5 秒内连不上就算黑洞。
       * 只连校园门户（2.2.2.2）不够 —— 未认证时门户照样通，但出不了网。
       * 探测结果缓存 60 秒，避免挂件每次轮询都白等 1.5 秒。
    """
    if not force:
        cached = _disk_cache_get("_dead_cache", _DEAD_TTL)
        if cached is not None:
            return cached

    net = network_info()          # 已带 30 秒缓存
    active = str(net.get("adapter") or "")
    routes = _routes()

    cands = []
    for r in routes:
        ad = str(r.get("adapter") or "")
        ip = str(r.get("ip") or "")
        if not ad or not ip:
            continue
        if ad.lower() == active.lower():
            continue                      # 当前正在用的那张不用查
        if str(r.get("status") or "").lower() not in ("up", "已启用", ""):
            continue
        cands.append(r)

    picked = None
    neutered = []
    for r in cands:
        if int(r.get("metric") or 0) >= _NEUTERED_METRIC:
            # 跃点已经被抬过（多半就是本插件修的），网卡还挂着但抢不过当前网络，
            # 不会再制造 10 秒卡顿 —— 不报警，只留个记录。
            neutered.append(str(r.get("adapter") or ""))
            continue
        ip = str(r.get("ip") or "")
        if _tcp_via(ip, "223.5.5.5", 443, _DEAD_PROBE_TIMEOUT):
            continue                      # 这张其实能上网，不是黑洞
        picked = r
        break

    if not picked:
        out = {"ok": True, "present": False, "active": active, "ts": now()}
        if neutered:
            out["neutralized"] = neutered
    else:
        out = {
            "ok": True,
            "present": True,
            "adapter": str(picked.get("adapter") or ""),
            "ifIndex": int(picked.get("ifIndex") or 0),
            "ip": str(picked.get("ip") or ""),
            "gateway": str(picked.get("gateway") or ""),
            "metric": int(picked.get("metric") or 0),
            "dns": [d for d in (picked.get("dns") or []) if d],
            "active": active,
            "reason": "挂在默认路由上，但 1.5 秒内连不通外网（未认证/已登出的校园网）",
            "ts": now(),
        }

    _disk_cache_put("_dead_cache", out)
    return out


def _run_elevated(body: str, timeout: int = 45) -> dict:
    """用 UAC 提权跑一段 PowerShell，结果通过临时 JSON 回传。

    返回值：{ok, errors[]}。用户点了「否」时 ok=False、error 里能看出来是取消了。
    """
    import tempfile
    tag = str(int(time.time() * 1000))
    ps1 = os.path.join(tempfile.gettempdir(), "campus-net-elev-%s.ps1" % tag)
    res = ps1 + ".json"
    script = (
        "$ErrorActionPreference = 'Stop'\r\n"
        "$err = @()\r\n"
        "$note = ''\r\n"
        "try {\r\n"
        + body + "\r\n"
        "} catch { $err += [string]$_.Exception.Message }\r\n"
        "[ordered]@{ ok = ($err.Count -eq 0); errors = @($err); note = [string]$note } | "
        "ConvertTo-Json -Compress | Set-Content -Path '" + res + "' -Encoding UTF8\r\n"
    )
    try:
        with open(ps1, "w", encoding="utf-8-sig") as fh:
            fh.write(script)
    except OSError as e:
        return {"ok": False, "error": "写临时脚本失败：%s" % e}

    launch = ("Start-Process -FilePath 'powershell' -ArgumentList "
              "'-NoProfile','-ExecutionPolicy','Bypass','-File','%s' "
              "-Verb RunAs -Wait -WindowStyle Hidden" % ps1)
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", launch],
                           capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        err = (p.stderr or "").strip()
    except Exception as e:
        return {"ok": False, "error": "提权调用失败：%s" % e}

    if os.path.exists(res):
        try:
            with open(res, encoding="utf-8-sig") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {"ok": False, "error": "返回值异常"}
        except Exception:
            pass

    if "取消" in err or "cancel" in err.lower():
        return {"ok": False, "error": "你取消了管理员授权，没改动任何东西"}
    return {"ok": False, "error": "提权执行没有结果" + (("：" + err[:160]) if err else "")}


def fix_dead_path(target: dict | None = None) -> dict:
    """把黑洞网卡的跃点抬到 9999；DNS 那步要看它是不是 DHCP 下发的。

    为什么是抬跃点而不是禁用：禁用要用户去设备管理器恢复，太狠；
    抬跃点只是让它永远抢不过热点，校园网要用时插上照样能用（只是优先级靠后）。

    🔴 关于 DNS（2026-11-03 实测踩到）：这台机器上以太网的 DNS 是 **DHCP 下发**的，
       `Set-DnsClientServerAddress -ResetServerAddresses` 只是「恢复成 DHCP 给的那份」——
       拿回来的还是同一批死 DNS，等于白做。所以这里先看 Dhcp 状态：
         * Disabled（静态）→ 才真的重置，dead DNS 会被清掉
         * Enabled（DHCP） → 跳过，并在结果里说清楚，别给用户假承诺
    """
    t = target or dead_path()
    if not t.get("present"):
        return {"ok": True, "action": "none", "message": "没有黑洞网卡，不用修"}
    idx = int(t.get("ifIndex") or 0)
    if not idx:
        return {"ok": False, "error": "拿不到网卡序号"}

    body = (
        "$nic = Get-NetIPInterface -InterfaceIndex {i} -AddressFamily IPv4\r\n"
        "Set-NetIPInterface -InterfaceIndex {i} -AddressFamily IPv4 -InterfaceMetric 9999\r\n"
        "if ($nic.Dhcp -eq 'Disabled') {{\r\n"
        "  Set-DnsClientServerAddress -InterfaceIndex {i} -ResetServerAddresses\r\n"
        "  $note = 'metric+dns'\r\n"
        "}} else {{ $note = 'metric-only' }}"
    ).format(i=idx)
    r = _run_elevated(body)
    if r.get("ok"):
        # 修完之后缓存里还留着「是黑洞」的结论，会误导前端，直接覆盖掉
        _disk_cache_put("_dead_cache", {"ok": True, "present": False, "ts": now()})
        name = t.get("adapter")
        if str(r.get("note") or "") == "metric-only":
            msg = "已把「%s」的跃点抬到 9999；它的 DNS 是 DHCP 下发的，重置等于把同一批死 DNS 又拿回来，已跳过（不影响路由）" % name
        else:
            msg = "已把「%s」的跃点抬到 9999 并清掉了它的静态 DNS" % name
        return {"ok": True, "action": "fix", "adapter": name, "note": r.get("note"), "message": msg}
    return {"ok": False, "action": "fix", "error": r.get("error") or ("；".join(r.get("errors") or []) or "失败")}


def restore_dead_path(target: dict | None = None) -> dict:
    """还原成「跃点自动」；DNS 只在它本来是静态时才重置。要回校园网时用。"""
    t = target or dead_path()
    idx = int(t.get("ifIndex") or 0)
    if not idx:
        return {"ok": False, "error": "没有可还原的网卡（黑洞已消失，或拿不到序号）"}
    body = (
        "$nic = Get-NetIPInterface -InterfaceIndex {i} -AddressFamily IPv4\r\n"
        "Set-NetIPInterface -InterfaceIndex {i} -AddressFamily IPv4 -AutomaticMetric Enabled\r\n"
        "if ($nic.Dhcp -eq 'Disabled') {{\r\n"
        "  Set-DnsClientServerAddress -InterfaceIndex {i} -ResetServerAddresses\r\n"
        "  $note = 'metric+dns'\r\n"
        "}} else {{ $note = 'metric-only' }}"
    ).format(i=idx)
    r = _run_elevated(body)
    if r.get("ok"):
        return {"ok": True, "action": "restore", "note": r.get("note"),
                "message": "已还原：跃点交回系统自动"}
    return {"ok": False, "action": "restore", "error": r.get("error") or ("；".join(r.get("errors") or []) or "失败")}


# --------------------------------------------------------------------------- 挂件位置

def ui_config() -> dict:
    """给前端读的轻量配置（不碰网络，纯读文件，几十毫秒）。"""
    cfg = load_config()
    return {
        "ok": True,
        "widgetLeft": int(cfg.get("widgetLeft", 10)),
        "widgetBottom": int(cfg.get("widgetBottom", 96)),
        "autoConnect": bool(cfg.get("autoConnect", True)),
        "autoReconnectSeconds": int(cfg.get("autoReconnectSeconds", 30)),
    }


def set_position(left, bottom) -> dict:
    """保存挂件位置。夹到合理范围，防止拖出屏幕再也找不回来。"""
    cfg = load_config()
    try:
        left = max(-200, min(4000, int(left)))
        bottom = max(0, min(3000, int(bottom)))
    except (TypeError, ValueError):
        return {"ok": False, "error": "位置不是数字"}
    cfg["widgetLeft"] = left
    cfg["widgetBottom"] = bottom
    save_config(cfg)
    return {"ok": True, "widgetLeft": left, "widgetBottom": bottom}


def reset_position() -> dict:
    cfg = load_config()
    cfg["widgetLeft"] = DEFAULT_CONFIG["widgetLeft"]
    cfg["widgetBottom"] = DEFAULT_CONFIG["widgetBottom"]
    save_config(cfg)
    return {"ok": True, "widgetLeft": cfg["widgetLeft"], "widgetBottom": cfg["widgetBottom"]}


# --------------------------------------------------------------------------- 测速

def _net_counters() -> dict:
    """读网卡累计收发字节。

    用 `netstat -e`（约 50ms）而不是 PowerShell（约 1.5s）——
    测速要连续采两次，PowerShell 光进程启动就占了大头。
    中英文系统都能解析，数据行长这样：
        字节           1234567890       987654321
        Bytes          1234567890       987654321
    """
    try:
        out = subprocess.run(
            ["netstat", "-e"], capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            encoding="utf-8", errors="replace")
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
                return {"rx": int(parts[1]), "tx": int(parts[2]), "adapters": 0, "via": "netstat"}
    except Exception:
        pass
    # 兜底：PowerShell
    ps = (
        "Get-NetAdapterStatistics -ErrorAction SilentlyContinue | "
        "Where-Object { $_.ReceivedBytes -gt 0 } | "
        "Select-Object Name,ReceivedBytes,SentBytes | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raw = (out.stdout or "").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        return {
            "rx": sum(int(d.get("ReceivedBytes") or 0) for d in data),
            "tx": sum(int(d.get("SentBytes") or 0) for d in data),
            "adapters": len(data), "via": "powershell",
        }
    except Exception:
        return {}


def speed_sample(window_ms: int = 700) -> dict:
    a = _net_counters()
    if not a:
        return {"ok": False, "error": "读不到网卡统计"}
    time.sleep(max(0.2, window_ms / 1000.0))
    b = _net_counters()
    if not b:
        return {"ok": False, "error": "读不到网卡统计"}
    dt = max(0.2, window_ms / 1000.0)
    rx = max(0, b["rx"] - a["rx"]) / dt
    tx = max(0, b["tx"] - a["tx"]) / dt
    return {
        "ok": True,
        "rx_bps": round(rx, 1), "tx_bps": round(tx, 1),
        "rx_human": human_bps(rx), "tx_human": human_bps(tx),
        "rx_total_gb": round(b["rx"] / 1024 ** 3, 2),
        "tx_total_gb": round(b["tx"] / 1024 ** 3, 2),
        "adapters": b.get("adapters", 0),
    }


def human_bps(bps: float) -> str:
    if bps < 1024:
        return "%.0f B/s" % bps
    if bps < 1024 * 1024:
        return "%.1f KB/s" % (bps / 1024)
    return "%.2f MB/s" % (bps / 1024 / 1024)


# --------------------------------------------------------------------------- 流量统计
#
# 数据源是 `netstat -e` 的累计计数（全机聚合、自开机起），所以：
#   * 「今日」「本次登录」都是靠前后两次采样做差
#   * 计数变小 = 重启过，此时把当前值直接当增量，别算出天文数字
#   * 采样有节流：30 秒内重复调用直接读缓存，不然面板每 3 秒轮询一次太重

_TRAFFIC_MIN_INTERVAL = 30.0
_TRAFFIC_KEEP_DAYS = 7


def traffic_report(force: bool = False) -> dict:
    st = load_state()
    t = dict(st.get("traffic") or {})
    now_ts = time.time()
    last_ts = float(t.get("last_ts") or 0)

    if force or (now_ts - last_ts) >= _TRAFFIC_MIN_INTERVAL:
        c = _net_counters()
        rx = int(c.get("rx") or 0)
        tx = int(c.get("tx") or 0)
        if c and (rx > 0 or tx > 0):
            today = time.strftime("%Y-%m-%d")

            if not t.get("last_ts"):
                # 第一次采样：没有历史可比，只能把当前累计值当基线，
                # 今日从 0 开始算 —— 否则会把「开机以来」整段算成「今天」。
                t = {"day": today, "day_rx": 0, "day_tx": 0,
                     "last_rx": rx, "last_tx": tx, "last_ts": now_ts,
                     "days": {}, "via": c.get("via", "")}
            else:
                day = str(t.get("day") or today)
                drx = int(t.get("day_rx") or 0)
                dtx = int(t.get("day_tx") or 0)
                days = dict(t.get("days") or {})

                if day != today:                    # 跨天：把昨天归档
                    days[day] = [drx, dtx]
                    day, drx, dtx = today, 0, 0

                last_rx = int(t.get("last_rx") or 0)
                last_tx = int(t.get("last_tx") or 0)
                dr = rx - last_rx if rx >= last_rx else rx      # 归零 ⇒ 重启过
                dt = tx - last_tx if tx >= last_tx else tx
                drx += max(0, dr)
                dtx += max(0, dt)

                if len(days) > _TRAFFIC_KEEP_DAYS:
                    for k in sorted(days)[:-_TRAFFIC_KEEP_DAYS]:
                        days.pop(k, None)

                t = {
                    "day": day, "day_rx": drx, "day_tx": dtx,
                    "last_rx": rx, "last_tx": tx, "last_ts": now_ts,
                    "days": days, "via": c.get("via", ""),
                }
            st["traffic"] = t
            st["updated_at"] = now()
            try:
                with open(STATE, "w", encoding="utf-8") as fh:
                    json.dump(st, fh, ensure_ascii=False, indent=2)
            except OSError:
                pass

    cur_rx = int(t.get("last_rx") or 0)
    cur_tx = int(t.get("last_tx") or 0)
    s0rx = int(st.get("session_rx0") or 0)
    s0tx = int(st.get("session_tx0") or 0)
    sess_rx = cur_rx - s0rx if (s0rx and cur_rx >= s0rx) else 0
    sess_tx = cur_tx - s0tx if (s0tx and cur_tx >= s0tx) else 0

    days = t.get("days") or {}
    return {
        "ok": bool(t),
        "today_rx": int(t.get("day_rx") or 0),
        "today_tx": int(t.get("day_tx") or 0),
        "day": t.get("day") or time.strftime("%Y-%m-%d"),
        "boot_rx": cur_rx,
        "boot_tx": cur_tx,
        "session_rx": max(0, sess_rx),
        "session_tx": max(0, sess_tx),
        "days": [{"day": d, "rx": v[0], "tx": v[1]} for d, v in sorted(days.items(), reverse=True)],
        "via": t.get("via", ""),
        "ts": now(),
    }


def mark_session_start() -> None:
    """登录成功那一刻记一笔，用来算「本次登录用了多少流量」。"""
    c = _net_counters()
    save_state(session_start=now(),
               session_rx0=int(c.get("rx") or 0),
               session_tx0=int(c.get("tx") or 0))


def clear_session() -> None:
    st = load_state()
    if st.get("session_start"):
        try:
            st.pop("session_start", None)
            st.pop("session_rx0", None)
            st.pop("session_tx0", None)
            st["updated_at"] = now()
            with open(STATE, "w", encoding="utf-8") as fh:
                json.dump(st, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass


def online_duration_seconds() -> int:
    st = load_state()
    start = str(st.get("session_start") or "")
    if not start:
        return 0
    try:
        t0 = time.mktime(time.strptime(start, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0
    return max(0, int(time.time() - t0))


def ensure_online(cfg: dict | None = None) -> dict:
    """开机自检：在线就什么都不做，离线就登录。"""
    cfg = cfg or load_config()
    s = status(cfg)
    if s.get("online"):
        return {"ok": True, "action": "none", "detail": "已在线"}
    r = login(cfg)
    return {"ok": bool(r.get("ok")), "action": "login", "detail": r.get("message", r.get("error", ""))}


# --------------------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    cmd = (argv[0] if argv else "status").lower()
    if not os.path.exists(CONFIG):
        save_config(load_config())

    if cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    elif cmd == "login":
        print(json.dumps(login(), ensure_ascii=False, indent=2))
    elif cmd in ("logout", "disconnect"):
        secs = 0
        if "--no-reconnect" in argv:
            secs = 0
        elif "--reconnect" in argv:
            i = argv.index("--reconnect")
            secs = int(argv[i + 1]) if i + 1 < len(argv) else 30
        else:
            secs = int(load_config().get("autoReconnectSeconds") or 0)
        print(json.dumps(logout(auto_reconnect=secs), ensure_ascii=False, indent=2))
    elif cmd == "reconnect-after":
        secs = 30
        if "--seconds" in argv:
            i = argv.index("--seconds")
            secs = int(argv[i + 1]) if i + 1 < len(argv) else 30
        print(json.dumps(reconnect_after(secs), ensure_ascii=False, indent=2))
    elif cmd == "ensure":
        print(json.dumps(ensure_online(), ensure_ascii=False, indent=2))
    elif cmd == "speed":
        print(json.dumps(speed_sample(), ensure_ascii=False, indent=2))
    elif cmd == "ui":
        print(json.dumps(ui_config(), ensure_ascii=False, indent=2))
    elif cmd == "set-position":
        try:
            l = int(argv[1]); b = int(argv[2])
        except (IndexError, ValueError):
            print(json.dumps({"ok": False, "error": "用法: set-position <left> <bottom>"}, ensure_ascii=False))
            return 1
        print(json.dumps(set_position(l, b), ensure_ascii=False, indent=2))
    elif cmd == "reset-position":
        print(json.dumps(reset_position(), ensure_ascii=False, indent=2))
    elif cmd == "network":
        print(json.dumps(network_info(), ensure_ascii=False, indent=2))
    elif cmd in ("dead-path", "dead"):
        print(json.dumps(dead_path(force="--force" in argv), ensure_ascii=False, indent=2))
    elif cmd == "fix-path":
        print(json.dumps(fix_dead_path(dead_path(force=True)), ensure_ascii=False, indent=2))
    elif cmd == "restore-path":
        print(json.dumps(restore_dead_path(dead_path(force=True)), ensure_ascii=False, indent=2))
    elif cmd == "discover":
        print(json.dumps(discover(), ensure_ascii=False, indent=2))
    elif cmd in ("accounts", "account"):
        cfg = load_config()
        lst = accounts(cfg)
        print(json.dumps({
            "ok": True,
            "current": _current_index(cfg, max(1, len(lst))),
            "accounts": [{"name": a["name"], "username": a["username"]} for a in lst],
        }, ensure_ascii=False, indent=2))
    elif cmd in ("switch-account", "use"):
        target = argv[1] if len(argv) > 1 else ""
        if not target:
            print(json.dumps({"ok": False, "error": "用法: switch-account <序号|名字>"}, ensure_ascii=False))
            return 1
        print(json.dumps(switch_account(target), ensure_ascii=False, indent=2))
    elif cmd == "traffic":
        print(json.dumps(traffic_report(force="--force" in argv), ensure_ascii=False, indent=2))
    elif cmd == "config":
        c = load_config()
        c["password"] = "***" if c.get("password") else ""
        c["accounts"] = [{"name": a["name"], "username": a["username"],
                          "password": "***" if a["password"] else ""}
                         for a in _clean_accounts(c.get("accounts"))]
        print(json.dumps(c, ensure_ascii=False, indent=2))
    elif cmd == "doctor":
        checks = []
        c = load_config()
        checks.append({"check": "配置", "ok": bool(c.get("username")),
                       "detail": "账号" + ("已填" if c.get("username") else "未填")})
        d = discover(c)
        checks.append({"check": "校园网可达", "ok": bool(d.get("ok")),
                       "detail": d.get("error") or ("门户 %s" % d.get("host"))})
        checks.append({"check": "登录状态", "ok": True,
                       "detail": ("在线 %s" % d.get("online_user")) if d.get("online") else "离线"})
        sp = speed_sample(400)
        checks.append({"check": "网卡统计", "ok": bool(sp.get("ok")),
                       "detail": sp.get("rx_human", sp.get("error", ""))})
        ok = all(x["ok"] for x in checks)
        print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    else:
        print("用法: campus-net.py status|login|logout|ensure|speed|network|traffic|accounts|switch-account|dead-path|fix-path|restore-path|ui|set-position|reset-position|discover|config|doctor")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))