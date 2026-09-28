'use strict';
const $ = s => document.querySelector(s);
const state = { items: [], running: 0, paused: false, filter: 'all', query: '' };
const SUPPORTED = /\.(jpe?g|png|webp|heic|heif|bmp|gif|tiff?|pdf|docx|txt|md|csv|tsv|json|srt|vtt|ass|html?|xml|log|zip)$/i;

async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  return r.json();
}

function today() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}
$('#outDir').value = `~/Desktop/小语种检查结果_${today()}`;

async function pollEngine() {
  try {
    const r = await (await fetch('/api/health')).json();
    const el = $('#engine');
    if (r.error) { el.textContent = r.error; el.className = 'engine bad'; return; }
    if (r.ready) {
      el.textContent = `引擎就绪 · ${r.workers} 路并行` + (r.warnings?.length ? '（部分语言模型未加载，准确率可能下降）' : '');
      el.title = (r.warnings || []).join('\n');
      el.className = 'engine ok';
      return;
    }
  } catch (e) { $('#engine').textContent = '服务未连接，请用“启动小语种检查.command”打开'; $('#engine').className = 'engine bad'; }
  setTimeout(pollEngine, 1000);
}
pollEngine();

function addEntries(files) {
  for (const f of files) {
    state.items.push({ id: f.id, name: f.name, rel: f.rel || f.name, status: 'queued', res: null, manual: null });
  }
  render(); pump();
}

