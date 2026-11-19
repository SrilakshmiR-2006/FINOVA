/* Dashboard: stat cards, charts, calendar, day list, savings, finance score. */
(function () {
  const profile = window.__PROFILE__;
  const CATS = window.__CATEGORIES__;
  const $ = id => document.getElementById(id);
  const ICONS = {
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 7l10 10"/><path d="M17 7v10H7"/></svg>',
    piggy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 5c-1.5 0-2.8 1.4-3 2-3.5-1.5-11-.3-11 5 0 1.8 0 3 2 4.5V20h4v-2h3v2h4v-4c1-.5 1.7-1 2-2h2v-4h-2c0-1-.5-1.5-1-2V5z"/><path d="M2 9v1c0 1.1.9 2 2 2h1"/><path d="M16 11h.01"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5v14"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    l: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>',
    r: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  };
  const META = {
    income: { label: 'Income', icon: ICONS.up, tone: 'text-income', add: 'Add Income', title: 'Add Income', toast: 'Income' },
    expense: { label: 'Expenses', icon: ICONS.down, tone: 'text-expense', add: 'Add Expense', title: 'Add Expense', toast: 'Expense' },
    saving: { label: 'Savings', icon: ICONS.piggy, tone: 'text-saving', add: 'Add Savings', title: 'Add to Savings', toast: 'Savings' },
  };
  const PIE_COLORS = ['#5C1A1B', '#7EC8E3', '#D8C3A5', '#4A3B32', '#C65A55', '#4a87b0', '#a98a5a', '#2d5f7a', '#8a7a70', '#e6d8c0'];

  let txns = [];
  let selected = new Date();
  let calMonth = new Date(selected.getFullYear(), selected.getMonth(), 1);
  let range = 'month';
  let trendChart = null, pieChart = null;
  let dlgType = 'income';

  const now = new Date();
  const sameMonth = (iso, ref) => { const d = parseISODate(iso); return d.getFullYear() === ref.getFullYear() && d.getMonth() === ref.getMonth(); };
  const fmtLong = new Intl.DateTimeFormat('en-US', { weekday: 'long', month: 'long', day: 'numeric' });
  const fmtShort = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  $('today-label').textContent = fmtLong.format(now);
  $('first-name').textContent = (profile.full_name || '').split(' ')[0] || 'there';
  if (!profile.monthly_income) $('complete-profile').classList.remove('hidden');

  function byCategory(list, type) {
    const m = new Map();
    list.forEach(t => { if (t.type === type) m.set(t.category, (m.get(t.category) || 0) + t.amount); });
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }

  /* ---------- render ---------- */
  function render() {
    const todayIso = toISODate(now);
    const monthTxns = txns.filter(t => sameMonth(t.occurred_on, now));
    const all = totals(txns), month = totals(monthTxns), today = totals(txns.filter(t => t.occurred_on === todayIso));
    const goalPct = profile.savings_goal_pct || 20;
    const incomeBase = month.income > 0 ? month.income : profile.monthly_income;
    const goalAmount = incomeBase * goalPct / 100;
    const score = financeScore(month, goalPct);

    // balance card
    $('balance').textContent = formatMoney(all.income - all.expense - all.saving);
    $('all-saving').textContent = formatMoney(all.saving);
    $('m-income').textContent = formatMoney(month.income);
    $('m-expense').textContent = formatMoney(month.expense);
    $('m-saving').textContent = formatMoney(month.saving);

    renderScore(score, month.income > 0, goalPct);
    ['income', 'expense', 'saving'].forEach(t => renderStat(t, month[t], today[t], monthTxns));
    renderTrend();
    renderPie(byCategory(monthTxns, 'expense'));
    renderCalendar();
    renderDay();
    renderSavings(monthTxns, goalAmount, goalPct);
  }

  function renderScore(score, hasIncome, goalPct) {
    const r = 54, c = 2 * Math.PI * r, offset = c * (1 - score / 100);
    const tip = !hasIncome ? "Add this month's income to get your score."
      : score >= 80 ? "You're beating your savings goal. Keep it steady."
      : score >= 60 ? `Close to your ${goalPct}% goal — trim one category to get there.`
      : score >= 40 ? 'Spending is eating into savings. Review your top expense.'
      : 'Expenses are close to income. Start with a small savings transfer.';
    $('score-panel').innerHTML = `
      <div class="panel-head"><h2>Finance score</h2></div>
      <div class="score-wrap">
        <div class="score-ring">
          <svg viewBox="0 0 128 128">
            <defs><linearGradient id="scoreGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#7EC8E3"/><stop offset="100%" stop-color="#5C1A1B"/></linearGradient></defs>
            <circle cx="64" cy="64" r="${r}" fill="none" stroke="var(--muted)" stroke-width="12"/>
            <circle cx="64" cy="64" r="${r}" fill="none" stroke="url(#scoreGrad)" stroke-width="12" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${offset}" style="transition:stroke-dashoffset 1s ease"/>
          </svg>
          <div class="c"><span class="font-display text-maroon" style="font-size:2.25rem;font-weight:600">${hasIncome ? score : '—'}</span><span class="text-xs text-muted">out of 100</span></div>
        </div>
        <span class="score-badge">${hasIncome ? scoreLabel(score) : 'No data yet'}</span>
        <p class="text-sm text-muted mt-3" style="text-align:center">${tip}</p>
      </div>`;
  }

  function renderStat(type, monthVal, todayVal, monthTxns) {
    const m = META[type];
    const top = byCategory(monthTxns, type).slice(0, 3);
    $('stat-' + type).innerHTML = `
      <div class="row">
        <span class="ico ${type}">${m.icon}</span>
        <button class="btn btn-sm ${type === 'expense' ? '' : 'btn-outline'}" data-add="${type}">${ICONS.plus} ${m.add}</button>
      </div>
      <p class="lbl">${m.label} this month</p>
      <p class="val ${m.tone}">${formatMoney(monthVal)}</p>
      <p class="today">Today: ${formatMoney(todayVal)}</p>
      ${top.length ? `<div class="tags">${top.map(([c, v]) => `<span>${escapeHtml(c)} · ${formatMoneyShort(v)}</span>`).join('')}</div>` : ''}`;
  }

  function renderTrend() {
    const ctx = $('trend').getContext('2d');
    if (trendChart) trendChart.destroy();
    const css = getComputedStyle(document.documentElement);
    const grid = css.getPropertyValue('--border').trim(), tick = css.getPropertyValue('--muted-foreground').trim();
    const yTick = { color: tick, font: { size: 12 }, callback: v => formatMoneyShort(v) };
    const tooltip = { callbacks: { label: c => ` ${c.dataset.label ? c.dataset.label + ': ' : ''}${formatMoney(c.parsed.y)}` } };
    const base = {
      responsive: true, maintainAspectRatio: false,
      scales: { x: { grid: { display: false }, ticks: { color: tick, font: { size: 12 } }, border: { display: false } }, y: { grid: { color: grid, borderDash: [3, 3] }, ticks: yTick, border: { display: false }, beginAtZero: true } },
      plugins: { legend: { display: range !== 'today', labels: { boxWidth: 10, font: { size: 12 } } }, tooltip },
    };
    if (range === 'today') {
      const iso = toISODate(now), t = { income: 0, expense: 0, saving: 0 };
      txns.forEach(x => { if (x.occurred_on === iso) t[x.type] += x.amount; });
      trendChart = new Chart(ctx, { type: 'bar', data: { labels: ['Income', 'Expense', 'Savings'], datasets: [{ data: [t.income, t.expense, t.saving], backgroundColor: ['#4a87b0', '#5C1A1B', '#7EC8E3'], borderRadius: 8, maxBarThickness: 72 }] }, options: base });
    } else if (range === 'month') {
      const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
      const inc = Array(days).fill(0), exp = Array(days).fill(0);
      txns.forEach(x => { const d = parseISODate(x.occurred_on); if (sameMonth(x.occurred_on, now) && x.type !== 'saving') (x.type === 'income' ? inc : exp)[d.getDate() - 1] += x.amount; });
      const g1 = ctx.createLinearGradient(0, 0, 0, 280); g1.addColorStop(0, 'rgba(126,200,227,.6)'); g1.addColorStop(1, 'rgba(126,200,227,0)');
      const g2 = ctx.createLinearGradient(0, 0, 0, 280); g2.addColorStop(0, 'rgba(92,26,27,.4)'); g2.addColorStop(1, 'rgba(92,26,27,0)');
      base.scales.x.ticks.autoSkip = true; base.scales.x.ticks.maxTicksLimit = 11;
      base.plugins.tooltip = { callbacks: { title: i => 'Day ' + i[0].label, label: c => ` ${c.dataset.label}: ${formatMoney(c.parsed.y)}` } };
      trendChart = new Chart(ctx, { type: 'line', data: { labels: Array.from({ length: days }, (_, i) => String(i + 1)), datasets: [
        { label: 'Income', data: inc, borderColor: '#4a87b0', backgroundColor: g1, fill: true, tension: .35, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 },
        { label: 'Expense', data: exp, borderColor: '#5C1A1B', backgroundColor: g2, fill: true, tension: .35, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4 }] }, options: base });
    } else {
      const map = new Map();
      [...txns].reverse().forEach(x => {
        if (x.type === 'saving') return;
        const k = x.occurred_on.slice(0, 7);
        if (!map.has(k)) map.set(k, { name: new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit' }).format(parseISODate(k + '-01')).replace(' ', ' '), income: 0, expense: 0 });
        map.get(k)[x.type] += x.amount;
      });
      const rows = [...map.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(e => e[1]);
      trendChart = new Chart(ctx, { type: 'bar', data: { labels: rows.map(r => r.name), datasets: [
        { label: 'Income', data: rows.map(r => r.income), backgroundColor: '#7EC8E3', borderRadius: 6, maxBarThickness: 36 },
        { label: 'Expense', data: rows.map(r => r.expense), backgroundColor: '#5C1A1B', borderRadius: 6, maxBarThickness: 36 }] }, options: base });
    }
  }

  function renderPie(data) {
    const wrap = $('pie-wrap');
    if (pieChart) { pieChart.destroy(); pieChart = null; }
    if (!data.length) { wrap.innerHTML = '<div style="display:flex;height:15rem;align-items:center;justify-content:center" class="text-sm text-muted">No expenses this month yet.</div>'; return; }
    const total = data.reduce((s, d) => s + d[1], 0);
    wrap.innerHTML = `<div class="pie-grid">
      <div class="pie-box"><canvas id="pie"></canvas><div class="pie-center"><span class="text-xs text-muted">Total</span><span class="font-display text-maroon" style="font-size:1.25rem;font-weight:600">${formatMoneyShort(total)}</span></div></div>
      <ul class="legend">${data.map((d, i) => `<li><i style="background:${PIE_COLORS[i % PIE_COLORS.length]}"></i><span class="n text-ink">${escapeHtml(d[0])}</span><span class="tabular text-muted">${Math.round(d[1] / total * 100)}%</span></li>`).join('')}</ul></div>`;
    pieChart = new Chart($('pie').getContext('2d'), { type: 'doughnut', data: { labels: data.map(d => d[0]), datasets: [{ data: data.map(d => d[1]), backgroundColor: data.map((_, i) => PIE_COLORS[i % PIE_COLORS.length]), borderColor: '#fff', borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: '58%', plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${c.label}: ${formatMoney(c.parsed)}` } } } } });
  }

  function renderCalendar() {
    const active = new Set(txns.map(t => t.occurred_on));
    const y = calMonth.getFullYear(), m = calMonth.getMonth();
    const first = new Date(y, m, 1), startDow = first.getDay();
    const todayIso = toISODate(now), selIso = toISODate(selected);
    let cells = '';
    ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].forEach(d => cells += `<div class="dow">${d}</div>`);
    for (let i = 0; i < 42; i++) {
      const d = new Date(y, m, 1 - startDow + i), iso = toISODate(d);
      const cls = [d.getMonth() !== m ? 'out' : '', iso === todayIso ? 'today' : '', iso === selIso ? 'sel' : '', active.has(iso) ? 'act' : ''].join(' ').trim();
      cells += `<button type="button" class="${cls}" data-date="${iso}">${d.getDate()}</button>`;
      if (i % 7 === 6 && i >= 34 && new Date(y, m, 1 - startDow + i + 1).getMonth() !== m) break;
    }
    $('calendar').innerHTML = `<div class="cal-head"><button type="button" data-nav="-1" aria-label="Previous month">${ICONS.l}</button><span>${new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(calMonth)}</span><button type="button" data-nav="1" aria-label="Next month">${ICONS.r}</button></div><div class="cal-grid">${cells}</div>`;
  }

  function renderDay() {
    const iso = toISODate(selected), isToday = iso === toISODate(new Date());
    const list = txns.filter(t => t.occurred_on === iso);
    $('day-panel').innerHTML = `
      <div class="panel-head"><h2>${isToday ? "Today's transactions" : 'Transactions · ' + fmtShort.format(selected)}</h2><span class="text-xs text-muted" style="font-weight:600">${list.length} entries</span></div>
      ${list.length === 0 ? '<div class="empty-box"><p class="t">A blank page.</p><p class="text-sm text-muted mt-1">Nothing logged for this day yet.</p></div>'
        : `<ul class="txn-list">${list.map(t => `<li>
          <span class="ico ${t.type}">${META[t.type].icon}</span>
          <div class="mid"><p>${escapeHtml(t.category)}</p><p>${META[t.type].label}${t.note ? ' · ' + escapeHtml(t.note) : ''}</p></div>
          <span class="tabular ${META[t.type].tone}" style="font-weight:600">${t.type === 'income' ? '+' : '−'}${formatMoney(t.amount)}</span>
          <button class="icon-btn" data-del="${t.id}" aria-label="Delete transaction">${ICONS.trash}</button></li>`).join('')}</ul>`}`;
  }

  function renderSavings(monthTxns, goalAmount, goalPct) {
    const rows = byCategory(monthTxns, 'saving');
    const saved = rows.reduce((s, r) => s + r[1], 0);
    const pct = goalAmount > 0 ? Math.min(100, saved / goalAmount * 100) : 0;
    $('savings-panel').innerHTML = `
      <div class="panel-head"><h2>Savings this month</h2></div>
      <div class="savebox"><div class="r"><span class="font-display text-saving" style="font-size:1.5rem;font-weight:600">${formatMoney(saved)}</span><span class="text-xs text-muted">goal ${formatMoney(goalAmount)} (${goalPct}%)</span></div>
        <div class="bar"><i style="width:${pct}%"></i></div></div>
      ${rows.length === 0 ? '<p class="text-sm text-muted mt-4">No savings logged this month. Use "Add Savings" to start.</p>'
        : `<ul style="list-style:none;margin:1rem 0 0;padding:0;display:grid;gap:.75rem">${rows.map(([c, v]) => `<li><div style="display:flex;justify-content:space-between" class="text-sm"><span style="font-weight:500" class="text-ink">${escapeHtml(c)}</span><span class="tabular text-ink" style="font-weight:600">${formatMoney(v)}</span></div><div class="bar thin"><i style="width:${saved > 0 ? v / saved * 100 : 0}%"></i></div></li>`).join('')}</ul>`}`;
  }

  /* ---------- events ---------- */
  document.addEventListener('click', async e => {
    const add = e.target.closest('[data-add]');
    if (add) return openDialog(add.dataset.add);
    const del = e.target.closest('[data-del]');
    if (del) {
      try { await api('DELETE', '/api/transactions/' + del.dataset.del); toast('Transaction removed', 'success'); await load(); }
      catch (err) { toast(err.message, 'error'); }
      return;
    }
    const nav = e.target.closest('[data-nav]');
    if (nav) { calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() + Number(nav.dataset.nav), 1); return renderCalendar(); }
    const day = e.target.closest('[data-date]');
    if (day) { selected = parseISODate(day.dataset.date); calMonth = new Date(selected.getFullYear(), selected.getMonth(), 1); renderCalendar(); renderDay(); }
  });

  $('range-tabs').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    range = b.dataset.r;
    $('range-tabs').querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    renderTrend();
  });

  /* ---------- dialog ---------- */
  const overlay = $('txn-overlay');
  function openDialog(type) {
    dlgType = type;
    $('dlg-title').textContent = META[type].title;
    $('dlg-submit').textContent = META[type].title;
    $('t-cat').innerHTML = CATS[type].map(c => `<option>${escapeHtml(c)}</option>`).join('');
    $('t-date').value = toISODate(selected);
    $('t-amount').value = ''; $('t-note').value = '';
    overlay.classList.add('open');
    setTimeout(() => $('t-amount').focus(), 30);
  }
  const closeDialog = () => overlay.classList.remove('open');
  $('dlg-close').addEventListener('click', closeDialog);
  overlay.addEventListener('mousedown', e => { if (e.target === overlay) closeDialog(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDialog(); });

  $('txn-form').addEventListener('submit', async e => {
    e.preventDefault();
    const raw = $('t-amount').value, amount = Number(raw);
    if (raw === '') return toast('Enter an amount', 'error');
    if (!(amount > 0)) return toast('Amount must be above 0', 'error');
    if (amount > 1e9) return toast('Amount is too large', 'error');
    if (!$('t-date').value) return toast('Pick a date', 'error');
    const btn = $('dlg-submit'); btn.disabled = true; const label = btn.textContent; btn.textContent = 'Saving…';
    try {
      await api('POST', '/api/transactions', { type: dlgType, amount, category: $('t-cat').value, occurred_on: $('t-date').value, note: $('t-note').value.trim() });
      toast(META[dlgType].toast + ' added', 'success');
      closeDialog();
      await load();
    } catch (err) { toast(err.message, 'error'); }
    btn.disabled = false; btn.textContent = label;
  });

  async function load() { txns = await api('GET', '/api/transactions'); render(); }
  load().catch(err => toast(err.message, 'error'));
})();
