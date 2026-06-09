/**
 * Stack & Edge — authoritative node metadata for schematics (hover tooltips + mega map).
 * Layer colors: grey data → green pipelines → epic purple ML → legendary orange Droid
 */

export const LAYER_COLORS = {
  data: { fill: '#374151', stroke: '#9ca3af', text: '#f3f4f6', label: 'Raw data' },
  pipeline: { fill: '#14532d', stroke: '#22c55e', text: '#bbf7d0', label: 'Pipelines' },
  ml: { fill: '#4c1d95', stroke: '#a855f7', text: '#e9d5ff', label: 'ML & signals' },
  droid: { fill: '#7c2d12', stroke: '#ff9500', text: '#fff4e0', label: 'Treasure Droid' },
  loop: { fill: '#0c4a6e', stroke: '#38bdf8', text: '#bae6fd', label: 'Feedback loop' },
};

export const STORY_FLOW = 'Grey → Green → Purple → Legendary Orange';

/** @typedef {object} ArchNode
 * @property {string} id
 * @property {string} layer
 * @property {string} label
 * @property {string} short
 * @property {string} cadence
 * @property {string[]} sources
 * @property {string[]} downstream
 * @property {string} edge
 * @property {string} [equation]
 * @property {string} [theory]
 * @property {string} [script]
 */

