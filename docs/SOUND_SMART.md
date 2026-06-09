# Sound Smart at Dinner — the Nostradamus glossary

Plain-English definitions with examples, each tied to what our system actually does.
Drop these casually. Your wife will think you run a hedge fund. (You kind of do.)

---

## The big idea

**Alpha** — Return you earn *because you're skilled*, above what the market gave everyone for free.
> "Index funds give you the market. **Alpha** is the extra you squeeze out by being clever. Our whole system hunts alpha."

**Beta** — How much you just move with the market. Beta 1 = you ride the wave; beta 0 = you're independent of it.
> "We run **market-neutral**, so our beta is basically zero — if the S&P craters, we can still make money."

**Market-neutral / long-short** — Buy the stuff you expect to win (**long**) and bet against the stuff you expect to lose (**short**) in equal size, so the overall market washes out and only your *skill* shows.
> "We're **long-short market-neutral** — 41 longs, 41 shorts, net exposure zero. We're not betting the market goes up; we're betting we picked better than average."

**Short** — Selling a stock you don't own (borrowing it) so you profit if it falls.
> "We **short** the bottom-ranked names — if they drop, that's money in our pocket."

---

## How we measure skill (this is the good stuff)

**IC (Information Coefficient)** — A score from −1 to +1 for how well our predictions line up with what actually happens. Around **0.02–0.05 is genuinely valuable** in this game (it sounds tiny — it isn't).
> "Our blended signal has an **IC** of about 0.028. Renaissance built the greatest fortune in finance on edges barely bigger than that."

**ICIR** — IC divided by how much it bounces around. It's *consistency*. A small edge that shows up **every single day** beats a big edge that shows up once a month.
> "I don't care about one lucky call — I care about **ICIR**, the edge being there reliably."

**Breadth** — How many independent bets you make. More bets = more chances for your edge to compound.
> "We maximize **breadth** — thousands of small bets across the whole market, not one big swing."

**The Fundamental Law of Active Management** — The one equation: `Return ≈ IC × √Breadth`. Skill times the square root of how often you bet.
> "It's the **Fundamental Law**: a casino's edge per spin is 2.7%, but over a million spins it's a money-printing machine. We're the casino."

**Information Ratio (IR) / Sharpe** — Reward per unit of risk. How much return you get for the stomach-churn you endure. Above 1.0 is excellent.
> "Top funds run a **Sharpe** around 1–2. That's the target — smooth, repeatable, not a rollercoaster."

**Quintile spread** — Split stocks into 5 buckets by our score; the spread is how much the top bucket beats the bottom. Positive = our ranking actually makes money.
> "We flipped our **quintile spread** positive this week — the top picks now genuinely outperform the bottom ones."

---

## The signals we trade (alpha "sleeves")

**Sleeve** — One independent source of edge. We stack many weak ones; combined, they're strong.
> "Each **sleeve** is a different way to be right. One model is fragile; ten uncorrelated sleeves is a fortress."

**Momentum** — Winners keep winning for a while. Buy recent strength.
> "**Momentum** is the oldest trick in the book — trends persist longer than people expect."

**Mean-reversion / reversal** — What shot up too fast often snaps back. Fade the overreaction.
> "Short-term **reversal** — when a stock spikes on nothing, we lean the other way."

**PEAD (Post-Earnings-Announcement Drift)** — After a company beats earnings, the stock keeps drifting up for weeks because the news spreads slowly. One of the most reliable patterns in 50+ years.
> "**PEAD** — when a company crushes earnings, the move isn't over that day; it drifts for a month. We ride that drift."

**SUE (Standardized Unexpected Earnings)** — How big a surprise the earnings beat was, relative to normal. Big clean surprise = strong drift.
> "We rank by **SUE** — not just *did* they beat, but did they beat *shockingly*."

**Analyst revisions** — When Wall Street analysts upgrade a stock, others follow over weeks. We front-run the herd.
> "**Analyst revisions** are slow-motion — the first upgrade predicts the next ten. We get there first."

**Neutralization** — Stripping out sector and size effects so we're comparing apples to apples, not just 'small risky stocks beat big safe ones.'
> "We **neutralize** by sector and size — otherwise you're not picking winners, you're just secretly betting on tiny companies."

---

## The plumbing

**API** — A way for two programs to talk. We pull data from other companies' computers through their **API**.
> "We hit the Finnhub **API** for earnings data — their server hands ours the numbers automatically."

**REST / endpoint** — The most common API style; an **endpoint** is one specific request you can make (a URL).
> "The `/stock/earnings` **endpoint** gives us every earnings surprise for a ticker."

**Rate limit** — How many requests you're allowed per minute before they cut you off. Free tiers are stingy, so we cache.
> "Free tier is 60 calls a minute — so we **cache** and only refresh what's stale."

**Cache** — Saving data locally so you don't re-ask for it constantly.
> "Earnings only change quarterly, so we **cache** them for days. No point asking every 15 minutes."

**Paper trading** — Trading with fake money but real prices, to prove a strategy before risking a dime.
> "It's all **paper trading** until the numbers prove themselves forward — then, and only then, real capital."

**Slippage** — The gap between the price you wanted and the price you got. Small, but it eats naive strategies alive.
> "Lots of 'winning' strategies die once you count **slippage**. We model it from day one."

---

## Machine learning

**Model** — A program that learned patterns from history to predict the future.
> "Our **model** trained on years of price data to rank tomorrow's likely winners."

**Feature** — One input fact the model looks at (a stock's recent return, its volatility, an earnings surprise).
> "Predictor v3 looks at 50 **features** per stock before it makes a call."

**Training / walk-forward** — Teaching the model on the past, then testing it on a *later* period it never saw — like a real forecast, no cheating.
> "We use **walk-forward** testing — train on 2023, test on 2025. No peeking at the future."

**Overfitting** — When a model memorizes noise instead of learning real patterns; looks brilliant on old data, fails live.
> "The enemy is **overfitting** — a backtest that looks perfect because it learned coincidences. We hunt that down."

**Deflated Sharpe** — A reality check that penalizes you for trying thousands of strategies until one looks good by luck.
> "We watch the **deflated Sharpe** — if we tested 10,000 ideas, one will look amazing by accident. That's not edge, that's noise."

**Ensemble** — Combining many models/signals into one decision. The crowd of models beats any single one.
> "It's an **ensemble** — like asking ten experts and blending their answers instead of trusting one."

**Kelly criterion** — The math for how big to bet given your edge — bet bigger when you're more confident, never bet the farm.
> "Position sizing uses the **Kelly criterion** — conviction sets the bet size, with a safety brake."

---

*Pro move at dinner:* "The trick isn't being right more often — it's the **Fundamental Law**: a small, consistent edge across a huge number of independent, market-neutral bets. Skill times the square root of breadth." Then sip your drink.
