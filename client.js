/**
 * dsh-campus-net —— 浏览器半端
 * ============================================================================
 * 在侧边栏左下角挂一只常驻小挂件：
 *   · 折叠态：网络类型图标 + 当前网络名 + 实时上下行速度 + 连通点
 *   · 点击展开：网络详情、校园网状态、网速条、连接/断开按钮
 *
 * ⭐ 网络名自动识别：走手机热点显示热点名，走校园网显示「校园网」，插网线显示以太网。
 *    判定在后端 network_info()（按默认路由最低 metric）。
 *
 * ⭐ 位置可拖动：不同人的 DSH 侧边栏高度不一样，固定的 bottom 可能压住账号区。
 *    按住挂件拖到合适位置，松手就记住（存后端 config 的 widgetLeft/widgetBottom）。
 *    面板里有「复位」按钮回到默认位置。
 *
 * 位置用 position:fixed，不依赖宿主布局 API —— 宿主改版也不会跑位。
 * 整个组件包在 Boundary 里，任何子组件抛错只显示「出错了」，不会把界面搞没。
 * ============================================================================
 */
window.__ModuleLoader__.load({
  id: 'dsh-campus-net',
  factory: (require) => {
    const React = require('react')
    const h = React.createElement
    const { useState, useEffect, useRef, useCallback } = React

    const API = '/api/campus-net'
    /** 每次改 client.js 就 +1，方便确认浏览器加载的是新代码 */
    const BUILD = 7

    /** 默认位置（像素，从视口左下角算）。可拖动覆盖。 */
    const DEFAULT_POS = { left: 10, bottom: 96 }

    /* ── 请求 ─────────────────────────────────────────────────────────── */
    const req = async (p, opts, timeoutMs) => {
      const ctl = new AbortController()
      const t = setTimeout(() => ctl.abort(), timeoutMs || 15000)
      try {
        const res = await fetch(API + p, Object.assign({ credentials: 'same-origin', signal: ctl.signal }, opts))
        if (!res.ok) throw new Error('HTTP ' + res.status)
        return await res.json()
      } finally {
        clearTimeout(t)
      }
    }
    const jget = (p, ms) => req(p, {}, ms)
    const jpost = (p, body, ms) => req(p, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body || {}),
    }, ms)

    /* ── 错误边界 ─────────────────────────────────────────────────────── */
    class Boundary extends React.Component {
      constructor(p) { super(p); this.state = { err: null } }
      static getDerivedStateFromError(e) { return { err: String((e && e.message) || e) } }
      render() {
        if (this.state.err) {
          return h('div', { style: S.errBox }, '⚠️ 校园网挂件出错了：', this.state.err)
        }
        return this.props.children
      }
    }

    /* ── 样式 ─────────────────────────────────────────────────────────── */
    const S = {
      wrap: (pos) => ({
        position: 'fixed',
        left: pos.left + 'px',
        bottom: pos.bottom + 'px',
        zIndex: 2147483000,
        fontFamily: '-apple-system, "Segoe UI", "Microsoft YaHei", sans-serif',
        userSelect: 'none',
      }),
      pill: {
        display: 'flex', alignItems: 'center', gap: '6px',
        padding: '7px 11px', borderRadius: '999px',
        background: 'rgba(24,26,32,.92)',
        border: '1px solid rgba(255,255,255,.10)',
        boxShadow: '0 6px 20px rgba(0,0,0,.36)',
        cursor: 'grab', color: '#e6e8ee', fontSize: '12px',
        backdropFilter: 'blur(10px)',
        maxWidth: '236px',
      },
      icon: { fontSize: '12px', lineHeight: 1, flexShrink: 0 },
      netName: {
        fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis',
        whiteSpace: 'nowrap', maxWidth: '92px', flexShrink: 1,
      },
      speed: { color: '#9aa3b2', fontSize: '11px', fontVariantNumeric: 'tabular-nums', flexShrink: 0 },
      dot: (on) => ({
        width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0,
        background: on ? '#35d07f' : '#f05a5a',
        boxShadow: on ? '0 0 7px rgba(53,208,127,.85)' : '0 0 7px rgba(240,90,90,.7)',
      }),
      card: {
        width: '262px', padding: '13px', borderRadius: '13px',
        background: 'rgba(24,26,32,.97)',
        border: '1px solid rgba(255,255,255,.10)',
        boxShadow: '0 12px 34px rgba(0,0,0,.5)',
        color: '#e6e8ee', fontSize: '12px', backdropFilter: 'blur(12px)',
      },
      head: {
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: '9px', cursor: 'grab',
      },
      title: { display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, fontSize: '13px', minWidth: 0 },
      titleText: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '150px' },
      build: { color: '#5f6675', fontSize: '10px', fontWeight: 400 },
      close: { cursor: 'pointer', color: '#7d8595', fontSize: '15px', lineHeight: 1, padding: '0 2px', flexShrink: 0 },
      row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '3px 0', color: '#9aa3b2', gap: '8px' },
      rowVal: (on) => ({
        color: on ? '#e6e8ee' : '#f05a5a', fontVariantNumeric: 'tabular-nums',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '152px',
      }),
      sep: { height: '1px', background: 'rgba(255,255,255,.07)', margin: '8px 0' },
      meter: { marginTop: '4px' },
      bar: { height: '5px', borderRadius: '3px', background: 'rgba(255,255,255,.08)', overflow: 'hidden', marginTop: '3px' },
      fill: (w, c) => ({ width: Math.max(1, Math.min(100, w)) + '%', height: '100%', background: c, borderRadius: '3px', transition: 'width .35s ease' }),
      btns: { display: 'flex', gap: '6px', marginTop: '10px' },
      btn: (primary, disabled) => ({
        flex: 1, padding: '7px 0', borderRadius: '8px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.42 : 1,
        border: '1px solid ' + (primary ? 'rgba(53,208,127,.42)' : 'rgba(255,255,255,.13)'),
        background: primary ? 'rgba(53,208,127,.16)' : 'rgba(255,255,255,.05)',
        color: primary ? '#6ee6a3' : '#c6ccd8', fontSize: '12px', fontWeight: 500,
      }),
      btnDanger: (disabled) => ({
        flex: 1, padding: '7px 0', borderRadius: '8px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.42 : 1,
        border: '1px solid rgba(240,90,90,.42)',
        background: 'rgba(240,90,90,.13)', color: '#ff8b8b', fontSize: '12px', fontWeight: 500,
      }),
      note: { marginTop: '8px', fontSize: '11px', color: '#7d8595', lineHeight: 1.5 },
      warn: { marginTop: '8px', fontSize: '11px', color: '#e0b341', lineHeight: 1.5 },
      deadBox: {
        marginTop: '9px', padding: '8px 9px', borderRadius: '9px',
        background: 'rgba(224,179,65,.10)', border: '1px solid rgba(224,179,65,.34)',
        color: '#e7c46a', fontSize: '11px', lineHeight: 1.55,
      },
      deadTitle: { fontWeight: 600, marginBottom: '2px' },
      dotWarn: {
        width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0,
        background: '#e0b341', boxShadow: '0 0 7px rgba(224,179,65,.8)',
      },
      errBox: { padding: '9px 11px', borderRadius: '9px', background: 'rgba(90,20,20,.9)', color: '#ffb4b4', fontSize: '11px', maxWidth: '240px' },
    }

    /* ── 小工具 ───────────────────────────────────────────────────────── */
    const fmt = (bps) => {
      const v = Number(bps) || 0
      if (v < 1024) return v.toFixed(0) + ' B/s'
      if (v < 1048576) return (v / 1024).toFixed(1) + ' KB/s'
      return (v / 1048576).toFixed(2) + ' MB/s'
    }
    const barW = (bps) => (Math.min(1, (Number(bps) || 0) / (10 * 1048576)) * 100)

    const KIND = {
      hotspot: { icon: '📱', label: '手机热点' },
      wifi: { icon: '📶', label: 'WiFi' },
      ethernet: { icon: '🔌', label: '有线' },
      cellular: { icon: '📡', label: '蜂窝' },
      campus: { icon: '🎓', label: '校园网' },
      unknown: { icon: '🌐', label: '网络' },
    }
    const netIdentity = (net, online) => {
      if (!net || net.ok === false) {
        if (online) return Object.assign({ campus: true, raw: null }, KIND.campus, { name: '校园网' })
        return Object.assign({ campus: false, raw: null }, KIND.unknown, { name: '网络' })
      }
      if (net.is_campus) return Object.assign({ campus: true, raw: net }, KIND.campus, { name: '校园网' })
      const k = KIND[net.kind] || KIND.unknown
      return Object.assign({ campus: false, raw: net }, k, { name: net.name || k.label })
    }

    /* ── 主挂件 ───────────────────────────────────────────────────────── */
    function Widget() {
      const [open, setOpen] = useState(false)
      const [st, setSt] = useState(null)
      const [sp, setSp] = useState(null)
      const [busy, setBusy] = useState('')
      const [msg, setMsg] = useState('')
      const [countdown, setCountdown] = useState(0)
      const [pos, setPos] = useState(DEFAULT_POS)
      const [posReady, setPosReady] = useState(false)
      const alive = useRef(true)
      const cdRef = useRef(null)
      const drag = useRef({ on: false, sx: 0, sy: 0, ol: 0, ob: 0, moved: false })

      useEffect(() => () => { alive.current = false; if (cdRef.current) clearInterval(cdRef.current) }, [])

      /* 启动时读一次位置（轻量接口，不碰网络） */
      useEffect(() => {
        ;(async () => {
          try {
            const r = await jget('/ui', 8000)
            if (alive.current && r && r.ok) {
              setPos({ left: Number(r.widgetLeft) || 10, bottom: Number(r.widgetBottom) || 96 })
            }
          } catch { /* 读不到就用默认 */ }
          if (alive.current) setPosReady(true)
        })()
      }, [])

      const pullStatus = useCallback(async () => {
        try {
          const r = await jget('/status', 14000)
          if (alive.current) setSt(r)
        } catch { /* 断网时别刷错误，保留上次 */ }
      }, [])

      const pullSpeed = useCallback(async () => {
        try {
          const r = await jget('/speed', 14000)
          if (alive.current && r && r.ok) setSp(r)
        } catch { /* 忽略 */ }
      }, [])

      useEffect(() => {
        pullStatus()
        const iv = setInterval(pullStatus, open ? 3000 : 8000)
        return () => clearInterval(iv)
      }, [open, pullStatus])

      useEffect(() => {
        pullSpeed()
        const iv = setInterval(pullSpeed, open ? 2000 : 3500)
        return () => clearInterval(iv)
      }, [open, pullSpeed])

      /* ── 拖动 ── */
      const beginDrag = (e) => {
        if (e.button !== 0) return
        if (e.target && e.target.getAttribute && e.target.getAttribute('data-no-drag') === '1') return
        drag.current = { on: true, sx: e.clientX, sy: e.clientY, ol: pos.left, ob: pos.bottom, moved: false }
        e.preventDefault()
      }

      useEffect(() => {
        const onMove = (e) => {
          const d = drag.current
          if (!d.on) return
          const dx = e.clientX - d.sx
          const dy = e.clientY - d.sy
          if (Math.abs(dx) > 3 || Math.abs(dy) > 3) d.moved = true
          // 夹到视口内，别拖丢了
          const left = Math.max(-40, Math.min(window.innerWidth - 80, d.ol + dx))
          const bottom = Math.max(0, Math.min(window.innerHeight - 40, d.ob - dy))
          setPos({ left, bottom })
        }
        const onUp = () => {
          const d = drag.current
          if (!d.on) return
          d.on = false
          if (!d.moved) return
          // 拖完记住
          setPos((p) => {
            jpost('/position', { left: Math.round(p.left), bottom: Math.round(p.bottom) }, 10000).catch(() => {})
            return p
          })
        }
        window.addEventListener('mousemove', onMove)
        window.addEventListener('mouseup', onUp)
        return () => {
          window.removeEventListener('mousemove', onMove)
          window.removeEventListener('mouseup', onUp)
        }
      }, [])

      const handlePillClick = () => {
        if (drag.current.moved) { drag.current.moved = false; return }
        setOpen(true)
      }

      const doReset = async () => {
        try {
          const r = await jpost('/reset-position')
          if (r && r.ok) { setPos({ left: r.widgetLeft, bottom: r.widgetBottom }); setMsg('位置已复位') }
        } catch { setMsg('复位失败') }
      }

      const startCountdown = (secs) => {
        if (cdRef.current) clearInterval(cdRef.current)
        setCountdown(secs)
        cdRef.current = setInterval(() => {
          setCountdown((n) => {
            if (n <= 1) { clearInterval(cdRef.current); cdRef.current = null; pullStatus(); return 0 }
            return n - 1
          })
        }, 1000)
      }

      const doLogin = async () => {
        setBusy('login'); setMsg('')
        try {
          const r = await jpost('/login')
          setMsg(r.ok ? (r.already ? '已经在线' : '连接成功 ✅') : ('连接失败：' + (r.error || r.message || '未知')))
          await pullStatus()
        } catch (e) { setMsg('连接失败：' + (e.message || e)) }
        setBusy('')
      }

      const doLogout = async () => {
        setBusy('logout'); setMsg('')
        try {
          const r = await jpost('/logout', { reconnect: 30 })
          if (r.ok) { setMsg('已断开，30 秒后自动重连'); startCountdown(30) }
          else setMsg('断开失败：' + (r.error || r.message || '未知'))
          await pullStatus()
        } catch (e) { setMsg('断开失败：' + (e.message || e)) }
        setBusy('')
      }

      /* 黑洞网卡：抬跃点 + 清死 DNS（会弹 UAC） */
      const doFixPath = async () => {
        setBusy('fix'); setMsg('')
        try {
          const r = await jpost('/fix-path', {}, 90000)
          setMsg(r.ok ? (r.message || '已修好') : ('没修成：' + (r.error || '未知')))
          await pullStatus()
        } catch (e) { setMsg('没修成：' + (e.message || e)) }
        setBusy('')
      }

      const doRestorePath = async () => {
        setBusy('restore'); setMsg('')
        try {
          const r = await jpost('/restore-path', {}, 90000)
          setMsg(r.ok ? (r.message || '已还原') : ('还原失败：' + (r.error || '未知')))
          await pullStatus()
        } catch (e) { setMsg('还原失败：' + (e.message || e)) }
        setBusy('')
      }

      const net = st && st.network ? st.network : null
      const id = netIdentity(net, Boolean(st && st.online))
      const campus = id.campus
      const online = Boolean(st && st.online)
      const rx = sp ? sp.rx_bps : 0
      const tx = sp ? sp.tx_bps : 0
      const dotOn = campus ? online : Boolean(net && net.internet)
      /* ⭐ 黑洞网卡：有默认路由却走不通的那张 —— 它是「transport failed」的元凶 */
      const dead = st && st.dead_path && st.dead_path.present ? st.dead_path : null
      const neutered = st && st.dead_path && st.dead_path.neutralized ? st.dead_path.neutralized : null

      /* 位置还没读出来时先不渲染，避免闪一下再跳 */
      if (!posReady) return null

      /* ── 折叠态 ── */
      if (!open) {
        return h('div', { style: S.wrap(pos) },
          h('div', {
            style: S.pill,
            onMouseDown: beginDrag,
            onClick: handlePillClick,
            title: id.name + '（按住可拖动位置）',
          },
            h('span', { style: S.icon }, id.icon),
            h('span', { style: S.netName }, id.name),
            h('span', { style: S.speed }, '↓' + (sp ? fmt(rx) : '…')),
            h('span', { style: S.speed }, '↑' + (sp ? fmt(tx) : '…')),
            dead
              ? h('span', { style: S.dotWarn, title: '「' + dead.adapter + '」挂着默认路由但走不通，会害模型超时' })
              : h('span', { style: S.dot(dotOn) }),
          ),
        )
      }

      /* ── 展开态 ── */
      return h('div', { style: S.wrap(pos) },
        h('div', { style: S.card },

          h('div', { style: S.head, onMouseDown: beginDrag, title: '按住可拖动位置' },
            h('div', { style: S.title },
              h('span', { style: S.icon }, id.icon),
              h('span', { style: S.titleText, title: id.name }, id.name),
              h('span', { style: S.build }, 'b' + BUILD),
            ),
            h('span', {
              style: S.close,
              'data-no-drag': '1',
              onClick: () => setOpen(false),
              title: '收起',
            }, '×'),
          ),

          h('div', { style: S.row }, h('span', null, '类型'), h('span', { style: S.rowVal(true) }, id.label)),
          net && net.adapter ? h('div', { style: S.row },
            h('span', null, '网卡'), h('span', { style: S.rowVal(true), title: net.desc || '' }, net.adapter)) : null,
          net && net.ip ? h('div', { style: S.row },
            h('span', null, 'IP'), h('span', { style: S.rowVal(true) }, net.ip)) : null,
          net && net.signal ? h('div', { style: S.row },
            h('span', null, '信号'), h('span', { style: S.rowVal(true) }, net.signal)) : null,

          h('div', { style: S.sep }),

          campus
            ? h('div', { style: S.row },
                h('span', null, '校园网'),
                h('span', { style: S.rowVal(online) }, online ? '已连接' : '未连接'))
            : h('div', { style: S.warn }, '当前不在校园网（' + id.label + '）—— 连接/断开只对校园网有效'),

          campus && st && st.username ? h('div', { style: S.row },
            h('span', null, '账号'), h('span', { style: S.rowVal(true) }, st.username)) : null,

          dead ? h('div', { style: S.deadBox },
            h('div', { style: S.deadTitle }, '⚠️ 「' + dead.adapter + '」是条黑洞'),
            '它还挂在默认路由上（跃点 ' + dead.metric + '），但走不通。',
            h('br'),
            'WiFi 一抖，系统就把流量切给它，然后卡 10 秒 —— 模型那边就是 transport failed。',
            h('br'),
            h('span', { style: { color: '#9aa3b2' } },
              '建议：抬跃点让它抢不过当前网络（会弹一次管理员授权）。'),
          ) : null,

          dead ? h('div', { style: S.btns },
            h('button', {
              style: S.btn(true, busy === 'fix'),
              disabled: busy === 'fix',
              onClick: doFixPath,
            }, busy === 'fix' ? '处理中…（等授权）' : '修一下'),
            h('button', {
              style: S.btn(false, busy === 'restore'),
              disabled: busy === 'restore',
              onClick: doRestorePath,
            }, busy === 'restore' ? '还原中…' : '还原跃点'),
          ) : null,

          !dead && neutered ? h('div', { style: S.note },
            '已处理：' + neutered.join('、') + ' 的跃点被抬高，不会再抢网。') : null,

          h('div', { style: S.meter },
            h('div', { style: { display: 'flex', justifyContent: 'space-between', marginTop: '6px' } },
              h('span', { style: { color: '#9aa3b2' } }, '下载'),
              h('span', { style: S.speed }, sp ? fmt(rx) : '…')),
            h('div', { style: S.bar }, h('div', { style: S.fill(barW(rx), 'linear-gradient(90deg,#3b82f6,#22d3ee)') })),
            h('div', { style: { display: 'flex', justifyContent: 'space-between', marginTop: '7px' } },
              h('span', { style: { color: '#9aa3b2' } }, '上传'),
              h('span', { style: S.speed }, sp ? fmt(tx) : '…')),
            h('div', { style: S.bar }, h('div', { style: S.fill(barW(tx), 'linear-gradient(90deg,#a855f7,#ec4899)') })),
          ),

          h('div', { style: S.btns },
            online
              ? h('button', {
                  style: S.btnDanger(!campus || busy === 'logout'),
                  disabled: !campus || busy === 'logout',
                  onClick: doLogout,
                }, busy === 'logout' ? '断开中…' : '断开')
              : h('button', {
                  style: S.btn(true, !campus || busy === 'login'),
                  disabled: !campus || busy === 'login',
                  onClick: doLogin,
                }, busy === 'login' ? '连接中…' : '连接'),
            h('button', { style: S.btn(false, false), onClick: () => { pullStatus(); pullSpeed() } }, '刷新'),
          ),

          h('div', { style: { ...S.btns, marginTop: '6px' } },
            h('button', {
              style: { ...S.btn(false, false), flex: 'none', width: '100%', padding: '5px 0', fontSize: '11px' },
              onClick: doReset,
            }, '复位挂件位置'),
          ),

          countdown > 0 ? h('div', { style: S.warn }, '⏳ ' + countdown + ' 秒后自动重连…') : null,
          msg ? h('div', { style: S.note }, msg) : null,
          h('div', { style: S.note },
            '按住挂件可拖动位置，松手自动记住。',
            h('br'),
            '断开后 30 秒没手动连回会自动重连。',
            h('br'),
            'DSH 起不来时，双击插件目录里的「救急重连.cmd」。'),
        ),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        const slots = (typeof ctx.get === 'function' ? ctx.get('slots') : undefined) || ctx.slots
        if (!slots) return
        slots.inject('shell.overlay', () => slots.register(
          { name: 'shell.overlay', id: 'campus-net', order: 950 },
          () => h(Boundary, null, h(Widget)),
        ))
      },
    }
  },
})