/** @type {ArchNode[]} */
export const PIPELINE_NODES = [
  {
    id: 'yahoo_ohlcv',
    layer: 'data',
    label: 'Yahoo OHLCV',
    short: 'OHLCV',
    cadence: 'Incremental daily (~5d lookback); full history rebuild weekly',
    sources: ['Yahoo Finance (yfinance)', 'Stooq fallback in historical rebuild'],
    downstream: ['fetch-history → data/historical/*.json', 'Predictor v3 day-diff features', 'Price sleeves (reversal, momentum)'],
    edge: 'Breadth foundation — ~10yr candles × thousands of symbols. Without price, nothing else runs.',
    script: 'scripts/fetch-history.py',
  },
  {
    id: 'sec_form4',
    layer: 'data',
    label: 'SEC Form 4',
    short: 'Insider',
    cadence: 'Every 2h via intelligence pulse; on-demand fetch',
    sources: ['SEC EDGAR submissions API', 'Cached under .cache/sec-submissions/'],
    downstream: ['overlay_features (insider flags)', 'Predictor v3 overlay columns', 'Congress alignment boosts'],
    edge: 'Informed-trading signal — insiders buying ahead of moves (sparse but high SNR when present).',
    script: 'scripts/fetch-insider-trades.py',
  },
  {
    id: 'congress_trades',
    layer: 'data',
    label: 'Congress trades',
    short: 'Congress',
    cadence: 'Every 2h via brain.py / intelligence pulse',
    sources: ['House/Senate disclosure scrapers', 'data/congress/'],
    downstream: ['Investor ranking overlay', 'Notable watchlist on Bridge', 'Reasoning agent context'],
    edge: 'Politician flow as weak prior — alignment with ML picks boosts conviction, not a standalone alpha.',
    script: 'scripts/fetch-congress-trades.py',
  },
  {
    id: 'fred_macro',
    layer: 'data',
    label: 'FRED macro',
    short: 'Macro',
    cadence: 'Daily close + weekly harness',
    sources: ['Federal Reserve FRED API (rates, VIX proxy, regime tags)'],
    downstream: ['Regime classifier', 'Predictor overlay features', 'Brain scheduler mode'],
    edge: 'Regime conditioning — same ML signal behaves differently in high-vol vs calm tapes.',
    script: 'scripts/orchestrator.py',
  },
  {
    id: 'finnhub_fundamentals',
    layer: 'data',
    label: 'Finnhub fundamentals',
    short: 'Finnhub',
    cadence: 'Daily / on intelligence pulse',
    sources: ['Finnhub API (earnings surprises, analyst revisions)'],
    downstream: ['PEAD sleeve', 'Revisions sleeve in alpha engine'],
    edge: 'Event-driven drift — post-earnings and revision momentum sleeves (sparse, being backfilled historically).',
    script: 'scripts/intelligence/finnhub.py',
  },
  {
    id: 'sentiment_feed',
    layer: 'data',
    label: 'Sentiment & gossip',
    short: 'Sentiment',
    cadence: 'Every 2h (continual_intelligence.ps1)',
    sources: ['Yahoo RSS headlines', 'Reddit mass-psych cache', 'Optional FinBERT scores'],
    downstream: ['sentiment alpha sleeve', 'Reasoning narrative context'],
    edge: 'Crowd positioning — contrarian/momentum overlay when news flow diverges from price.',
    script: 'scripts/intelligence/sentiment_feed.py',
  },
  {
    id: 'alpaca_paper',
    layer: 'data',
    label: 'Alpaca paper',
    short: 'Paper $',
    cadence: 'Real-time during RTH; polled on /api/alpaca/account',
    sources: ['Alpaca paper trading API'],
    downstream: ['Bridge equity tiles', 'Forward truth gate inputs', 'Fleet mark-to-market'],
    edge: 'Forward truth anchor — fake money, real fills/prices. The only PnL that counts for promotion.',
  },
  {
    id: 'canal_history',
    layer: 'pipeline',
    label: 'fetch-history',
    short: 'History canal',
    cadence: 'Post-close daily; weekly full regen',
    sources: ['yahoo_ohlcv'],
    downstream: ['data/historical/<sector>.json', 'train-predictor-v3.py', 'panel_builder.py'],
    edge: 'Canonical price store — all ML trains from the same diff-feature pipeline.',
    script: 'scripts/fetch-history.py',
  },
  {
    id: 'canal_insider',
    layer: 'pipeline',
    label: 'Insider canal',
    short: 'Insider→',
    cadence: '2h pulse',
    sources: ['sec_form4'],
    downstream: ['overlay_features.attach_all_overlays', 'live.csv enrichment'],
    edge: 'Joins insider flags onto (date,symbol) panel rows.',
    script: 'scripts/fetch-insider-trades.py',
  },
  {
    id: 'canal_congress',
    layer: 'pipeline',
    label: 'Congress canal',
    short: 'Congress→',
    cadence: '2h pulse',
    sources: ['congress_trades'],
    downstream: ['Investor overlay', 'api/congress/notable'],
    edge: 'Human-readable politician flow for ranking boosts.',
    script: 'scripts/fetch-congress-trades.py',
  },
  {
    id: 'regime_engine',
    layer: 'pipeline',
    label: 'Regime & brain',
    short: 'Regime',
    cadence: 'Every 2h + scheduler tick',
    sources: ['fred_macro', 'live panel stats'],
    downstream: ['brain/schedule.json', 'Harness mode selection', 'Risk caps'],
    edge: 'Adapts harness aggressiveness to volatility session — avoids training in wrong regime.',
    script: 'scripts/intelligence/brain.py',
  },
  {
    id: 'live_panel',
    layer: 'pipeline',
    label: 'live.csv panel',
    short: 'live.csv',
    cadence: 'Post-close daily + intraday pulse (15m RTH for reasoning path)',
    sources: ['Predictor v3 inference', 'Alpha engine', 'Overlay features'],
    downstream: ['Trader Arena sim', 'Fleet forward paper', 'Manifests', 'Mad Scientist panel mirror'],
    edge: 'Single source of truth for cross-section each day — pred_proba_up, pred_ret, edge, alpha, n_* sleeves.',
    script: 'scripts/generate_live_predictions.py',
  },
  {
    id: 'predictor_v3',
    layer: 'ml',
    label: 'Predictor v3',
    short: 'Predictor',
    cadence: 'Weekly retrain (Sunday harness); daily inference only',
    sources: ['canal_history', 'overlays (SEC, congress, regime)'],
    downstream: ['live.csv', 'Historical panel (val+test)', 'Investor v3 training'],
    edge: 'Core IC engine — stacked HGB classifiers + regressor with isotonic calibration.',
    theory: 'Grinold Fundamental Law: tiny per-name IC × √breadth. Predictor supplies the IC term.',
    equation: `p_stack = Logistic( [HGB_clf_seed_0..4](x) )   # meta fit on 2024 val
pred_proba_up = Isotonic(p_stack)
pred_ret = HGB_reg(x)
edge = (2·pred_proba_up − 1) · |pred_ret|
Split: train ≤2023-12-31 | val 2024 | test 2025+ (held out)
x = day-diff OHLCV (~30 feats) + OVERLAY_FEATURE_COLS (SEC, congress, regime)`,
    script: 'scripts/train-predictor-v3.py',
  },
  {
    id: 'alpha_engine',
    layer: 'ml',
    label: 'Alpha engine',
    short: 'Alpha',
    cadence: 'Every daily close + panel enrich for Mad Scientist',
    sources: ['live_panel', 'Point-in-time prices', 'Finnhub', 'Sentiment'],
    downstream: ['alpha/book.json', 'Fleet ranking', 'Mad Scientist panel alpha column'],
    edge: 'WorldQuant-style multi-sleeve factory — many weak signals combined & neutralized.',
    theory: 'Alpha Doctrine Pillar 3: many weak alphas (IC~0.01–0.03) beat one strong model if uncorrelated.',
    equation: `Per sleeve s: n_s = cs_zscore( demean_sector( demean_size( winsorize(raw_s) ) ) )
α = Σ_s w_s · n_s   (w_s from sleeve_ic.json ICIR weights)
Sleeves: ml_edge, ml_proba, reversal_1d/5d, momentum_120_20, pead, revisions, sentiment`,
    script: 'scripts/intelligence/alpha/engine.py',
  },
  {
    id: 'investor_v3',
    layer: 'ml',
    label: 'Investor v3',
    short: 'Investor',
    cadence: 'Daily close retrain policy; manifests refreshed post-close',
    sources: ['predictor_v3 test/live outputs', 'Congress overlays'],
    downstream: ['decisions.json backtest', 'Swing manifest', 'Arena parent genomes'],
    edge: 'Kelly-sized portfolio policy — turns ML panel into dollars (sim) with friction.',
    equation: `rank = (pred_proba_up − 0.5) · pred_ret · confidence
size_i = min(kelly(p_i), 0.20) capped at 90% gross
Policy: HGB_reg(pred_proba_up, pred_ret, sector) → realized return meta-model`,
    script: 'scripts/train-investor-v3.py',
  },
  {
    id: 'trader_arena',
    layer: 'ml',
    label: 'Trader Arena',
    short: 'Arena',
    cadence: 'Hourly pulse on active pools (v1, v2, champion v3)',
    sources: ['live.csv pred_ret proxy'],
    downstream: ['experiment.json', 'harvest → evolve', 'real_agents registry'],
    edge: 'Evolutionary search — 100 genomes/version compete on fast sim PnL before forward paper.',
    equation: `Sim daily return ≈ weighted pred_ret of selected names − costs
v1: threshold gates | v2: rank-unified | v3: champion pool (mutable)
Harvest top decile → breed → distill ≤5 real agents`,
    script: 'scripts/intelligence/trader_arena.py',
  },
  {
    id: 'mad_scientist_lab',
    layer: 'ml',
    label: 'Mad Scientist Lab',
    short: 'Mad Lab',
    cadence: 'Every 3h (continual_mad_scientist.ps1) + weekly harness',
    sources: ['Historical panel 2024–2025', 'Predictor ≤2023 train window'],
    downstream: ['Shadow fleet MS-* agents', 'lab_results.json', 'Captain briefing'],
    edge: '8yr train / 2yr walk-forward — proves genomes on held-out days before shadow promotion.',
    theory: 'Scientific method at scale: spawn → select 60% → judge 40% holdout → promote survivors.',
    equation: `signal = alpha if genome.signal=='alpha' else edge
edge = (2·pred_proba_up − 1) · |pred_ret|
Long: mask(proba≥min_proba & pred_ret≥min_pred_ret) → top_k by signal, proba-weighted ret
day_ret = long_gross·R_long + short_gross·R_short − gross·cost_bps/1e4
Selection = first 60% walk-forward days; holdout = tail
Sharpe_hold = mean(day_ret)/std(day_ret)·√252; promote if ≥ 0.5`,
    script: 'scripts/intelligence/historical/walkforward_lab.py',
  },
  {
    id: 'sleeve_ic',
    layer: 'ml',
    label: 'Sleeve IC tracker',
    short: 'Sleeve IC',
    cadence: 'Daily close (sleeve_ic.py)',
    sources: ['Forward snapshots', 'Research val/test IC'],
    downstream: ['alpha_engine weights', 'Bridge scoreboard', 'Auto-decay bad sleeves'],
    edge: 'Closes the loop — sleeves that fail forward ICIR get down-weighted automatically.',
    equation: `IC_s = Spearman(rank(n_s), rank(y_ret))
ICIR_s = mean(IC_s) / std(IC_s) over forward window
w_s ∝ max(0, ICIR_s) normalized; decay flag if IC_s < 0`,
    script: 'scripts/intelligence/alpha/sleeve_ic.py',
  },
  {
    id: 'penny_ml',
    layer: 'ml',
    label: 'Penny Wolf ML',
    short: 'Penny ML',
    cadence: 'Background batches (penny_ml_search.ps1); NPU when available',
    sources: ['Sub-$5 historical panel'],
    downstream: ['Penny desk signals', 'Separate risk sleeve'],
    edge: 'Microcap momentum niche — orthogonal to main book; serialized with weekly retrain.',
    script: 'scripts/penny_ml/search.py',
  },
  {
    id: 'fleet_forward',
    layer: 'droid',
    label: 'Fleet forward paper',
    short: 'Fleet',
    cadence: 'Daily close fleet/run.py + per-agent stepping',
    sources: ['live_panel', 'Alpha book', 'Genome params per agent'],
    downstream: ['equityCurve per agent', 'Forward truth metrics', 'Leader promotion'],
    edge: 'Each spawn walks day-by-day on real prices — the only promotion scoreboard.',
    script: 'scripts/intelligence/fleet/run.py',
  },
  {
    id: 'captain_megamind',
    layer: 'droid',
    label: 'Captain (Megamind)',
    short: 'Captain',
    cadence: 'Megamind tick via improve loop + 5m agent watcher',
    sources: ['Arena compare', 'Fleet state', 'Mad Scientist lab', 'Forward truth'],
    downstream: ['Recommendations queue', 'Cursor agent prompts', 'Auto-approve critical'],
    edge: 'Meta-agent — proposes system upgrades; cannot weaken live_gate.',
    theory: 'Research velocity moat: alphas decay; the captain ships new experiments faster than decay.',
    script: 'scripts/intelligence/megamind.py',
  },
  {
    id: 'reasoning_agent',
    layer: 'droid',
    label: 'Reasoning agent',
    short: 'Reasoning',
    cadence: 'Every 15 min (continual_reasoning.ps1)',
    sources: ['live.csv top edges', 'Strategy template', 'Optional Gemini narrative'],
    downstream: ['paper_portfolio.json', 'strategy.json', 'journal.jsonl'],
    edge: 'Forward paper book separate from fleet — tests narrative + watchlist discipline.',
    script: 'scripts/reasoning_agent.py',
  },
  {
    id: 'manifests',
    layer: 'droid',
    label: 'Manifests',
    short: 'Manifests',
    cadence: 'Swing: daily close; Daytrade: every 15m RTH',
    sources: ['Investor v3', 'Daytrade signals'],
    downstream: ['Robinhood Agents polling', 'External execution prep'],
    edge: 'Handoff layer — converts internal sim to broker-ready order lists (paper first).',
    script: 'scripts/generate_trade_signals.py',
  },
  {
    id: 'readiness_gate',
    layer: 'droid',
    label: 'Readiness gate',
    short: 'Gate',
    cadence: 'Evaluated on every Captain tick + nostradamus-live daily',
    sources: ['Forward truth metrics', 'sleeve IC', 'Paper Sharpe'],
    downstream: ['liveTradingPermitted flag', 'Bridge verdict pill'],
    edge: 'Honest constraint — live capital blocked until forward metrics pass thresholds.',
    script: 'nostradamus-live readiness (external repo)',
  },
];

