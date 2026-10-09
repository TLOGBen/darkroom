import type { Register, SessionRateLimit } from 'claude-code'

// Temporary mod for the darkroom campaign (2026-10-09): the user asked for Fable subagents until
// 2026-10-10 02:00 +08:00, and for an automatic switch to Opus 5.5 whenever usage gets tight.
const TIGHT_PERCENT = 85                                   // any 5-hour or 7-day window at or past this is "tight"
const FABLE_UNTIL_MS = Date.parse('2026-10-10T02:00:00+08:00')
const WINDOWS = ['five_hour', 'seven_day']

let limits: SessionRateLimit[] = []
let warned = ''

const label = (k: string) => (k === 'five_hour' ? '5h' : k === 'seven_day' ? '7d' : k)
const tightOnes = () => limits.filter(l => WINDOWS.includes(l.kind) && l.percentUsed >= TIGHT_PERCENT)
const summary = () => limits.filter(l => WINDOWS.includes(l.kind)).map(l => `${label(l.kind)} ${l.percentUsed}%`).join(' · ')

const statusText = () => {
  const s = summary()
  return s ? `用量 ${s}${tightOnes().length ? '（緊繃：子代理改 Opus）' : ''}` : undefined
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    try { limits = (await $.session.usage()).rateLimits } catch { /* no reading yet */ }
    $.ui.status(statusText())
    return r
  })

  on('session.measure', ($, e, next) => {
    limits = e.rateLimits
    $.ui.status(statusText())
    return next(e)
  })

  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    if (e.model !== 'fable') return next(e)
    const tight = tightOnes()
    const expired = (await $.clock.now()) >= FABLE_UNTIL_MS
    if (!tight.length && !expired) return next(e)
    const why = tight.length ? `用量緊繃（${tight.map(l => `${label(l.kind)} ${l.percentUsed}%`).join('、')}）` : 'Fable 期間已過（10/10 02:00）'
    if (warned !== why) { warned = why; $.ui.toast(`usage-guard：${why}，子代理改用 Opus 5.5`) }
    return next({ ...e, model: 'opus' })
  }).catch(($, e, next) => next(e))   // never block a subagent because this mod failed
}
