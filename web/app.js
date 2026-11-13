// Family Video Studio — single-page workbench (no build step)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const qs = new URLSearchParams(location.search);
const state = { pid: qs.get("pid") || localStorage.getItem("pid") || null, project: null };

async function api(path, opts = {}) {
  const init = { ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, init);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

// project-relative file URL from an absolute path inside data/projects/<pid>/
function fileUrl(p, pid = state.pid) {
  if (!p) return "";
  const norm = String(p).replace(/\\/g, "/");
  const i = norm.indexOf(`/${pid}/`);
  return i < 0 ? "" : `/files/${pid}/${norm.slice(i + pid.length + 2)}?v=${Date.now() % 1e6}`;
}

// ---------------- tabs / projects ----------------
$$("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
function showTab(t) {
  $$("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $$(".tab").forEach((s) => s.classList.toggle("on", s.id === `tab-${t}`));
}

async function loadProjects() {
  const ps = await api("/api/projects");
  const sel = $("#projectSel");
  sel.innerHTML = `<option value="">— 选择项目 —</option>` +
    ps.map((p) => `<option value="${esc(p.id)}">${esc(p.title)} · ${esc(p.stage)}</option>`).join("");
  if (state.pid && ps.some((p) => p.id === state.pid)) sel.value = state.pid;
  else state.pid = null;
}
$("#projectSel").addEventListener("change", (e) => selectProject(e.target.value));

async function selectProject(pid) {
  state.pid = pid || null;
  localStorage.setItem("pid", pid || "");
  if (!pid) { state.project = null; renderAll(); return; }
  state.project = await api(`/api/projects/${pid}`);
  renderAll();
}
async function refresh() { if (state.pid) await selectProject(state.pid); await loadProjects(); }

function needProject() {
  if (!state.pid) { alert("先在右上角选一个项目，或新建项目"); return false; }
  return true;
}

// ---------------- jobs ----------------
async function runJob(title, promise) {
  const panel = $("#jobPanel");
  panel.classList.remove("hidden");
  $("#jobTitle").textContent = title;
  $("#jobRounds").innerHTML = "";
  $("#jobLog").textContent = "提交中…";
  let start;
  try { start = await promise; } catch (e) { $("#jobLog").textContent = "失败：" + e.message; throw e; }
  if (start.project && start.project !== state.pid) { state.pid = start.project; localStorage.setItem("pid", state.pid); }
  for (;;) {
    const j = await api(`/api/jobs/${start.job}`);
    $("#jobLog").textContent = j.log.map((l) => `[${l.t}s] ${l.msg}`).join("\n");
    $("#jobRounds").innerHTML = roundsHtml(j.rounds);
    if (j.status !== "running") {
      if (j.status === "error") { $("#jobLog").textContent += `\n\n${j.trace || ""}`; throw new Error(j.error); }
      await refresh();
      return j.result;
    }
    await new Promise((r) => setTimeout(r, 1200));
  }
}
$("#jobClose").addEventListener("click", () => $("#jobPanel").classList.add("hidden"));

function guard(btn, fn) {
  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    btn.disabled = true;
    try { await fn(); } catch (err) { console.error(err); } finally { btn.disabled = false; }
  });
}

// ---------------- loop / critic rendering ----------------
function roundsHtml(rounds, bestIt) {
  if (!rounds || !rounds.length) return "";
  return `<div class="rounds">` + rounds.map((r) =>
    `<div class="round ${r.passed ? "pass" : ""} ${r.iteration === bestIt ? "best" : ""}" title="${esc(JSON.stringify(r.scores))}">
      第${r.iteration}轮 平均 <b>${r.avg}</b> 最低 ${r.min}${r.passed ? " ✅" : ""}</div>`).join("") + `</div>`;
}
function loopHtml(res, label) {
  if (!res) return "";
  const last = res.rounds?.[res.rounds.length - 1];
  const stop = res.stop_reason;
  const scores = last ? Object.entries(last.scores).map(([d, s]) =>
    `<div class="issue"><span class="dim">${esc(d)}</span>${s}<span class="scorebar" style="width:${s * 10}px"></span></div>`).join("") : "";
  const issues = (last?.issues || []).map((i) =>
    `<div class="issue"><span class="dim">${esc(i.dim)}</span>${esc(i.problem)} → ${esc(i.fix)} <span class="owner">[${esc(i.stage_owner)}]</span></div>`).join("");
  const rb = (res.rollbacks || []).length ? `<p class="hint">⤴ 回滚建议：${[...new Set(res.rollbacks.map((r) => r.stage_owner))].map(esc).join("、")}（问题出在上游环节）</p>` : "";
  return `<details class="card"><summary><b>${esc(label)} · 自审循环</b>：${res.rounds?.length || 0} 轮，采用第 ${res.best_iteration} 版，停止原因：${esc(stop)}</summary>
    ${roundsHtml(res.rounds, res.best_iteration)}<h3>最后一轮评分</h3>${scores}${issues ? `<h3>遗留问题</h3>${issues}` : ""}${rb}</details>`;
}
const mockTag = (o) => (o && o._mock ? ` <span class="mockTag">演示数据</span>` : "");

// ---------------- ① topics ----------------
$("#analyzeForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("button", e.target);
  btn.disabled = true;
  try {
    const out = await runJob("选题分析", api("/api/analyze", { method: "POST", body: new FormData(e.target) }));
    await selectProject(out.project);
    await loadProjects();
  } catch {} finally { btn.disabled = false; }
});
guard($("#dailyBtn"), async () => {
  const out = await runJob("今日选题", api("/api/topics/daily", { method: "POST" }));
  await selectProject(out.project);
});