/** Alpha factory sleeves (neutralized before combine) */
export const ALPHA_SLEEVES = [
  { id: 'ml_edge', label: 'ML edge', equation: 'raw = (2·pred_proba_up − 1) · |pred_ret|', theory: 'Grinold IC term from stacked predictor', edge: 'Primary ML conviction sleeve — highest default weight.' },
  { id: 'ml_proba', label: 'ML proba', equation: 'raw = pred_proba_up − 0.5', theory: 'Direction-only classifier output', edge: 'Pure up/down tilt when magnitude sleeve is noisy.' },
  { id: 'reversal_1d', label: '1-day reversal', equation: 'raw = −(close_t / close_{t−1} − 1)', theory: 'Short-term reversal (Jegadeesh-style micro mean-reversion)', edge: 'Orthogonal to ML — profits when tape overreacts.' },
  { id: 'reversal_5d', label: '5-day reversal', equation: 'raw = −(close_t / close_{t−5} − 1)', theory: 'Weekly mean-reversion anomaly', edge: 'Slower reversion sleeve; decorrelates from 1d.' },
  { id: 'momentum_120_20', label: 'Residual momentum', equation: 'raw = close_{t−21}/close_{t−121} − 1', theory: '12-1 momentum (skip recent month)', edge: 'Trend sleeve balanced against reversal sleeves.' },
  { id: 'pead', label: 'PEAD', equation: 'raw = finnhub.pead_score(symbol)', theory: 'Post-earnings announcement drift', edge: 'Event-driven; sparse but uncorrelated with price ML.' },
  { id: 'revisions', label: 'Analyst revisions', equation: 'raw = finnhub.revision_score(symbol)', theory: 'Estimate revision momentum', edge: 'Fundamental drift sleeve from Finnhub feed.' },
  { id: 'sentiment', label: 'Sentiment', equation: 'raw = sentiment_score(symbol)', theory: 'News + Reddit crowd positioning', edge: 'Contrarian/momentum overlay on narrative flow.' },
  { id: 'combine', label: 'Combined alpha', equation: 'n_s = cs_zscore(neutralize_sector_size(winsorize(raw_s)))\nα = Σ_s w_s · n_s', theory: 'WorldQuant factory — ICIR weights from sleeve_ic.json', edge: 'Many weak sleeves → one tradeable cross-sectional score.' },
];

