// All D3 (v7) visualisations.
// Assumes d3 global loaded via CDN.

const VIZ = (() => {
  const LO = -2.5, HI = 2.5;

  // ── 1. Audience Scatter ─────────────────────────────────────────────────
  function buildScatter(selector) {
    const el = document.querySelector(selector);
    const W = el.clientWidth || 360, H = 220;
    const M = { top: 15, right: 15, bottom: 40, left: 45 };
    const iW = W - M.left - M.right, iH = H - M.top - M.bottom;

    const svg = d3.select(selector).append("svg")
      .attr("width", W).attr("height", H);
    const g = svg.append("g").attr("transform", `translate(${M.left},${M.top})`);

    const xScale = d3.scaleLinear().domain([LO, HI]).range([0, iW]);
    const yScale = d3.scaleLinear().domain([0, 1]).range([iH, 0]);

    // Grid
    g.append("g").attr("class", "grid")
      .attr("transform", `translate(0,${iH})`)
      .call(d3.axisBottom(xScale).ticks(5).tickSize(-iH).tickFormat(""));
    g.append("g").attr("class", "grid")
      .call(d3.axisLeft(yScale).ticks(4).tickSize(-iW).tickFormat(""));

    // Axes
    g.append("g").attr("class", "axis").attr("transform", `translate(0,${iH})`)
      .call(d3.axisBottom(xScale).ticks(5));
    g.append("g").attr("class", "axis")
      .call(d3.axisLeft(yScale).ticks(4).tickFormat(d => (d * 100).toFixed(0) + "%"));

    // Labels
    svg.append("text").attr("x", W / 2).attr("y", H - 4)
      .attr("text-anchor", "middle").attr("font-size", 10).attr("fill", "#a0aec0")
      .text("← Liberal  DW-NOMINATE Score  Conservative →");
    svg.append("text").attr("transform", `translate(10,${H / 2}) rotate(-90)`)
      .attr("text-anchor", "middle").attr("font-size", 10).attr("fill", "#a0aec0")
      .text("Satisfaction");

    // Dots layer
    const dotsG = g.append("g").attr("class", "dots");

    return { svg, g, dotsG, xScale, yScale, iW, iH };
  }

  let scatter;
  function renderScatter(state) {
    if (!scatter) scatter = buildScatter("#scatter-chart");
    const { dotsG, xScale, yScale } = scatter;
    const act = state.activeAct;

    const dots = dotsG.selectAll("circle").data(state.visitors, d => d.id);
    const sat = v => act ? (v.satisfaction[act.id] ?? 0) : 0;

    dots.enter().append("circle")
        .attr("r", 4).attr("opacity", 0.75)
        .attr("cx", d => xScale(d.dwnominate))
        .attr("cy", d => yScale(sat(d)))
        .attr("fill", d => d.color)
      .merge(dots)
      .transition().duration(500)
        .attr("cx", d => xScale(d.dwnominate))
        .attr("cy", d => yScale(sat(d)))
        .attr("fill", d => d.color);

    dots.exit().remove();
  }

  // ── 2. Satisfaction Histogram + Gaussian overlay ─────────────────────────
  function buildHistogram(selector) {
    const el = document.querySelector(selector);
    const W = el.clientWidth || 360, H = 220;
    const M = { top: 15, right: 15, bottom: 40, left: 45 };
    const iW = W - M.left - M.right, iH = H - M.top - M.bottom;

    const svg = d3.select(selector).append("svg").attr("width", W).attr("height", H);
    const g = svg.append("g").attr("transform", `translate(${M.left},${M.top})`);

    const xScale = d3.scaleLinear().domain([LO, HI]).range([0, iW]);
    const yScale = d3.scaleLinear().domain([0, 1]).range([iH, 0]);

    g.append("g").attr("class", "axis").attr("transform", `translate(0,${iH})`)
      .call(d3.axisBottom(xScale).ticks(5));
    g.append("g").attr("class", "axis")
      .call(d3.axisLeft(yScale).ticks(4).tickFormat(d => (d * 100).toFixed(0) + "%"));

    svg.append("text").attr("x", W / 2).attr("y", H - 4)
      .attr("text-anchor", "middle").attr("font-size", 10).attr("fill", "#a0aec0")
      .text("← Liberal  DW-NOMINATE  Conservative →");

    const barsG   = g.append("g").attr("class", "bars");
    const curveG  = g.append("g").attr("class", "curve");
    const valenceG = g.append("g").attr("class", "valence-line");

    return { svg, g, barsG, curveG, valenceG, xScale, yScale, iW, iH };
  }

  let histogram;
  function renderHistogram(state) {
    if (!histogram) histogram = buildHistogram("#histogram-chart");
    const { barsG, curveG, valenceG, xScale, yScale, iW } = histogram;
    const { bins, curve, actRing } = state;
    const act = state.activeAct;

    // Bars
    const binW = bins.length ? iW / bins.length : 0;
    const bars = barsG.selectAll("rect").data(bins, d => d.binMid);
    bars.enter().append("rect")
        .attr("x", d => xScale(d.binMid) - binW / 2 + 1)
        .attr("width", Math.max(0, binW - 2))
        .attr("fill", d => ideologyColor(d.binMid))
        .attr("opacity", 0.6)
      .merge(bars)
      .transition().duration(500)
        .attr("x", d => xScale(d.binMid) - binW / 2 + 1)
        .attr("width", Math.max(0, binW - 2))
        .attr("y", d => yScale(d.meanSat))
        .attr("height", d => yScale(0) - yScale(d.meanSat));
    bars.exit().remove();

    // Gaussian overlay curve
    const line = d3.line().x(d => xScale(d.x)).y(d => yScale(d.y)).curve(d3.curveBasis);
    const path = curveG.selectAll("path").data(curve.length ? [curve] : []);
    path.enter().append("path")
        .attr("fill", "none").attr("stroke", "#e6a817").attr("stroke-width", 2).attr("opacity", 0.9)
      .merge(path)
      .transition().duration(500)
        .attr("d", line);
    path.exit().remove();

    // Valence marker
    const vl = valenceG.selectAll("line").data(act ? [act.political_valence] : []);
    vl.enter().append("line")
        .attr("y1", 0).attr("stroke", "#fff").attr("stroke-dasharray", "4,3").attr("opacity", 0.5)
      .merge(vl)
      .attr("x1", d => xScale(d)).attr("x2", d => xScale(d))
      .attr("y2", yScale(0));
    vl.exit().remove();
  }

  // ── 3. Circus Ring (polar) ───────────────────────────────────────────────
  function buildRing(selector) {
    const el = document.querySelector(selector);
    const W = el.clientWidth || 360, H = 300;
    const svg = d3.select(selector).append("svg").attr("width", W).attr("height", H);
    const g = svg.append("g").attr("transform", `translate(${W / 2},${H / 2})`);
    return { svg, g, W, H, R: Math.min(W, H) / 2 - 30 };
  }

  let ring;
  function renderRing(state) {
    if (!ring) ring = buildRing("#ring-chart");
    const { g, R } = ring;
    const { actRing } = state;
    const n = actRing.length;
    const arc = d3.arc();
    const tau = 2 * Math.PI;

    const arcs = g.selectAll("g.arc-group").data(actRing, d => d.act.id);

    const entered = arcs.enter().append("g").attr("class", "arc-group");
    entered.append("path");
    entered.append("text").attr("text-anchor", "middle").attr("font-size", 16);

    const all = entered.merge(arcs);

    all.select("path")
      .transition().duration(500)
      .attr("d", (d, i) => arc({
        innerRadius: R * 0.35,
        outerRadius: R * 0.35 + (d.staged ? R * 0.5 * d.meanSat + 12 : 8),
        startAngle: (i / n) * tau,
        endAngle: ((i + 1) / n) * tau - 0.02,
      }))
      .attr("fill", d => d.staged ? ideologyColor(d.act.political_valence) : "#1e3a5f")
      .attr("opacity", d => d.staged ? 0.75 + 0.25 * d.meanSat : 0.3)
      .attr("stroke", d => (d.act === state.activeAct) ? "#e6a817" : "none")
      .attr("stroke-width", 2);

    all.select("text")
      .attr("transform", (d, i) => {
        const angle = ((i + 0.5) / n) * tau - Math.PI / 2;
        const r = R * 0.25;
        return `translate(${r * Math.cos(angle)},${r * Math.sin(angle)})`;
      })
      .text(d => d.act.emoji);

    arcs.exit().remove();
  }

  // ── 4. Phone-Urge Gauge ──────────────────────────────────────────────────
  function buildGauge(selector) {
    const el = document.querySelector(selector);
    const W = el.clientWidth || 200, H = 130;
    const svg = d3.select(selector).select("svg");
    // svg already exists in HTML; just size it
    svg.attr("width", W).attr("height", H);
    const g = svg.append("g").attr("transform", `translate(${W / 2},${H - 10})`);
    const R = Math.min(W / 2, H) - 10;

    // Background arc
    const bgArc = d3.arc()({ innerRadius: R - 16, outerRadius: R, startAngle: -Math.PI / 1.1, endAngle: Math.PI / 1.1 });
    g.append("path").attr("d", bgArc).attr("fill", "#1e3a5f");

    const fillArc = g.append("path").attr("fill", "#c0392b");
    const needle  = g.append("line").attr("stroke", "#e6a817").attr("stroke-width", 3).attr("stroke-linecap", "round");
    const centre  = g.append("circle").attr("r", 5).attr("fill", "#e6a817");
    const label   = g.append("text").attr("text-anchor", "middle").attr("y", -R * 0.45)
                     .attr("fill", "#eaeaea").attr("font-size", 12);

    return { g, fillArc, needle, label, R };
  }

  let gauge;
  function renderGauge(state) {
    if (!gauge) gauge = buildGauge("#phone-gauge");
    const { fillArc, needle, label, R } = gauge;
    const urge = state.phoneUrge;                  // 0 = engaged, 1 = on phone
    const SA = -Math.PI / 1.1, EA = Math.PI / 1.1;
    const angle = SA + urge * (EA - SA);

    fillArc.transition().duration(500)
      .attr("d", d3.arc()({
        innerRadius: R - 16, outerRadius: R,
        startAngle: SA, endAngle: angle,
      }));

    const nx = (R * 0.65) * Math.sin(angle);
    const ny = -(R * 0.65) * Math.cos(angle);
    needle.transition().duration(500)
      .attr("x1", 0).attr("y1", 0).attr("x2", nx).attr("y2", ny);

    label.text(`${(urge * 100).toFixed(0)}% on phone`);
  }

  // ── Public renderAll ─────────────────────────────────────────────────────
  function renderAll(circusState) {
    const s = circusState.stats();
    s.activeAct   = circusState.activeAct;
    s.visitors    = circusState.visitors;
    s.phoneUrge   = audiencePhoneUrge(circusState.visitors);

    renderScatter(s);
    renderHistogram(s);
    renderRing(s);
    renderGauge(s);
    updateStatPanel(s, circusState);
    updateActCard(circusState.activeAct);
    updateLegend(s);
  }

  // ── Side-panel stats ─────────────────────────────────────────────────────
  function updateStatPanel(s, state) {
    setText("stat-visitors",  s.visitorCount);
    setText("stat-acts",      s.actsStaged + " / " + ACTS.length);
    setText("stat-mean-sat",  s.activeActMeanSat ? (s.activeActMeanSat * 100).toFixed(1) + "%" : "—");
    setText("stat-phone-away", ((1 - s.phoneUrge) * 100).toFixed(1) + "%");
    setText("stat-running",   state.isRunning ? "▶ Running" : "—");
  }

  function updateActCard(act) {
    if (!act) return;
    setText("act-emoji", act.emoji);
    setText("act-name", act.name);
    setText("act-desc", act.description);
    const valBar = document.getElementById("act-valence-bar");
    if (valBar) {
      // valence in [-1,+1] → left% [0,100]
      const pct = ((act.political_valence + 1) / 2 * 100).toFixed(1);
      valBar.style.background = `linear-gradient(to right, #1a6faf ${pct}%, #c0392b ${pct}%)`;
      valBar.title = `Political valence: ${act.political_valence.toFixed(2)}`;
    }
  }

  function updateLegend(s) {
    const el = document.getElementById("ring-legend");
    if (!el) return;
    el.innerHTML = s.actRing.map(r =>
      `<span class="ring-legend-item ${r.staged ? 'staged' : ''}" title="${r.act.name}">${r.act.emoji}</span>`
    ).join("");
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  return { renderAll };
})();