function verdictCls(v) { return /不/.test(v || "") ? "v-no" : /改编|谨慎/.test(v || "") ? "v-adapt" : "v-go"; }

function renderAnalysis(a) {
  const b = a.best || {};
  const ev = (x) => (x?.evidence ? `<div class="ev">${esc(x.evidence)}</div>` : "");
  const src = a.source || {};
  const v = src.video;
  const f = b.feasibility || {};
  return `<div class="card">
    <h2><span class="verdict ${verdictCls(b.verdict)}">${esc(b.verdict)}</span>${esc(b.score)} / 10 · 置信度 ${esc(b.confidence)}${mockTag(b)}</h2>
    <p><b>${esc(b.one_liner)}</b></p>
    ${v ? `<p class="hint">来源：<a href="${esc(v.url)}" target="_blank">${esc(v.title)}</a> · 播放 ${esc(v.stats?.view)} · 点赞率 ${esc(v.derived?.like_rate)} · 收藏率 ${esc(v.derived?.favorite_rate)} · UP 粉丝 ${fmtNum(v.derived?.followers)} · ${viralTag(v.derived?.viral_ratio, v.derived?.viral_level, v.derived?.low_sample)}</p>` : ""}
    ${(src.gaps || []).length ? `<p class="hint">⚠ 数据缺口：${src.gaps.map(esc).join("；")}</p>` : ""}
    <h3>为什么火（钩子拆解）</h3><ul>${(b.hook_breakdown || []).map((h) => `<li>${esc(h.point)}${ev(h)}</li>`).join("")}</ul>
    <h3>数据</h3><p>${esc(b.data?.summary)}</p>${ev(b.data)}
    <h3>观众需求</h3><ul>${(b.audience_needs || []).map((n) => `<li>${esc(n.need)}${ev(n)}</li>`).join("")}</ul>
    <h3>饱和度</h3><p>${esc(b.saturation?.level)}</p>${ev(b.saturation)}
    <h3>你家能不能拍</h3><p>可行性 ${esc(f.score)} / 10 · 需要：${esc((f.needs_cast || []).join("、"))} · 机位：${esc((f.cameras || []).join("、"))} · 成本 ¥${esc(f.cost_cny)}</p>
    <p class="hint">${esc(f.baby_fit)}</p>
    <h3>建议角度</h3><div class="angles">${(b.angles || []).map((g, i) =>
      `<div class="angle"><b>${esc(g.title)}</b><p>${esc(g.pitch)}</p><p class="hint">差异：${esc(g.why_different)}</p>
        <button data-angle="${i}">用这个角度写脚本 →</button></div>`).join("")}</div>
    <h3>风险</h3><ul>${(b.risks || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    <h3>什么情况说明判断错了</h3><ul>${(b.falsified_if || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    ${(a.extra_evidence || []).length ? `<p class="hint">自动补查：${a.extra_evidence.map((x) => esc(x.query)).join("；")}</p>` : ""}
  </div>${loopHtml(a, "分析")}`;
}

