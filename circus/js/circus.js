class CircusState {
  constructor() {
    this.visitors = [];
    this.stagedActs = [];   // acts performed so far, in order
    this.activeAct = null;
    this.isRunning = false;
    this._listeners = [];
  }

  // Subscribe to state changes
  onChange(fn) { this._listeners.push(fn); }
  _emit() { this._listeners.forEach(fn => fn(this)); }

  // --- Visitor management ---

  addRandomVisitor() {
    if (this.visitors.length >= 200) this.visitors.shift(); // rolling window
    this.visitors.push(new Visitor());
    this._applyHistoryToNew(this.visitors[this.visitors.length - 1]);
    this._emit();
  }

  addTargetedVisitor(score) {
    if (this.visitors.length >= 200) this.visitors.shift();
    this.visitors.push(new Visitor(score));
    this._applyHistoryToNew(this.visitors[this.visitors.length - 1]);
    this._emit();
  }

  setPopulation(n) {
    const target = Math.max(10, Math.min(200, n));
    while (this.visitors.length < target) {
      const v = new Visitor();
      this._applyHistoryToNew(v);
      this.visitors.push(v);
    }
    if (this.visitors.length > target) {
      this.visitors = this.visitors.slice(this.visitors.length - target);
    }
    this._emit();
  }

  // Give new arrivals scores for every act already staged
  _applyHistoryToNew(visitor) {
    this.stagedActs.forEach(act => {
      const score = gaussianSatisfaction(visitor.dwnominate, act.political_valence, act.entertainment_radius);
      visitor.attend(act, score);
    });
  }

  // --- Act staging ---

  stageAct(actId) {
    const act = ACT_BY_ID[actId];
    if (!act) return;
    this.activeAct = act;
    this.stagedActs.push(act);
    applyAct(this.visitors, act);
    this._emit();
  }

  // --- Full show runner ---

  async runFullShow(intervalMs = 1200) {
    if (this.isRunning) return;
    this.isRunning = true;
    this.stagedActs = [];
    this.activeAct = null;
    // Reset visitor history
    this.visitors.forEach(v => { v.satisfaction = {}; v.phoneUrge = 1.0; v.totalShows = 0; });

    for (const act of ACTS) {
      if (!this.isRunning) break;
      this.stageAct(act.id);
      await delay(intervalMs);
    }
    this.isRunning = false;
    this._emit();
  }

  stopShow() {
    this.isRunning = false;
  }

  // --- Derived stats ---

  stats() {
    const act = this.activeAct;
    return {
      visitorCount: this.visitors.length,
      actsStaged: this.stagedActs.length,
      phoneUrge: audiencePhoneUrge(this.visitors),
      activeActMeanSat: act ? actMeanSatisfaction(this.visitors, act.id) : 0,
      bins: act ? aggregateByBin(this.visitors, act.id) : [],
      curve: act ? gaussianCurve(act) : [],
      actRing: ACTS.map(a => ({
        act: a,
        staged: this.stagedActs.some(s => s.id === a.id),
        meanSat: actMeanSatisfaction(this.visitors, a.id),
      })),
    };
  }
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// Singleton
const circus = new CircusState();
