import type { Register } from 'claude-code'

// Temporary mod for the darkroom campaign (2026-10-10). The main session runs a long
// /common:strategic-advance campaign with many background agents; a compaction that drops the
// HQ packet (which fronts are active, which agents and schedules are live, what the user decided)
// costs a full reconstruction. This mod watches the context fill and steers every compaction.
const WARN_PERCENT = 70
const URGENT_PERCENT = 85

const KEEP = [
  'This is a long darkroom campaign run with /common:strategic-advance. The summary MUST keep, verbatim where possible:',
  '1. Where truth lives: D:/Code/darkroom/.strategic-advance/darkroom-alpha/state.json (rebuild the HQ packet from it after compaction, never from chat memory), the ledger run-ledger.jsonl next to it, the map .claude/wayfinder/darkroom/map.md, the contracts in .claude/contract/, CONTEXT.md, AGENTS.md, and the memory folder C:/Users/powde/.claude/projects/D--Code-darkroom/memory/.',
  '2. Every background agent still running: its id, what it was asked to do, its model, and whether it works on main or in a worktree (with the worktree path and branch).',
  '3. Every scheduled job (cron id, what it fires, when it ends) and every one-shot schedule still pending.',
  '4. The active fronts and their state (sealed / in progress / deferred / needs the user), and the next move.',
  '5. Every decision the user made in this session, in their words, with the date: scope additions, product core (讓人省心), model policy, privacy rules, what must never be written or published.',
  '6. Open findings not yet fixed, with file:line, and anything the user is waiting on from the agent or the agent from the user.',
  'Drop raw tool output, file dumps, and resolved back-and-forth.',
].join('\n')

let percent: number | undefined
let warnedAt = 0

const statusText = () => (percent === undefined ? undefined : `ctx ${percent}%`)

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await $.command.register({
      name: 'hq-compact',
      description: 'Compact now, keeping the darkroom campaign HQ packet (fronts, agents, schedules, user decisions)',
    })
    try { percent = (await $.session.usage()).context.percent } catch { /* no reading yet */ }
    $.ui.status(statusText())
    return r
  })

  on('session.measure', ($, e, next) => {
    percent = e.context.percent
    $.ui.status(statusText())
    if (percent !== undefined) {
      const level = percent >= URGENT_PERCENT ? URGENT_PERCENT : percent >= WARN_PERCENT ? WARN_PERCENT : 0
      if (level > warnedAt) {
        warnedAt = level
        $.ui.toast(level === URGENT_PERCENT
          ? `compact-helper：context ${percent}%，建議現在就 /hq-compact`
          : `compact-helper：context ${percent}%，找個空檔 /hq-compact`)
      }
      if (percent < WARN_PERCENT) warnedAt = 0
    }
    return next(e)
  })

  on('command.run', { command: 'hq-compact' }, async $ => {
    await $.session.compact({ instructions: KEEP })
    return { text: '已壓縮（保留戰役 HQ 封包）。' }
  })

  // Every compaction of the main conversation (manual, threshold, or ahead of time) keeps the packet.
  on('session.compact', ($, e, next) => {
    if (e.agentId) return next(e)
    const instructions = e.instructions ? `${e.instructions}\n\n${KEEP}` : KEEP
    return next({ ...e, instructions })
  }).catch(($, e, next) => next(e))
}