function viralTag(r, level, low) {
  if (r === null || r === undefined) return `<span class="hint">爆款系数 未知</span>`;
  const cls = low ? "v-adapt" : r >= 1 ? "v-go" : r >= 0.2 ? "v-adapt" : "v-no";
  return `<span class="vr ${cls}" title="播放 ÷ 粉丝数：越高说明越是选题本身带量">爆款系数 ${r}${level ? " · " + esc(level) : ""}</span>`;
}

function renderCalendar(cal) {
  if (!cal || cal.age_months === null || cal.age_months === undefined) return "";
  const block = (title, m) => m ? `<h3>${title}</h3><p>${m.milestones.map(esc).join("、")}</p>
    <p class="hint">选题种子：${m.ideas.map(esc).join("；")}</p><p class="hint">安全：${m.safety.map(esc).join("；")}</p>` : "";
  return `<details class="card"><summary><b>月龄日历</b>：宝宝 ${cal.age_months} 个月</summary>
    ${block("这个月常见", cal.now)}${block("下个月可能出现（提前准备好机位）", cal.next)}
    ${(cal.events || []).length ? `<p>纪念日：${cal.events.map(esc).join("、")}</p>` : ""}
    ${(cal.seasonal || []).length ? `<p>当季：${cal.seasonal.map(esc).join("、")}</p>` : ""}
    <p class="hint">${esc(cal.note)}</p></details>`;
}

function renderTrending(items, errors) {
  if (!items || !items.length) return (errors || []).length ? `<p class="hint">⚠ 热门获取失败：${errors.map(esc).join("；")}</p>` : "";
  return `<details class="card"><summary><b>参考热门</b>：${items.length} 条，按爆款系数排序</summary>
    <p class="hint">爆款系数 = 播放 ÷ UP 主粉丝数。大于 1 说明播放超出了粉丝圈，是选题本身带量，最值得小号借鉴。</p>
    <table class="tr"><tr><th>标题</th><th>榜单</th><th>UP 粉丝</th><th>播放</th><th>系数</th></tr>
    ${items.map((it) => `<tr><td><a href="${esc(it.url)}" target="_blank">${esc(it.title)}</a>${it.small_creator ? ' <span class="mockTag" style="background:#d3f9d8;color:#2b8a3e">小UP</span>' : ""}</td>
      <td>${esc(it.list)}</td><td>${fmtNum(it.followers)}</td><td>${fmtNum(it.stats?.view)}</td><td>${viralTag(it.viral_ratio, it.low_sample ? "粉丝过少·仅供参考" : "", it.low_sample)}</td></tr>`).join("")}
    </table></details>`;
}
const fmtNum = (n) => (n === null || n === undefined ? "?" : n >= 1e4 ? (n / 1e4).toFixed(1) + "万" : String(n));

function renderTopics(t) {
  const b = t.best || {};
  const srcTag = (x) => x.source === "milestone" ? `<span class="src src-m">月龄日历</span>` : `<span class="src src-t">热点改编</span>`;
  return `<div class="card"><h2>今日选题（${(b.topics || []).length} 个）${mockTag(b)}</h2><div class="angles">${(b.topics || []).map((x, i) =>
    `<div class="angle">${srcTag(x)}<b>${esc(x.title)}</b><p>${esc(x.angle)}</p>
      ${x.why_now ? `<p class="hint">为什么是现在：${esc(x.why_now)}</p>` : ""}
      <p class="hint">出镜：${esc((x.cast || []).join("、"))} · 机位：${esc((x.cameras || []).join("、"))} · ${esc(x.duration_s)}s · ¥${esc(x.cost_cny)}</p>
      <p class="hint">${esc(x.feasibility)} · 系列：${esc(x.series_potential)}</p>
      ${(x.inspired_by || []).length ? `<p class="hint">灵感：${x.inspired_by.map((s) => `<a href="${esc(s.url)}" target="_blank">${esc(s.title)}</a> ${viralTag(s.viral_ratio)}`).join("；")}</p>` : ""}
      <button data-topic="${i}">做这个 →</button></div>`).join("")}</div></div>
    ${renderCalendar(t.milestone_calendar)}${renderTrending(t.trending, t.trending_errors)}${loopHtml(t, "选题")}`;
}

