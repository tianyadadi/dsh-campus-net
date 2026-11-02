/**
 * 「非上网时段」自动重试控制器
 * ============================================================================
 * 学校在非上网时段会返回「不允许上网时间段，请在上网时段认证」，以前遇到就停在那儿，
 * 得用户自己想起来再点一次。这里把它变成：每 N 分钟自动试一次，成功或到上限就停。
 *
 * 单独成文件是为了能真测 —— 抽出来以后可以传 50ms 的间隔跑单测，不用等 10 分钟。
 * ============================================================================
 */

/** 学校返回的「现在不让上网」类错误 */
export const TIMEWINDOW_RE = /上网时段|时间窗|时间段|非上网|不允许上网/i

/** 这句话看起来像不像时间窗限制 */
export function looksLikeTimeWindow(text) {
  return TIMEWINDOW_RE.test(String(text || ''))
}

/**
 * @param {object} opts
 * @param {() => Promise<any>} opts.runEnsure  真去连一次，返回 {ok, detail, error, message}
 * @param {(msg: string) => void} [opts.log]
 * @param {number} [opts.intervalMs]  重试间隔，默认 10 分钟
 * @param {number} [opts.max]         最多试几次，默认 60（≈10 小时）
 */
export function createRetry({ runEnsure, log = () => {}, intervalMs = 10 * 60 * 1000, max = 60 }) {
  const state = { active: false, attempts: 0, nextAt: 0, lastMessage: '', timer: null }

  const info = () => ({
    active: state.active,
    attempts: state.attempts,
    max,
    nextAt: state.nextAt,
    lastMessage: state.lastMessage,
  })

  const stop = (why) => {
    if (!state.active) return
    state.active = false
    state.nextAt = 0
    if (state.timer) { clearTimeout(state.timer); state.timer = null }
    log(`自动重试停止：${why || '已成功'}`)
  }

  const schedule = () => {
    if (!state.active) return
    state.nextAt = Date.now() + intervalMs
    if (state.timer) clearTimeout(state.timer)
    const t = setTimeout(tick, intervalMs)
    t.unref?.()
    state.timer = t
  }

  const tick = async () => {
    if (!state.active) return
    state.attempts += 1
    let r = null
    try {
      r = await runEnsure()
    } catch { /* 抛错就当这次没成功 */ }
    if (r && r.ok) { log(`自动重试成功（第 ${state.attempts} 次）`); stop('成功'); return }
    if (state.attempts >= max) { stop('到上限'); return }
    schedule()
  }

  const start = (message) => {
    if (state.active) return
    state.active = true
    state.attempts = 0
    state.lastMessage = String(message || '')
    log('进入非上网时段，开始自动重试')
    schedule()
  }

  /** 每次登录 / ensure 之后过一遍：成功就停，撞上时间窗就开始排队 */
  const react = (r) => {
    if (!r) return r
    if (r.ok) { stop('登录成功'); return r }
    const text = `${r.detail || ''} ${r.error || ''} ${r.message || ''}`
    if (looksLikeTimeWindow(text)) start(text.trim())
    return r
  }

  return { info, react, start, stop, tick, _state: state }
}