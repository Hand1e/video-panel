/**
 * DeepSeek Harness (dsh) plugin: exposes the Family Video Studio workbench as agent tools.
 * The workbench backend must be running:  python -m studio   (http://127.0.0.1:8765)
 *
 * Load:  pnpm dsh web --patch ./harness-plugin/cordis.yml      (from dsh source checkout)
 * NOTE: dsh is a developer preview; if the defineTool signature changed, adjust here only.
 */
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'family-video-studio'
export const inject = ['tools']

const BASE = process.env.STUDIO_URL ?? 'http://127.0.0.1:8765'

async function call(path: string, init?: RequestInit & { json?: unknown }): Promise<any> {
  const opts: RequestInit = { ...init }
  if (init?.json !== undefined) {
    opts.method = opts.method ?? 'POST'
    opts.headers = { 'Content-Type': 'application/json' }
    opts.body = JSON.stringify(init.json)
  }
  const r = await fetch(BASE + path, opts)
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`)
  return r.json()
}

/** Start a workbench job and wait for it (the workbench runs its own generate→critique→revise loop). */
async function job(start: Promise<any>, timeoutS = 1800): Promise<any> {
  const s = await start
  const t0 = Date.now()
  for (;;) {
    const j = await call(`/api/jobs/${s.job}`)
    if (j.status === 'done') return { project: s.project ?? j.project, result: j.result, log: j.log.map((l: any) => l.msg) }
    if (j.status === 'error') throw new Error(j.error)
    if ((Date.now() - t0) / 1000 > timeoutS) throw new Error('timeout')
    await new Promise((r) => setTimeout(r, 2000))
  }
}

/** Keep tool output small for the agent: verdicts + loop summary, not the full artefacts. */
function loopSummary(res: any) {
  return {
    best_iteration: res?.best_iteration,
    stop_reason: res?.stop_reason,
    scores: res?.rounds?.map((r: any) => ({ it: r.iteration, avg: r.avg, min: r.min })),
    rollbacks: res?.rollbacks,
  }
}

export function apply(ctx: Context) {
  ctx.tools.register(defineTool({
    name: 'studio_status',
    description: '家庭视频工作台状态：是否演示模式、模型、ffmpeg、循环参数。',
    parameters: {},
    async execute() { return call('/api/status') },
  }))

  ctx.tools.register(defineTool({
    name: 'studio_analyze_topic',
    description: '分析一个视频选题（链接或关键词）：为什么火、数据、观众需求、饱和度、我家能不能拍、改编角度、结论。',
    parameters: { text: { type: 'string', required: true, description: '视频链接（B站/抖音/小红书/快手/YouTube）或关键词' } },
    async execute({ text }: { text: string }) {
      const fd = new FormData()
      fd.append('text', text)
      const out = await job(call('/api/analyze', { method: 'POST', body: fd }))
      const b = out.result.best ?? {}
      return { project: out.project, verdict: b.verdict, score: b.score, one_liner: b.one_liner,
               feasibility: b.feasibility, angles: b.angles, risks: b.risks, loop: loopSummary(out.result),
               ui: `${BASE}/?pid=${out.project}&tab=topics` }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'studio_daily_topics',
    description: '拉取今日 B站热门里的生活类视频，改编成 3 个我家（我+爱人+宝宝）能拍的选题。适合每天定时运行。',
    parameters: {},
    async execute() {
      const out = await job(call('/api/topics/daily', { method: 'POST' }))
      return { project: out.project, topics: out.result.best?.topics, loop: loopSummary(out.result),
               ui: `${BASE}/?pid=${out.project}&tab=topics` }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'studio_script',
    description: '为项目写脚本与台词大纲（含宝宝捕捉方案）。不传 title 时使用该项目的选题分析结果。',
    parameters: {
      project: { type: 'string', required: true, description: '项目 id' },
      title: { type: 'string', required: false, description: '选题标题（可选）' },
    },
    async execute({ project, title }: { project: string; title?: string }) {
      const out = await job(call(`/api/projects/${project}/script`, { json: { brief: title ? { title } : null } }))
      const b = out.result.best ?? {}
      return { title: b.title, logline: b.logline, beats: b.beats, loop: loopSummary(out.result),
               ui: `${BASE}/?pid=${project}&tab=project` }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'studio_storyboard',
    description: '根据脚本生成简笔画分镜 + 拍摄清单（按机位/宝宝作息排序，含场记口令）。',
    parameters: { project: { type: 'string', required: true, description: '项目 id' } },
    async execute({ project }: { project: string }) {
      const out = await job(call(`/api/projects/${project}/storyboard`, { method: 'POST' }))
      return { shots: out.result.best?.shots?.length, loop: loopSummary(out.result),
               storyboard_ui: `${BASE}/?pid=${project}&tab=project`, shotlist_ui: `${BASE}/?pid=${project}&tab=shoot` }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'studio_footage_cut',
    description: '素材直剪：引用本地素材文件夹 → 素材理解 → 剪辑方案 → 剪辑+审片循环 → 成片。',
    parameters: {
      folder: { type: 'string', required: true, description: '素材所在本地文件夹' },
      intent: { type: 'string', required: false, description: '想要的效果，例如“抖音 30 秒，温馨搞笑”' },
      project: { type: 'string', required: false, description: '已有项目 id；不传则新建' },
    },
    async execute({ folder, intent, project }: { folder: string; intent?: string; project?: string }) {
      const pid = project ?? (await call('/api/projects', { json: { title: `直剪 ${folder.split(/[\/]/).pop()}`, mode: 'footage_only' } })).id
      await call(`/api/projects/${pid}/footage/folder`, { json: { folder } })
      const out = await job(call(`/api/projects/${pid}/footage-direct`, { json: { intent: intent ?? '' } }), 7200)
      return { project: pid, final: out.result.final, duration_s: out.result.best?.duration_s,
               titles: out.result.best?.title_options, loop: loopSummary(out.result),
               ui: `${BASE}/?pid=${pid}&tab=review` }
    },
  }))
}