$("#topicsOut").addEventListener("click", async (e) => {
  const p = state.project;
  const ai = e.target.dataset.angle, ti = e.target.dataset.topic;
  if (ai === undefined && ti === undefined) return;
  let brief;
  if (ai !== undefined) { const b = p.analysis.best; brief = { title: b.angles[ai].title, angle: b.angles[ai], analysis: b }; }
  else { brief = { title: p.topics.best.topics[ti].title, topic: p.topics.best.topics[ti] }; }
  e.target.disabled = true;
  try {
    await runJob("写脚本", api(`/api/projects/${state.pid}/script`, { json: { brief } }));
    showTab("project");
  } finally { e.target.disabled = false; }
});

// ---------------- ② script + storyboard ----------------
guard($("#newProjectBtn"), async () => {
  const title = $("#newTitle").value.trim();
  if (!title) return alert("填个标题");
  const { id } = await api("/api/projects", { json: { title, mode: "full" } });
  await loadProjects();
  await selectProject(id);
});
guard($("#scriptBtn"), async () => {
  if (!needProject()) return;
  const title = $("#newTitle").value.trim();
  await runJob("写脚本", api(`/api/projects/${state.pid}/script`, { json: { brief: title ? { title } : null } }));
});
guard($("#boardBtn"), async () => {
  if (!needProject()) return;
  await runJob("画分镜", api(`/api/projects/${state.pid}/storyboard`, { method: "POST" }));
});
$("#aspectSel").addEventListener("change", renderBoard);

function renderScript(s) {
  const b = s.best || {};
  return `<div class="card"><h2>${esc(b.title)}${mockTag(b)}</h2>
    <p>${esc(b.logline)} · ${esc(b.duration_s)}s · ${esc(b.platform_format)}</p>
    ${(b.beats || []).map((x) => `<div class="beat"><span class="sec">${esc(x.id)} ${esc(x.section)}</span>${esc(x.summary)}
      <span class="hint">（${esc(x.duration_s)}s · ${esc((x.cast || []).join("、"))}）</span>
      ${(x.key_lines || []).map((l) => `<div class="line">「${esc(l)}」</div>`).join("")}
      ${x.baby_capture ? `<div class="capture">🎯 宝宝捕捉：希望 ${esc(x.baby_capture.hope)}；诱导 ${esc(x.baby_capture.lure)}；拍不到就 ${esc(x.baby_capture.fallback)}</div>` : ""}
    </div>`).join("")}
    <h3>标题备选</h3><ul>${(b.title_options || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
    <p class="hint">封面：${esc(b.cover_idea)}</p></div>${loopHtml(s, "脚本")}`;
}

async function renderBoard() {
  const out = $("#boardOut");
  if (!state.project?.storyboard) { out.innerHTML = ""; return; }
  const aspect = $("#aspectSel").value;
  const cards = await api(`/api/projects/${state.pid}/storyboard/svg${aspect ? `?aspect=${encodeURIComponent(aspect)}` : ""}`);
  out.innerHTML = `<div style="width:100%">${loopHtml(state.project.storyboard, "分镜")}</div>` +
    cards.map((c) => `<div class="shot">${c.svg}</div>`).join("");
}

// ---------------- ③ shot list ----------------
function renderShoot(sl) {
  if (!sl) return `<div class="card hint">先在②生成分镜，这里会自动排出拍摄顺序。</div>`;
  const cam = { pov: "POV", tripod: "三脚架", handheld: "手持" };
  return `<div class="card"><h2>拍摄清单（按“少挪机位、宝宝状态优先”排序）</h2>
    <p class="hint">宝宝状态好的时段：${esc(JSON.stringify(sl.baby_schedule_hint || "按实际"))}</p>
    ${sl.blocks.map((bl) => `<h3>${esc(bl.block)}</h3>${bl.steps.map((s) => s.type === "setup"
      ? `<div class="step-setup">${esc(s.text)}</div>`
      : `<div class="step-shot"><input type="checkbox"><b>${esc(s.shot_id)} ${esc(cam[s.camera] || s.camera)}</b>
         <div>${esc(s.action)}${s.line ? ` <span class="line" style="color:#1f6feb">「${esc(s.line)}」</span>` : ""}
         <div class="slate">🎬 ${esc(s.slate)}</div><div class="${s.capture ? "capture" : "hint"}">${esc(s.tip)}</div>
         ${s.notes ? `<div class="hint">${esc(s.notes)}</div>` : ""}</div></div>`).join("")}`).join("")}
  </div>
  <div class="card"><h3>👶 安全</h3><ul>${sl.safety.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <h3>🔒 隐私检查</h3><ul>${sl.privacy_checklist.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <h3>🎒 器材</h3><ul>${sl.gear_checklist.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`;
}

