(() => {
  const etfSelect = document.querySelector('#history-etf');
  const metricSelect = document.querySelector('#history-metric');
  const dateInput = document.querySelector('#history-date');
  const status = document.querySelector('#history-status');
  const detail = document.querySelector('#history-detail');
  const canvas = document.querySelector('#history-chart');
  const ctx = canvas.getContext('2d');
  const formatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 });
  const padding = { left: 60, right: 12, top: 18, bottom: 30 };
  let etfs = new Map();

  function draw(etf) {
    if (!ctx || !etf) return;
    const rows = etf.daily;
    const key = metricSelect.value;
    const values = rows.map(row => row[key]).filter(Number.isFinite);
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillStyle = '#46566a';
    if (!values.length) {
      ctx.fillText('所选指标暂无历史数据', 12, 28);
      return;
    }

    const low = values.reduce((a, b) => Math.min(a, b));
    const high = values.reduce((a, b) => Math.max(a, b));
    const chartWidth = Math.max(1, width - padding.left - padding.right);
    const chartHeight = height - padding.top - padding.bottom;
    const x = index => padding.left + chartWidth * index / Math.max(1, rows.length - 1);
    const y = value => padding.top + chartHeight * (high === low ? .5 : (high - value) / (high - low));
    for (let tick = 0; tick <= 4; tick++) {
      const lineY = padding.top + chartHeight * tick / 4;
      ctx.strokeStyle = '#e1e8f0';
      ctx.beginPath();
      ctx.moveTo(padding.left, lineY);
      ctx.lineTo(width - padding.right, lineY);
      ctx.stroke();
      if (high !== low || tick === 2) ctx.fillText(formatter.format(high - (high - low) * tick / 4), 1, lineY + 4);
    }

    ctx.strokeStyle = '#164c91';
    ctx.lineWidth = 2;
    ctx.beginPath();
    let connected = false;
    rows.forEach((row, index) => {
      const value = row[key];
      if (Number.isFinite(value)) {
        if (connected) ctx.lineTo(x(index), y(value));
        else ctx.moveTo(x(index), y(value));
      }
      connected = Number.isFinite(value);
    });
    ctx.stroke();

    ctx.fillText(rows[0].date, padding.left, height - 8);
    ctx.textAlign = 'right';
    ctx.fillText(rows.at(-1).date, width - padding.right, height - 8);
    const chosen = rows.findIndex(row => row.date === dateInput.value);
    if (chosen >= 0 && Number.isFinite(rows[chosen][key])) {
      ctx.fillStyle = '#164c91';
      ctx.beginPath();
      ctx.arc(x(chosen), y(rows[chosen][key]), 4, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function showDate() {
    const etf = etfs.get(etfSelect.value);
    const day = etf?.daily.find(row => row.date === dateInput.value);
    const signal = etf?.history.find(row => row.date === dateInput.value);
    const value = day?.[metricSelect.value];
    const metric = metricSelect.selectedOptions[0].textContent;
    detail.textContent = day
      ? `${day.date} · ${metric} ${Number.isFinite(value) ? formatter.format(value) : '暂无'} · ${signal?.verdict ?? '暂无共振判定'}`
      : '所选日期没有日度记录';
    draw(etf);
  }

  function selectEtf() {
    const etf = etfs.get(etfSelect.value);
    dateInput.min = etf.daily[0].date;
    dateInput.max = etf.daily.at(-1).date;
    dateInput.value = dateInput.max;
    const shares = etf.daily.filter(row => Number.isFinite(row.shares_yi)).length;
    status.textContent = `${dateInput.min} 至 ${dateInput.max} · ${etf.daily.length} 条日度记录 · ${shares} 条有份额 · ${etf.history.length} 条共振记录`;
    showDate();
  }

  canvas.addEventListener('click', event => {
    const rows = etfs.get(etfSelect.value)?.daily;
    if (!rows?.length) return;
    const width = canvas.clientWidth - padding.left - padding.right;
    const offset = (event.clientX - canvas.getBoundingClientRect().left - padding.left) / Math.max(1, width);
    const index = Math.round(Math.max(0, Math.min(1, offset)) * (rows.length - 1));
    dateInput.value = rows[index].date;
    showDate();
  });
  etfSelect.addEventListener('change', selectEtf);
  metricSelect.addEventListener('change', showDate);
  dateInput.addEventListener('change', showDate);
  new ResizeObserver(() => draw(etfs.get(etfSelect.value))).observe(canvas);

  fetch('resonance.json')
    .then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then(data => {
      etfs = new Map(data.etfs.filter(etf => etf.daily.length).map(etf => [etf.code, etf]));
      if (!etfs.size) throw new Error('Empty history');
      etfSelect.replaceChildren(...Array.from(etfs.values(), etf => new Option(`${etf.code} ${etf.name}`, etf.code)));
      if (etfs.has('510300')) etfSelect.value = '510300';
      for (const control of [etfSelect, metricSelect, dateInput]) control.disabled = false;
      selectEtf();
    })
    .catch(() => { status.textContent = '历史图表加载失败，可直接查看 Agent 数据 JSON。'; });
})();