/** Mad Scientist experiment profiles (rotated every 3h) */
export const EXPERIMENT_PROFILES = [
  { name: 'alpha_neutral_wide', genomes: 400, signal: 'alpha', promote: 3, edge: 'Wide search on neutralized alpha signal.' },
  { name: 'edge_hunter', genomes: 300, signal: 'edge', promote: 2, edge: 'Hunt high-conviction ML edge combinations.' },
  { name: 'deep_search', genomes: 600, signal: 'mixed', promote: 4, edge: 'Maximum genome diversity per cycle.' },
  { name: 'tight_holdout', genomes: 350, signal: 'mixed', selection: '50%', promote: 2, edge: 'Stricter holdout — fewer false positives.' },
];

/** Feedback / recursive edges (dashed on mega map) */
export const FEEDBACK_EDGES = [
  ['fleet_forward', 'sleeve_ic'],
  ['captain_megamind', 'trader_arena'],
  ['mad_scientist_lab', 'captain_megamind'],
  ['readiness_gate', 'captain_megamind'],
  ['trader_arena', 'fleet_forward'],
];

/** Directed edges for mega chart [fromId, toId] */
export const PIPELINE_EDGES = [
  ['yahoo_ohlcv', 'canal_history'],
  ['sec_form4', 'canal_insider'],
  ['congress_trades', 'canal_congress'],
  ['fred_macro', 'regime_engine'],
  ['finnhub_fundamentals', 'alpha_engine'],
  ['sentiment_feed', 'alpha_engine'],
  ['canal_history', 'predictor_v3'],
  ['canal_insider', 'predictor_v3'],
  ['canal_congress', 'investor_v3'],
  ['regime_engine', 'live_panel'],
  ['predictor_v3', 'live_panel'],
  ['predictor_v3', 'mad_scientist_lab'],
  ['live_panel', 'alpha_engine'],
  ['alpha_engine', 'fleet_forward'],
  ['live_panel', 'trader_arena'],
  ['live_panel', 'investor_v3'],
  ['sleeve_ic', 'alpha_engine'],
  ['trader_arena', 'captain_megamind'],
  ['mad_scientist_lab', 'fleet_forward'],
  ['fleet_forward', 'readiness_gate'],
  ['investor_v3', 'manifests'],
  ['fleet_forward', 'captain_megamind'],
  ['alpaca_paper', 'readiness_gate'],
  ['penny_ml', 'manifests'],
  ['reasoning_agent', 'readiness_gate'],
];