async function uploadFiles(list) {
  const files = [...list].filter(x => SUPPORTED.test(x.file.name));
  if (!files.length) { alert('没有可识别的文件（支持图片 / PDF / Word / 文本 / zip）'); return; }
  let i = 0;
  const worker = async () => {
    while (i < files.length) {
      const { file, rel } = files[i++];
      try {
        const r = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}&rel=${encodeURIComponent(rel || file.name)}`, { method: 'POST', body: file });
        const j = await r.json();
        if (j.files) addEntries(j.files);
      } catch (e) { console.error(e); }
    }
  };
  await Promise.all([worker(), worker(), worker()]);
}

function readEntry(entry, prefix, out) {
  return new Promise(resolve => {
    if (entry.isFile) {
      entry.file(f => { out.push({ file: f, rel: prefix + f.name }); resolve(); }, () => resolve());
    } else if (entry.isDirectory) {
      const reader = entry.createReader(), all = [];
      const next = () => reader.readEntries(async batch => {
        if (!batch.length) {
          for (const e of all) if (!e.name.startsWith('.')) await readEntry(e, prefix + entry.name + '/', out);
          resolve();
        } else { all.push(...batch); next(); }
      }, () => resolve());
      next();
    } else resolve();
  });
}

const drop = $('#drop');
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('hover'); }));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('hover'); }));
document.addEventListener('dragover', e => e.preventDefault());
document.addEventListener('drop', e => e.preventDefault());
drop.addEventListener('drop', async e => {
  const entries = [...e.dataTransfer.items].map(it => it.webkitGetAsEntry && it.webkitGetAsEntry()).filter(Boolean);
  const out = [];
  if (entries.length) { for (const en of entries) await readEntry(en, '', out); }
  else for (const f of e.dataTransfer.files) out.push({ file: f, rel: f.name });
  uploadFiles(out);
});
$('#pickFiles').addEventListener('change', e => { uploadFiles([...e.target.files].map(f => ({ file: f, rel: f.name }))); e.target.value = ''; });
$('#pickDir').addEventListener('change', e => { uploadFiles([...e.target.files].map(f => ({ file: f, rel: f.webkitRelativePath || f.name }))); e.target.value = ''; });
$('#scanPath').addEventListener('click', async () => {
  const p = $('#pathInput').value.trim();
  if (!p) return;
  $('#scanPath').disabled = true;
  const r = await api('/api/list', { path: p });
  $('#scanPath').disabled = false;
  if (r.error) return alert(r.error);
  if (!r.files.length) return alert('该路径下没有可识别的文件');
  addEntries(r.files);
});

function finalOf(it) {
  if (it.status === 'skipped' || it.status === 'error') return null;
  if (it.manual) return it.manual;
  if (!it.res || it.res.error) return null;
  return it.res.verdict === '小语种' ? (it.res.level === '确定' ? 'sure' : 'suspect') : 'none';
}

async function pump() {
  const conc = Math.max(1, Math.min(6, +$('#conc').value || 3));
  while (!state.paused && state.running < conc) {
    const it = state.items.find(x => x.status === 'queued');
    if (!it) break;
    it.status = 'running'; state.running++; updateCard(it);
    api('/api/analyze', { id: it.id, level: it.level ?? +$('#level').value, sens: $('#sens').value, earlyStop: $('#earlyStop').checked })
      .then(res => { it.res = res; it.status = res.skipped ? 'skipped' : res.error ? 'error' : 'done'; })
      .catch(e => { it.res = { error: String(e) }; it.status = 'error'; })
      .finally(() => { state.running--; updateCard(it); stats(); pump(); });
  }
  stats();
  if (!state.running && !state.items.some(x => x.status === 'queued')) showSkipNotice();
}

function showSkipNotice() {
  const sk = state.items.filter(x => x.status === 'skipped' || x.status === 'error');
  const box = $('#skipNotice');
  if (!sk.length) { box.hidden = true; return; }
  const list = sk.map(x => `${x.rel}　—　${x.res?.reason || x.res?.error || '未知原因'}`);
  box.innerHTML = `<b>识别完成，有 ${sk.length} 个文件无法读取，已跳过：</b><button class="btn ghost" id="copySkip">复制清单</button><button class="btn ghost" id="showSkip">只看这些</button>` +
    `<ul>${list.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`;
  box.hidden = false;
  $('#copySkip').onclick = () => { navigator.clipboard.writeText(list.join('\n')); $('#copySkip').textContent = '已复制'; };
  $('#showSkip').onclick = () => document.querySelector('#tabs button[data-f="error"]').click();
}

function stats() {
  const n = state.items.length, done = state.items.filter(x => ['done', 'error', 'skipped'].includes(x.status)).length;
  const c = { sure: 0, suspect: 0, none: 0 };
  state.items.forEach(x => { const f = finalOf(x); if (f) c[f]++; });
  const err = state.items.filter(x => x.status === 'error' || x.status === 'skipped').length;
  $('#progBar').style.width = n ? (done / n * 100) + '%' : 0;
  $('#stats').innerHTML = `共 <b>${n}</b> · 已完成 <b>${done}</b> · <span class="r">小语种确定 <b>${c.sure}</b></span> · <span class="o">疑似 <b>${c.suspect}</b></span> · 非小语种 <b>${c.none}</b>` + (err ? ` · 无法读取 <b>${err}</b>` : '');
}

const cardEls = new Map();
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

function matches(it) {
  const f = finalOf(it);
  const ok = { all: true, minor: f === 'sure' || f === 'suspect', sure: f === 'sure', suspect: f === 'suspect', none: f === 'none', error: it.status === 'error' || it.status === 'skipped' }[state.filter];
  if (!ok) return false;
  if (!state.query) return true;
  const hay = (it.rel + ' ' + (it.res?.note || '') + ' ' + (it.res?.items || []).map(x => x.text).join(' ')).toLowerCase();
  return hay.includes(state.query.toLowerCase());
}

function cardHTML(it) {
  const f = finalOf(it);
  const badge = it.status === 'queued' ? ['', '排队中'] : it.status === 'running' ? ['run', '识别中…'] : it.status === 'error' || it.status === 'skipped' ? ['err', '无法读取'] :
    ({ sure: ['minor', '小语种'], suspect: ['suspect', '疑似小语种'], none: ['none', '非小语种'] }[f]);
  const langs = it.res?.langs?.map(l => l.name).join('、') || '';
  const extra = it.res?.present?.length ? `含${it.res.present.join('、')}` : '';
  const note = it.status === 'skipped' ? '已跳过：' + (it.res?.reason || '') : it.status === 'error' ? it.res?.error : (it.res?.note || '');
  const isImg = /\.(jpe?g|png|webp|heic|heif|bmp|gif|tiff?|pdf)$/i.test(it.name);
  const passes = it.res?.passes?.length ? ` · ${it.res.passes.join('+')} · ${(it.res.ms / 1000).toFixed(1)}s` : '';
  return `<div class="thumb" data-open="${it.id}" ${isImg ? `style="background-image:url('/api/preview?id=${it.id}')"` : ''}>${isImg ? '' : esc(it.name.split('.').pop().toUpperCase()) + ' 文件'}</div>
    <span class="badge ${badge[0]}">${badge[1]}</span>${it.manual ? '<span class="manual">人工</span>' : ''}
    <div class="meta"><div class="langs">${esc(langs || extra)}</div><div class="note" title="${esc(note)}">${esc(note)}</div>
    <div class="fname">${esc(it.rel)}${passes}</div></div>
    <div class="card-actions"><button data-mark="sure" data-id="${it.id}">标为小语种</button><button data-mark="none" data-id="${it.id}">标为非小语种</button></div>`;
}

function updateCard(it) {
  let el = cardEls.get(it.id);
  if (!el) return;
  const f = finalOf(it);
  el.className = 'card' + (f === 'sure' ? ' minor' : f === 'suspect' ? ' suspect' : '');
  el.innerHTML = cardHTML(it);
  el.style.display = matches(it) ? '' : 'none';
}

function render() {
  const grid = $('#grid');
  for (const it of state.items) {
    if (!cardEls.has(it.id)) {
      const el = document.createElement('div');
      el.dataset.id = it.id;
      cardEls.set(it.id, el);
      grid.appendChild(el);
    }
    updateCard(it);
  }
  stats();
}

$('#tabs').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  document.querySelectorAll('#tabs button').forEach(x => x.classList.toggle('on', x === b));
  state.filter = b.dataset.f; render();
});
$('#search').addEventListener('input', e => { state.query = e.target.value.trim(); render(); });
$('#stop').addEventListener('click', () => { state.paused = !state.paused; $('#stop').textContent = state.paused ? '继续' : '暂停'; pump(); });
$('#clear').addEventListener('click', () => {
  if (state.running) return alert('正在识别，请先暂停并等待当前文件完成');
  state.items = []; cardEls.clear(); $('#grid').innerHTML = ''; stats();
});
$('#rescan').addEventListener('click', () => {
  const targets = state.items.filter(x => x.status === 'done' && finalOf(x) === 'none' && !x.manual && /\.(jpe?g|png|webp|heic|heif|bmp|gif|tiff?|pdf)$/i.test(x.name));
  if (!targets.length) return alert('没有需要重扫的非小语种图片');
  targets.forEach(x => { x.status = 'queued'; x.level = 3; updateCard(x); });
  pump();
});

$('#grid').addEventListener('click', e => {
  const mk = e.target.closest('[data-mark]');
  if (mk) {
    const it = state.items.find(x => x.id === mk.dataset.id);
    const auto = finalOf({ ...it, manual: null });
    const want = mk.dataset.mark;
    it.manual = it.manual === want || auto === want ? null : want;
    updateCard(it); stats(); return;
  }
  const op = e.target.closest('[data-open]');
  if (op) openModal(state.items.find(x => x.id === op.dataset.open));
});

function openModal(it) {
  if (!it) return;
  const res = it.res || {};
  const isImg = /\.(jpe?g|png|webp|heic|heif|bmp|gif|tiff?)$/i.test(it.name);
  const img = $('#mImg'), svg = $('#mSvg');
  svg.innerHTML = '';
  img.style.display = isImg || /\.pdf$/i.test(it.name) ? '' : 'none';
  img.src = isImg || /\.pdf$/i.test(it.name) ? `/api/preview?id=${it.id}` : '';
  const hitKey = new Map((res.marks || []).map(m => [m.text, m.level]));
  img.onload = () => {
    svg.setAttribute('viewBox', '0 0 1000 1000'); svg.setAttribute('preserveAspectRatio', 'none');
    svg.innerHTML = (res.items || []).filter(x => x.box && !x.page).map((x, i) => {
      const lv = hitKey.get(x.text);
      const color = lv === 'strong' ? '#ff2d2d' : lv === 'weak' ? '#ffa200' : '#4da3ff';
      const [bx, by, bw, bh] = x.box.map(v => v * 1000);
      return `<rect data-i="${i}" x="${bx - 2}" y="${by - 2}" width="${bw + 4}" height="${bh + 4}" fill="none" stroke="${color}" stroke-width="${lv ? 3 : 1.5}" vector-effect="non-scaling-stroke"/>`;
    }).join('');
  };
  const f = finalOf(it);
  const lines = (res.items || []).map((x, i) => {
    const lv = hitKey.get(x.text);
    return `<li data-i="${i}" class="${lv ? 'hit-' + lv : ''}">${esc(x.text)}<span class="tag">${x.conf != null ? Math.round(x.conf * 100) + '%' : ''}${x.pass ? ' ' + x.pass : ''}</span></li>`;
  }).join('');
  $('#mInfo').innerHTML = `<h3>${esc(it.rel)}</h3>
    <p><b>${{ sure: '小语种（确定）', suspect: '小语种（疑似）', none: '非小语种' }[f] || it.status}</b>${it.manual ? '（人工）' : ''}</p>
    <p>${esc(res.note || res.error || '')}</p>
    ${(res.langs || []).map(l => `<div>• ${esc(l.name)} <span class="tag">${l.level === 'strong' ? '确定' : '疑似'} ${l.score}</span></div>`).join('')}
    <p style="color:#6b7280;font-size:12px">红框 = 确定命中，橙框 = 疑似，蓝框 = 其他文字。识别轮次：${esc((res.passes || []).join(' + '))}</p>
    <ul class="lines">${lines || '<li>未识别到文字</li>'}</ul>`;
  $('#modal').hidden = false;
}
$('#mClose').addEventListener('click', () => { $('#modal').hidden = true; });
$('#modal').addEventListener('click', e => { if (e.target.id === 'modal') $('#modal').hidden = true; });
document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#modal').hidden = true; });
$('#mInfo').addEventListener('mouseover', e => {
  const li = e.target.closest('li[data-i]');
  document.querySelectorAll('#mSvg rect').forEach(r => r.style.strokeWidth = r.dataset.i === li?.dataset.i ? '6' : '');
});

function exportItems() {
  const skippedItems = state.items.filter(x => x.status === 'skipped' || x.status === 'error').map(x => ({ id: x.id, name: x.name,
    verdict: '无法读取', level: '', langNames: [], note: '无法读取，已跳过：' + (x.res?.reason || x.res?.error || ''), reason: x.res?.reason || x.res?.error || '', manual: false, marks: [] }));
  return skippedItems.concat(state.items.filter(x => x.status === 'done').map(x => {
    const f = finalOf(x);
    const r = x.res || {};
    let langNames = (r.langs || []).map(l => l.name);
    let note = r.note || '';
    if (x.manual === 'sure' && !langNames.length) { langNames = ['小语种']; note = '人工标记为小语种'; }
    if (x.manual === 'none') note = '人工标记为非小语种；' + note;
    return { id: x.id, name: x.name, verdict: f === 'none' ? '非小语种' : '小语种', level: f === 'sure' ? '确定' : f === 'suspect' ? '疑似' : '',
      langNames, note, manual: !!x.manual, marks: r.marks || [] };
  }));
}

$('#doExport').addEventListener('click', async () => {
  const items = exportItems();
  if (!items.some(x => x.verdict !== '无法读取')) return alert('还没有识别完成的文件');
  if (state.running && !confirm('还有文件在识别中，只导出已完成的部分？')) return;
  $('#exportMsg').textContent = '导出中…';
  const r = await api('/api/export', { outDir: $('#outDir').value, mode: $('#mode').value, splitSuspect: $('#optSplit').checked,
    rename: $('#optRename').checked, annotate: $('#optAnnot').checked, includeOthers: $('#optOthers').checked, items });
  if (r.error) { $('#exportMsg').textContent = '导出失败：' + r.error; return; }
  $('#exportMsg').innerHTML = `已导出 ${r.exported} 个文件（小语种 ${r.minor} 个）到 ${esc(r.outDir)} <a id="reveal">打开文件夹</a>` +
    (r.unreadable ? `<br>另有 ${r.unreadable} 个文件无法读取，已跳过，清单见“无法读取的文件.txt”` : '') +
    (r.errors.length ? `<br>导出失败 ${r.errors.length} 个：${esc(r.errors.slice(0, 5).join('；'))}` : '');
  $('#reveal').onclick = () => api('/api/reveal', { path: r.outDir + '/小语种' });
});

$('#dlCsv').addEventListener('click', () => {
  const rows = [['文件', '判定', '置信', '语种', '备注', '人工修改']];
  exportItems().forEach(x => rows.push([state.items.find(i => i.id === x.id).rel, x.verdict, x.level, x.langNames.join('、'), x.note, x.manual ? '是' : '']));
  const csv = '\ufeff' + rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `小语种检查报告_${today()}.csv`; a.click();
});
