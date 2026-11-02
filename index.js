/**
 * dsh-campus-net —— 服务端
 * ============================================================================
 * 只做一件事：把 /api/campus-net/* 的请求转给 core/campus_net.py，再把 JSON 回给浏览器。
 * 真正的登录/断开/测速逻辑都在 Python 里（已单独验证过，也能脱离 DSH 用）。
 *
 * 为什么用 Python 而不是全写成 Node：
 *   * 门户那套参数（wlanuserip / wlanacname / vlan / version）每次登录都要重新发现，
 *     Python 版已经跑通并留了缓存兜底，重写一遍风险大。
 *   * 测速要读 Windows 网卡计数器，Python 调 PowerShell 也是现成的。
 *   代价是每次调用多 ~80ms 进程启动，对这个场景无所谓。
 * ============================================================================
 */
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { createRetry } from './retry.js'

export const name = 'campus-net'
export const inject = []
/** webServer 只在桌面/web 版存在，headless 里没有 —— 走 optional，缺了就不挂路由 */
export const optional = ['webServer']

const HERE = dirname(fileURLToPath(import.meta.url))
const CORE = join(HERE, 'core', 'campus_net.py')

/** Python 解释器：环境变量优先，其次常见路径，最后退回 PATH 里的 python */
function pythonExe() {
  const env = String(process.env.CAMPUS_NET_PYTHON || '').trim()
  if (env && existsSync(env)) return env
  const cands = [
    'C:\\Users\\ASUS\\AppData\\Local\\Programs\\Python\\Python312\\python.exe',
    'C:\\Users\\ASUS\\AppData\\Local\\Programs\\Python\\Python311\\python.exe',
    join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
  ]
  for (const c of cands) if (c && existsSync(c)) return c
  return 'python'
}

/** 跑一次 Python 核心，解析 JSON */
function runCore(args, timeout = 40_000) {
  return new Promise((resolve) => {
    execFile(pythonExe(), [CORE, ...args], {
      timeout,
      windowsHide: true,
      maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    }, (err, stdout, stderr) => {
      const out = String(stdout || '').trim()
      if (!out) {
        resolve({ ok: false, error: (err && err.message) || String(stderr || '').slice(0, 200) || '没有输出' })
        return
      }
      // 先整体解析；不行再按「第一个 { 到最后一个 }」截取。
      // 🔴 曾经写成 lastIndexOf('{')，嵌套对象（比如 network）会把开头截到内层括号，
      //    解析必然失败 —— 加了 network 字段之后面板就整个空了。
      try {
        resolve(JSON.parse(out))
        return
      } catch { /* 再试截取 */ }
      const start = out.indexOf('{')
      const end = out.lastIndexOf('}')
      const slice = start >= 0 && end > start ? out.slice(start, end + 1) : out
      try {
        resolve(JSON.parse(slice))
      } catch {
        resolve({ ok: false, error: '输出不是 JSON：' + out.slice(0, 160) })
      }
    })
  })
}

function sendJson(res, code, obj) {
  const body = JSON.stringify(obj)
  try {
    res.writeHead(code, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      'access-control-allow-origin': '*',
      'access-control-allow-headers': 'content-type',
      'access-control-allow-methods': 'GET,POST,OPTIONS',
    })
    res.end(body)
  } catch { /* 头可能已经发出去了 */ }
}

function readBody(req) {
  return new Promise((resolve) => {
    let buf = ''
    req.on('data', (c) => { buf += c; if (buf.length > 1e6) req.destroy() })
    req.on('end', () => {
      try { resolve(JSON.parse(buf || '{}')) } catch { resolve({}) }
    })
    req.on('error', () => resolve({}))
  })
}

