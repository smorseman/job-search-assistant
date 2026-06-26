// Gaussian satisfaction: S(θ, v, σ) = exp(-(θ-v)² / 2σ²)
function gaussianSatisfaction(theta, valence, radius) {
  const sigma = radius > 0 ? radius : 0.5;
  return Math.exp(-Math.pow(theta - valence, 2) / (2 * sigma * sigma));
}

// Score every visitor against an act, mutate each visitor's state
function applyAct(visitors, act) {
  visitors.forEach(v => {
    const score = gaussianSatisfaction(v.dwnominate, act.political_valence, act.entertainment_radius);
    v.attend(act, score);
  });
}

// Bin visitors by DW-NOMINATE score into N equal-width bins across [lo, hi]
// Returns array of {binMid, meanSat, count}
function aggregateByBin(visitors, actId, bins = 10, lo = -2.5, hi = 2.5) {
  const width = (hi - lo) / bins;
  const buckets = Array.from({ length: bins }, (_, i) => ({
    binMid: lo + (i + 0.5) * width,
    sum: 0,
    count: 0,
  }));

  visitors.forEach(v => {
    const sat = v.satisfaction[actId] ?? 0;
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v.dwnominate - lo) / width)));
    buckets[idx].sum += sat;
    buckets[idx].count++;
  });

  return buckets.map(b => ({
    binMid: b.binMid,
    meanSat: b.count > 0 ? b.sum / b.count : 0,
    count: b.count,
  }));
}

// Theoretical Gaussian curve points for the overlay (100 points across [lo, hi])
function gaussianCurve(act, lo = -2.5, hi = 2.5, points = 100) {
  return Array.from({ length: points }, (_, i) => {
    const x = lo + (i / (points - 1)) * (hi - lo);
    return { x, y: gaussianSatisfaction(x, act.political_valence, act.entertainment_radius) };
  });
}

// Aggregate phone urge across all visitors → [0,1]; 0 = everyone engaged
function audiencePhoneUrge(visitors) {
  if (!visitors.length) return 1;
  return visitors.reduce((s, v) => s + v.phoneUrge, 0) / visitors.length;
}

// Per-act mean satisfaction across the whole audience
function actMeanSatisfaction(visitors, actId) {
  const scored = visitors.filter(v => actId in v.satisfaction);
  if (!scored.length) return 0;
  return scored.reduce((s, v) => s + v.satisfaction[actId], 0) / scored.length;
}