// ---------------- ④ footage + edit ----------------
guard($("#uploadBtn"), async () => {
  if (!needProject()) return;
  const fs = $("#footageFiles").files;
  if (!fs.length) return alert("选择视频文件");
  const fd = new FormData();
  [...fs].forEach((f) => fd.append("files", f));
  $("#footageList").textContent = "上传中…";
  await api(`/api/projects/${state.pid}/footage/upload`, { method: "POST", body: fd });
  await refresh();
});
guard($("#folderBtn"), async () => {
  if (!needProject()) return;
  await api(`/api/projects/${state.pid}/footage/folder`, { json: { folder: $("#folderPath").value.trim() } });
  await refresh();
});
guard($("#analyzeFootageBtn"), async () => {
  if (!needProject()) return;
  await runJob("分析素材", api(`/api/projects/${state.pid}/footage/analyze`, { method: "POST" }));
});
guard($("#optionsBtn"), async () => {
  if (!needProject()) return;
  await runJob("剪辑方案", api(`/api/projects/${state.pid}/edit/options`, { json: { intent: $("#intent").value } }));
});
guard($("#directBtn"), async () => {
  if (!needProject()) return;
  await runJob("一键直剪", api(`/api/projects/${state.pid}/footage-direct`, { json: { intent: $("#intent").value } }));
  showTab("review");
});
$("#optionsOut").addEventListener("click", async (e) => {
  const id = e.target.dataset.opt;
  if (!id) return;
  e.target.disabled = true;
  try {
    const bgm = $("#bgmPath").value.trim() || null;
    await runJob(`按方案 ${id} 剪辑`, api(`/api/projects/${state.pid}/edit/cut`, { json: { option_id: id, bgm } }));
    showTab("review");
  } finally { e.target.disabled = false; }
});

function renderFootage(f) {
  if (!f) return "";
  return `<div class="card"><h2>素材理解（${f.clips.length} 段）</h2>
    ${(f.sync_groups || []).length ? `<p class="hint">🔗 双机位同步：${f.sync_groups.map((g) => esc(JSON.stringify(g))).join("；")}</p>` : ""}
    ${(f.errors || []).map((x) => `<p class="hint">⚠ ${esc(x.file)}：${esc(x.error)}</p>`).join("")}
    ${f.clips.map((c) => {
      const t = c.tags || {};
      const fr = c.frames?.[Math.floor((c.frames.length - 1) / 2)];
      return `<div class="clip">${fr ? `<img src="${fileUrl(fr.path)}">` : "<div></div>"}
        <div><b>${esc(c.clip_id)}</b> ${esc(c.file)} · ${esc(c.info?.duration?.toFixed?.(1))}s · ${esc(t.camera)}${mockTag(t)}
        ${c.slate ? ` · 场记：${esc(c.slate.shot_id || JSON.stringify(c.slate))}` : ""}
        <div class="hint">${esc(t.summary)}</div>
        <div>${(t.moments || []).map((m) => `⭐ ${m.start}-${m.end}s ${esc(m.label)}`).join("<br>")}</div>
        ${(t.bad_ranges || []).length ? `<div class="hint">废片段：${t.bad_ranges.map((b) => `${b.start}-${b.end}s ${esc(b.why)}`).join("；")}</div>` : ""}
        ${(t.privacy_flags || []).length ? `<div class="capture">🔒 隐私：${t.privacy_flags.map((p) => esc(p.what || JSON.stringify(p))).join("；")}</div>` : ""}
        <div class="hint">语音段 ${c.speech_ranges?.length || 0} 个（${esc(c.transcript_engine)}${c.transcript_mock ? "·演示" : ""}）</div></div></div>`;
    }).join("")}</div>`;
}

function renderOptions(o) {
  if (!o) return "";
  return `<div class="card"><h2>剪辑方案</h2><div class="opts">${o.options.map((x, i) =>
    `<div class="opt"><b>${esc(x.id)}. ${esc(x.name)}</b>${i === 0 ? " ⭐推荐" : ""}<p>${esc(x.style)} · ${esc(x.duration_s?.toFixed?.(0) ?? x.duration_s)}s · ${esc(x.aspect)}</p>
      <p class="hint">结构：${esc((x.structure || []).join(" → "))}</p>
      <div>${(x.techniques || []).map((t) => `<span class="tech">${esc(t)}</span>`).join("")}</div>
      <p class="hint">${esc(x.why)}</p><button data-opt="${esc(x.id)}">按这个剪 →</button></div>`).join("")}</div></div>`;
}