export function apply(ctx, config) {
  const log = (m) => { try { ctx.logger?.info?.(`[campus-net] ${m}`) } catch { /* 没 logger 就算了 */ } }

  /* ── 时间窗自动重试 ────────────────────────────────────────────────────
   * 学校在非上网时段会返回「不允许上网时间段，请在上网时段认证」。
   * 具体逻辑在 retry.js（抽出去是为了能单测，不用真等 10 分钟）。
   */
  const retryCtl = createRetry({
    runEnsure: () => runCore(['ensure'], 60_000),
    log,
  })
  const retryInfo = () => retryCtl.info()
  const reactToResult = (r) => retryCtl.react(r)
  const stopRetry = (why) => retryCtl.stop(why)

  const handle = async (req, res, url) => {
    if (req.method === 'OPTIONS') {
      sendJson(res, 204, {})
      return
    }
    const path = url.pathname

    if (req.method === 'GET' && path === '/api/campus-net/status') {
      const s = await runCore(['status'], 30_000)
      // 把自动重试的进度并进 status，省得前端多开一个轮询
      if (s && typeof s === 'object') s.auto_retry = retryInfo()
      return sendJson(res, 200, s)
    }

    if (req.method === 'GET' && path === '/api/campus-net/ui') {
      return sendJson(res, 200, await runCore(['ui'], 15_000))
    }

    if (req.method === 'POST' && path === '/api/campus-net/position') {
      const b = await readBody(req)
      const l = Number(b.left)
      const bt = Number(b.bottom)
      return sendJson(res, 200, await runCore(
        ['set-position', String(Number.isFinite(l) ? Math.round(l) : 10),
         String(Number.isFinite(bt) ? Math.round(bt) : 96)], 15_000))
    }

    if (req.method === 'POST' && path === '/api/campus-net/reset-position') {
      return sendJson(res, 200, await runCore(['reset-position'], 15_000))
    }

    if (req.method === 'GET' && path === '/api/campus-net/network') {
      return sendJson(res, 200, await runCore(['network'], 25_000))
    }

    /** 黑洞网卡：有默认路由但走不通（要把 UAC 提权也算进超时） */
    if (req.method === 'GET' && path === '/api/campus-net/dead-path') {
      return sendJson(res, 200, await runCore(['dead-path'], 30_000))
    }

    if (req.method === 'POST' && path === '/api/campus-net/fix-path') {
      log('修黑洞网卡（抬跃点 + 清死 DNS）')
      return sendJson(res, 200, await runCore(['fix-path'], 90_000))
    }

    if (req.method === 'POST' && path === '/api/campus-net/restore-path') {
      log('还原网卡跃点')
      return sendJson(res, 200, await runCore(['restore-path'], 90_000))
    }

    if (req.method === 'GET' && path === '/api/campus-net/speed') {
      return sendJson(res, 200, await runCore(['speed'], 30_000))
    }

    if (req.method === 'GET' && path === '/api/campus-net/config') {
      const c = await runCore(['config'], 20_000)
      return sendJson(res, 200, { ok: true, config: c, core: CORE, python: pythonExe() })
    }

    if (req.method === 'GET' && path === '/api/campus-net/doctor') {
      return sendJson(res, 200, await runCore(['doctor'], 45_000))
    }

    if (req.method === 'POST' && path === '/api/campus-net/login') {
      log('手动登录')
      return sendJson(res, 200, reactToResult(await runCore(['login'], 45_000)))
    }

    if (req.method === 'POST' && path === '/api/campus-net/switch-account') {
      const body = await readBody(req)
      const which = body.index !== undefined ? String(body.index) : String(body.name || '')
      log(`切换账号 → ${which}`)
      const r = await runCore(['switch-account', which], 20_000)
      if (r && r.ok) stopRetry('切号')
      return sendJson(res, 200, r)
    }

    if (req.method === 'POST' && path === '/api/campus-net/logout') {
      const body = await readBody(req)
      const secs = Number.isFinite(Number(body.reconnect))
        ? String(Math.max(0, Math.min(600, Number(body.reconnect))))
        : '30'
      log(`断开校园网（${secs} 秒后自动重连）`)
      return sendJson(res, 200, await runCore(['logout', '--reconnect', secs], 45_000))
    }

    if (req.method === 'POST' && path === '/api/campus-net/ensure') {
      return sendJson(res, 200, reactToResult(await runCore(['ensure'], 45_000)))
    }

    return sendJson(res, 404, { ok: false, error: '没有这个接口' })
  }

  /** 开机/启动时自动连一次（不阻塞启动） */
  const kick = () => {
    try {
      const t = setTimeout(() => {
        runCore(['ensure'], 60_000)
          .then((r) => {
            log(`启动自检：${r.action === 'none' ? '已在线' : (r.ok ? '已登录' : '登录失败：' + (r.detail || r.error || ''))}`)
            reactToResult(r)
          })
          .catch(() => {})
      }, 8000)   // 等宿主和其它插件先起来
      t.unref?.()
    } catch { /* 忽略 */ }
  }

  ctx.inject(['webServer'], (webCtx) => {
    try {
      webCtx.effect(() => webCtx.get('webServer').register({
        kind: 'prefix',
        path: '/api/campus-net',
        handler: async (req, res) => {
          try {
            await handle(req, res, new URL(req.url, 'http://127.0.0.1'))
          } catch (e) {
            sendJson(res, 500, { ok: false, error: e?.message ?? String(e) })
          }
        },
      }), 'campus-net: /api/campus-net 路由')
      log('接口已就绪')
      kick()
    } catch (e) {
      log(`路由没挂上：${e?.message ?? e}`)
    }
  })
}