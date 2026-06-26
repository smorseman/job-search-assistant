// Box-Muller transform: samples one value from N(0,1)
function boxMuller() {
  let u1, u2;
  do { u1 = Math.random(); } while (u1 === 0); // avoid log(0)
  u2 = Math.random();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
}

function scoreLabel(theta) {
  if (theta < -0.5) return "Liberal";
  if (theta >  0.5) return "Conservative";
  return "Moderate";
}

// DW-NOMINATE-style colour: blue (left) → purple (centre) → red (right)
// theta expected in roughly [-2.5, 2.5]; mapped to [0,1] for interpolation
function ideologyColor(theta) {
  const t = Math.max(0, Math.min(1, (theta + 2.5) / 5));
  // blue  #1a6faf  →  purple #7b3f8e  →  red #c0392b
  if (t < 0.5) {
    const s = t * 2;
    return lerpColor([26, 111, 175], [123, 63, 142], s);
  } else {
    const s = (t - 0.5) * 2;
    return lerpColor([123, 63, 142], [192, 57, 43], s);
  }
}

function lerpColor(a, b, t) {
  const r = Math.round(a[0] + (b[0] - a[0]) * t);
  const g = Math.round(a[1] + (b[1] - a[1]) * t);
  const bl = Math.round(a[2] + (b[2] - a[2]) * t);
  return `rgb(${r},${g},${bl})`;
}

const AGE_GROUPS = ["child", "teen", "adult", "senior"];

class Visitor {
  constructor(overrideScore = null) {
    this.id = crypto.randomUUID();
    // Clamp to ±3 so extreme outliers stay on-screen
    const raw = overrideScore ?? boxMuller();
    this.dwnominate = Math.max(-3, Math.min(3, raw));
    this.label = scoreLabel(this.dwnominate);
    this.color = ideologyColor(this.dwnominate);
    this.ageGroup = AGE_GROUPS[Math.floor(Math.random() * AGE_GROUPS.length)];
    this.satisfaction = {};   // actId → [0,1]
    this.phoneUrge = 1.0;     // 1 = glued to phone; 0 = fully engaged
    this.totalShows = 0;
  }

  // Record satisfaction for an act and decay phone urge
  attend(act, score) {
    this.satisfaction[act.id] = score;
    this.totalShows++;
    // Running mean satisfaction (exponential moving average, α=0.4)
    const prev = 1 - this.phoneUrge;
    const alpha = 0.4;
    const meanSat = alpha * score + (1 - alpha) * prev;
    this.phoneUrge = Math.exp(-2 * meanSat);
  }
}