// ---------------- ⑤ review ----------------
function renderReview(cut, tl) {
  if (!cut) return `<div class="card hint">剪辑完成后，成片、审片意见和每轮评分会显示在这里。</div>`;
  const fin = cut.final || {};
  const best = cut.best || tl || {};
  return `<div class="card"><h2>成片${mockTag(best)}</h2>
    <video controls src="${fileUrl(fin.video)}"></video>
    <p><a href="${fileUrl(fin.video)}" download>下载 MP4</a> · <a href="${fileUrl(fin.srt)}" download>字幕 SRT</a> · <a href="${fileUrl(fin.ass)}" download>字幕 ASS</a></p>
    ${(fin.covers || []).map((c) => `<img src="${fileUrl(c)}" style="max-width:320px;border-radius:6px">`).join("")}
    <h3>标题备选</h3><ul>${(best.title_options || []).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
    <p class="hint">BGM 情绪：${esc(best.bgm_mood)} · ${esc(best.notes)}</p>
    <h3>时间线（${esc(best.duration_s)}s）</h3>
    ${(best.segments || []).map((s, i) => `<div class="seg">${String(i + 1).padStart(2, "0")} ${esc(s.clip)} ${(+s.in).toFixed(2)}→${(+s.out).toFixed(2)}
      ${s.zoom && s.zoom !== 1 ? `zoom${s.zoom}` : ""} ${s.speed && s.speed !== 1 ? `×${s.speed}` : ""} [${esc((s.techniques || []).join(","))}] ${esc(s.purpose)} ${s.caption ? `「${esc(s.caption)}」` : ""}</div>`).join("")}
  </div>${loopHtml(cut, "审片")}`;
}

// ---------------- render all ----------------
function renderAll() {
  const p = state.project || {};
  $("#topicsOut").innerHTML = (p.analysis ? renderAnalysis(p.analysis) : "") + (p.topics ? renderTopics(p.topics) : "");
  $("#scriptOut").innerHTML = p.script ? renderScript(p.script) : "";
  renderBoard().catch(console.error);
  $("#shootOut").innerHTML = renderShoot(p.shotlist);
  const fl = p.meta?.footage || [];
  $("#footageList").textContent = fl.length ? `已导入 ${fl.length} 段：${fl.map((x) => x.split(/[\\/]/).pop()).join("、")}` : "";
  $("#footageOut").innerHTML = renderFootage(p.footage);
  $("#optionsOut").innerHTML = renderOptions(p.edit_options);
  $("#cutOut").innerHTML = "";
  $("#reviewOut").innerHTML = renderReview(p.cut, p.timeline);
}

// ---------------- settings / status ----------------
guard($("#saveCast"), async () => {
  let cast;
  try { cast = JSON.parse($("#castJson").value); } catch (e) { return alert("JSON 格式错误：" + e.message); }
  await api("/api/cast", { method: "PUT", json: cast });
  alert("已保存");
});
$("#retroForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!needProject()) return;
  const body = {};
  new FormData(e.target).forEach((v, k) => { if (v !== "") body[k] = ["views", "likes", "favorites"].includes(k) ? +v : k === "completion_rate" ? parseFloat(v) : v; });
  await api(`/api/projects/${state.pid}/retro`, { json: body });
  alert("已记录，后续选题分析会参考这次的实际数据");
});

async function init() {
  const st = await api("/api/status");
  const b = $("#status");
  b.textContent = st.mock_llm ? "演示模式（未配置 DeepSeek Key）" : `DeepSeek · ${st.model}`;
  b.className = "badge " + (st.mock_llm ? "mock" : "live");
  if (!st.ffmpeg) b.textContent += " · ⚠ 未找到 ffmpeg";
  $("#statusJson").textContent = JSON.stringify(st, null, 2);
  $("#castJson").value = JSON.stringify(await api("/api/cast"), null, 2);
  await loadProjects();
  if (state.pid) await selectProject(state.pid);
  if (qs.get("tab")) showTab(qs.get("tab"));
}
init().catch((e) => { $("#status").textContent = "后端未启动：" + e.message; });