/** Feedback loops (recursive learning) */
export const RECURSIVE_LOOPS = [
  { id: 'loop_autonomous', label: 'Autonomous supervisor', cadence: '24/7', script: 'scripts/autonomous_loop.ps1',
    children: ['reasoning 15m', 'arena 1h', 'intelligence 2h', 'improve 6h', 'mad-scientist 3h', 'megamind 5m', 'penny_ml batches'],
    edge: 'Always-on orchestration — dead child processes auto-restart.' },
  { id: 'loop_mad', label: 'Mad Scientist loop', cadence: 'Every 3h', script: 'scripts/continual_mad_scientist.ps1',
    children: ['Rotate experiment profiles', 'panel_builder if stale', 'walkforward_lab --once', 'Promote MS-* to fleet'],
    edge: 'Historical GPU-free evolution — survivors shadow-walk forward.' },
  { id: 'loop_arena', label: 'Arena harvest → evolve', cadence: 'Hourly + post-close',
    children: ['Pulse v1/v2/champion', 'Harvest all pools incl. archived', 'Breed champion genomes', 'Distill real_agents'],
    edge: 'Sim-fast feedback before expensive forward paper.' },
  { id: 'loop_harness', label: 'Learning harness', cadence: 'Daily close + Sunday weekly',
    children: ['Daily: investor, signals, sleeve_ic, fleet', 'Weekly: predictor retrain, walkforward lab, promotion gates'],
    edge: 'Scheduled deep learning — predictor weights change only on weekly boundary.' },
  { id: 'loop_ic', label: 'Sleeve IC decay', cadence: 'Daily close',
    children: ['Snapshot live book', 'Accrue forward IC', 'ICIR reweight', 'Flag decayed sleeves'],
    edge: 'Automatic alpha hygiene — bad sleeves starved without human intervention.' },
  { id: 'loop_forward', label: 'Forward truth', cadence: 'Continuous',
    children: ['Fleet paper curves', 'Reasoning paper book', 'Alpaca marks', 'Gate evaluation'],
    edge: 'The only scoreboard that unlocks capital.' },
];

