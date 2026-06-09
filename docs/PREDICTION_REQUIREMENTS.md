# What Must Be True for a Powerful Prediction + Execution Stack

This checklist defines the bar Nostradamus is building toward before
connecting Robinhood Agents for real money.

## Data truth

- [x] Multi-vendor equity canal (yfinance → Tiingo → Alpha Vantage → Stooq)
- [x] Macro regime panel (12 FRED series + regime one-hot)
- [ ] GDELT tone on every training day (run `fetch-regime-data.py`; rate-limited)
- [ ] Survivorship-bias-free history (Stooq bulk ZIP or licensed CRSP/Norgate)
- [ ] Point-in-time macro (ALFRED vintages — future)
- [x] Feed health gate (`criticalReady`) before orchestrator runs

## Model truth

- [ ] Held-out AUC > 0.54 on walk-forward (v3 currently ~0.54)
- [x] Regime features joined in `train-predictor-v3.py` (14 cols)
- [ ] Predictor + investor retrained on same nightly schedule
- [x] Cost/slippage modeled in investor backtest
- [x] Liquidity + magnitude filters (ETF/treasury exclusion)

## Execution truth

- [x] Broker-neutral order schema (`scripts/broker/adapter.py`)
- [x] Manifest export for external agents
- [x] Execution ack audit log
- [ ] Robinhood Agents wired with `BROKER_MODE=robinhood_agents`
- [ ] Paper trading parity test (manifest fills vs investor simulation)

## Operational truth

- [x] Orchestrator (`scripts/orchestrator.py`)
- [x] Nightly Windows task extended (macro, regime, signals)
- [x] CI workflow `fetch-regime.yml`
- [x] Block live trading when paper-agent profit gate fails (wired in `broker/adapter.py`)
- [x] Mass psychology scraper (`intelligence/mass_psychology.py`)
- [x] Insider monitor — public Form 4 clusters (`intelligence/insider_monitor.py`)
- [x] Execution feedback loop (`intelligence/execution_feedback.py`)
- [x] Forward live IC scoring (`intelligence/forward_score.py`)
- [x] Live champion sync from nostradamus-live (`intelligence/champion_sync.py`)
- [x] Risk engine on manifests (`intelligence/risk_engine.py`)
- [x] Autonomous learning harness (`scripts/learning_harness.py`)
- [x] Overlay features: regime + congress + insider (`scripts/overlay_features.py`)
- [x] Promotion gate v3 (`scripts/promotion_gate_v3.py`)
- [ ] NPU provider active (install `onnxruntime-qnn` if QNN not detected)
