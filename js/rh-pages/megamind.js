import { api } from '../rh-api.js';

function statusPill(status) {
  const s = status || 'proposed';
  const cls = s === 'approved' ? 'rh-pill rh-pill--green'
    : s === 'rejected' ? 'rh-pill rh-pill--muted' : 'rh-pill';
  return `<span class="${cls}">${s}</span>`;
}

function walkforwardSection(wf) {
  if (!wf || !wf.ok) return '';
  const w = wf.window || {};
  const rows = (wf.leaderboard || []).slice(0, 8).map((r) => `<tr>
    <td>${r.rank}</td><td>${r.family}</td>
    <td>${r.selSharpe ?? '—'}</td>
    <td class="${(r.holdSharpe || 0) > 0 ? 'edge-pos' : 'edge-neg'}">${r.holdSharpe ?? '—'}</td>
    <td class="${(r.holdReturnPct || 0) >= 0 ? 'edge-pos' : 'edge-neg'}">${r.holdReturnPct != null ? r.holdReturnPct + '%' : '—'}</td>
  </tr>`).join('');
  return `
    <h3 class="rh-section-title">Historical walk-forward</h3>
    <section class="rh-card">
      <p class="rh-muted">Spawn genomes, <b>select</b> them on the first 60% of the out-of-sample year, then <b>judge</b> them on the held-out tail they never saw. ${w.selectionDays || 0}d selection · ${w.holdoutDays || 0}d holdout.</p>
      <p><b>${wf.topSelectionHeldUp || '—'}</b> of the top genomes stayed positive on the unseen holdout.</p>
      <div class="rh-card rh-card--warn" style="margin:10px 0"><p class="rh-card__label">Honest caveat</p><p class="rh-muted" style="font-size:12.5px">${wf.caveat || ''}</p></div>
      <table class="rh-table"><thead><tr><th>#</th><th>Family</th><th>Sel Sharpe</th><th>Holdout Sharpe</th><th>Holdout ret</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="5">No genomes scored.</td></tr>'}</tbody></table>
      <p class="rh-muted" style="font-size:12px">Top survivors are promoted into the 🏴‍☠️ Fleet to prove themselves on truly unseen forward data — the only real test.</p>
    </section>`;
}

export async function renderMegamind(main, route = {}) {
  main.innerHTML = '<div class="rh-loading">Hailing Treasure Droid…</div>';
  let data;
  try {
    data = await api.megamind();
  } catch (e) {
    main.innerHTML = `<section class="rh-card"><h2>🤖 Treasure Droid</h2>
      <p class="rh-muted">${e.message}. Run daily close or POST /api/megamind/tick.</p></section>`;
    return;
  }
  let wf = null;
  try { wf = await api.walkforward(); } catch (_) { wf = null; }

  const highlight = route.highlight || new URLSearchParams(location.hash.split('?')[1] || '').get('highlight');
  const recs = data.recommendations || [];

  const cards = recs.map((r) => {
    const hi = highlight === r.id ? ' arena-card--winner' : '';
    const canAct = r.status === 'proposed';
    return `<section class="rh-card${hi}" id="rec-${r.id}">
      <div class="rh-card__head">
        <h3 class="rh-card__subtitle">${r.area || 'general'} ${statusPill(r.status)}</h3>
        <span class="rh-pill">${r.priority || 'info'}</span>
      </div>
      <p><strong>Finding:</strong> ${r.finding || ''}</p>
      <p><strong>Action:</strong> ${r.action || ''}</p>
      <p class="rh-muted" style="font-size:12px">ID: ${r.id}</p>
      ${canAct ? `<div class="rh-row" style="margin-top:12px">
        <button type="button" class="rh-btn-primary" data-approve="${r.id}">Approve → launch in Cursor</button>
        <button type="button" class="rh-btn-secondary" data-reject="${r.id}">Dismiss</button>
      </div>` : ''}
      ${r.status === 'approved' ? `<p class="rh-muted">Active rule: <code>.cursor/rules/megamind-active-task.mdc</code> · Prompt: <code>data/intelligence/megamind/CURRENT_AGENT_PROMPT.md</code></p>
        <button type="button" class="rh-btn-secondary" data-done="${r.id}">Mark implemented</button>` : ''}
    </section>`;
  }).join('');

  main.innerHTML = `
    <section class="rh-card rh-card--accent arena-ultimate">
      <h2 class="rh-card__title">🤖 Treasure Droid <span style="font-weight:400;font-size:14px;opacity:0.7">— the captain</span></h2>
      <p class="rh-muted">Treasure Droid — mad scientist captain. Schemes over the historical lab, forward fleet, live IC, and arena. Recommends the next experiment (data pipeline, arena arm, genome kill/promote). <strong>Approve</strong> queues the build. Forward paper is the only proof — live capital stays gated.</p>
      <p class="rh-muted">Updated ${(data.generatedAt || '').slice(0, 19)} UTC · ${data.nPending ?? 0} pending · ${data.nApproved ?? 0} approved</p>
      <div class="rh-row">
        <button type="button" class="rh-btn-secondary" id="mm-tick">Refresh analysis</button>
        <a href="#/arena" class="rh-btn-secondary" style="text-decoration:none;display:inline-block;padding:10px 16px">← Arena</a>
      </div>
    </section>
    <section class="rh-card">
      <h3 class="rh-card__subtitle">Analysis</h3>
      <div class="arena-reasoning">${(data.narrative || '').slice(0, 4000)}</div>
    </section>
    ${walkforwardSection(wf)}
    <h3 class="rh-section-title">Recommendations</h3>
    ${cards || '<p class="rh-muted">No recommendations yet.</p>'}`;

  main.querySelector('#mm-tick')?.addEventListener('click', async () => {
    main.querySelector('#mm-tick').disabled = true;
    try {
      await api.megamindTick();
      await renderMegamind(main, route);
    } catch (err) {
      alert(err.message);
    }
    main.querySelector('#mm-tick').disabled = false;
  });

  main.querySelectorAll('[data-approve]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Approve this recommendation and queue it for Cursor Agent implementation?')) return;
      btn.disabled = true;
      try {
        const res = await api.megamindApprove(btn.dataset.approve);
        const hint = res.composerHint || 'Implement the Megamind active task (@megamind-active-task.mdc)';
        alert(`Approved.\n\n${hint}\n\nSDK: ${JSON.stringify(res.cursorLaunch?.sdk || res.cursorLaunch?.ide || {})}`);
        await renderMegamind(main, route);
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    });
  });

  main.querySelectorAll('[data-done]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await api.megamindImplemented(btn.dataset.done);
        await renderMegamind(main, route);
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    });
  });

  main.querySelectorAll('[data-reject]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        await api.megamindReject(btn.dataset.reject);
        await renderMegamind(main, route);
      } catch (err) {
        alert(err.message);
        btn.disabled = false;
      }
    });
  });

  if (highlight) {
    document.getElementById(`rec-${highlight}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