export const MEGA_LAYOUT = {
  columns: [
    { layer: 'data', x: 0, nodes: ['yahoo_ohlcv', 'sec_form4', 'congress_trades', 'fred_macro', 'finnhub_fundamentals', 'sentiment_feed', 'alpaca_paper'] },
    { layer: 'pipeline', x: 1, nodes: ['canal_history', 'canal_insider', 'canal_congress', 'regime_engine', 'live_panel'] },
    { layer: 'ml', x: 2, nodes: ['predictor_v3', 'alpha_engine', 'investor_v3', 'trader_arena', 'mad_scientist_lab', 'sleeve_ic', 'penny_ml'] },
    { layer: 'droid', x: 3, nodes: ['fleet_forward', 'captain_megamind', 'reasoning_agent', 'manifests', 'readiness_gate'] },
  ],
};

export function nodeById(id) {
  return PIPELINE_NODES.find((n) => n.id === id);
}

export const COMPARE_MODELS = [
  { name: 'Treasure Droid', us: true, alt: 5, sim: 5, meta: 5, local: 5, honest: 5, forward: 3 },
  { name: 'Medallion-class', us: false, alt: 5, sim: 5, meta: 2, local: 1, honest: 3, forward: 5 },
  { name: 'Citadel / Two Sigma', us: false, alt: 5, sim: 5, meta: 3, local: 1, honest: 4, forward: 5 },
  { name: 'Numerai', us: false, alt: 3, sim: 4, meta: 4, local: 2, honest: 4, forward: 4 },
  { name: 'QuantConnect retail', us: false, alt: 2, sim: 4, meta: 2, local: 4, honest: 3, forward: 3 },
  { name: 'Retail LSTM app', us: false, alt: 1, sim: 2, meta: 1, local: 4, honest: 2, forward: 2 },
  { name: 'FinRL baseline', us: false, alt: 2, sim: 3, meta: 2, local: 4, honest: 2, forward: 2 },
  { name: 'Robo 60/40', us: false, alt: 1, sim: 2, meta: 1, local: 3, honest: 5, forward: 3 },
];

export const COMPARE_LABELS = [
  { key: 'alt', label: 'Alt data' },
  { key: 'sim', label: 'Sim scale' },
  { key: 'meta', label: 'Meta-agent' },
  { key: 'local', label: 'Local-first' },
  { key: 'honest', label: 'Honest gate' },
  { key: 'forward', label: 'Live edge' },
];

export const CADENCE_ROWS = [
  ['15 min', 'continual_reasoning.ps1', 'Reasoning paper journal + watchlist'],
  ['1 hour', 'continual_trader_arena.ps1', 'Arena pulse v1, v2, champion (+ challenger)'],
  ['2 hours', 'continual_intelligence.ps1', 'Congress/insider, sentiment, forward IC snapshot'],
  ['3 hours', 'continual_mad_scientist.ps1', 'Historical genome experiments + fleet promotion'],
  ['4 hours', 'continual_intraday.ps1', 'Intraday harness (weekdays)'],
  ['5 min', 'continual_megamind_agent.ps1', 'Cursor SDK on approved Megamind queue'],
  ['6 hours', 'continual_improve.ps1', 'Feeds, harvest-evolve, Megamind tick'],
  ['Post-close', 'daily_market_close.ps1', 'live.csv, alpha, sleeve_ic, fleet, harness daily'],
  ['Sunday', 'learning_harness weekly', 'Full predictor v3 retrain + walkforward lab'],
  ['Background', 'penny_ml_search.ps1', 'Penny NPU trial search (batched)'],
];
