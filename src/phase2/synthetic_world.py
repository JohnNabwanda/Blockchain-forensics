"""Synthetic TRON/USDT and mobile-money world for Phase 2 (concept note, Section 12).

FOR TESTING THE ATTRIBUTION LOGIC ONLY. Every address, account and payment here is generated;
addresses start with "TSYN" and accounts contain "-SYN-" so they can never be mistaken for real
ones. Results on this data say nothing about real P2P markets. The generator and the matcher
share assumptions (fee ranges, settlement delays), so run_phase2.py --stress varies those
assumptions to show how quickly the method degrades when reality differs.

Files written:
    chain_transfers.csv    tx_id, ts, asset (USDT or TRX), src, dst, amount
    mobile_money.csv       mm_id, ts, operator, dst_operator, src, dst, amount_tzs
    fx_rates.csv           date, usd_tzs
    trader_directory.csv   trader_id, kind, identifier   (stands in for records obtained under lawful access)
    reported_wallets.csv   wallet, reports                (stands in for victim reports)
    truth_wallets.csv, truth_accounts.csv, truth_trades.csv   ground truth, read only by evaluation code
"""
import numpy as np
import pandas as pd

OPERATORS = ["M-Pesa", "Tigo Pesa", "Airtel Money", "HaloPesa"]
OP_CODE = {"M-Pesa": "MPS", "Tigo Pesa": "TGO", "Airtel Money": "AIR", "HaloPesa": "HAL"}
START = pd.Timestamp("2026-06-01", tz="Africa/Dar_es_Salaam")
B58 = list("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
USDT_SIZES = np.array([20, 30, 50, 100, 150, 200, 250, 300, 500, 1000])
USDT_P = np.array([.08, .07, .16, .20, .10, .12, .06, .09, .08, .04])


class _World:
    def __init__(self, rng):
        self.rng = rng
        self.wallets, self.accounts = [], []      # (id, entity, role) / (id, entity, operator)
        self.chain, self.mm = [], []              # (ts, asset, src, dst, amount) / (ts, src, dst, tzs)
        self.trades = []                          # (chain_idx, mm_idx or -1, side, trader, counterparty)
        self.activated = set()
        self._used = set()

    def wallet(self, entity, role):
        while True:
            a = "TSYN" + "".join(self.rng.choice(B58, 30))
            if a not in self._used:
                break
        self._used.add(a)
        self.wallets.append((a, entity, role))
        return a

    def account(self, entity, operator=None):
        op = operator or OPERATORS[self.rng.integers(len(OPERATORS))]
        a = f"{OP_CODE[op]}-SYN-{len(self.accounts):05d}"
        self.accounts.append((a, entity, op))
        return a

    def activate(self, ts, funder, wallet):
        """TRON accounts must receive TRX before first use; who pays for that is a clustering clue."""
        if wallet not in self.activated:
            self.activated.add(wallet)
            self.chain.append((ts - self.rng.uniform(60, 3600), "TRX", funder, wallet, 1.1))

    def send(self, ts, src, dst, amount):
        self.chain.append((ts, "USDT", src, dst, round(float(amount), 2)))
        return len(self.chain) - 1

    def pay(self, ts, src, dst, tzs):
        self.mm.append((ts, src, dst, int(round(tzs, -1))))
        return len(self.mm) - 1

    def daytime(self, day):
        """Seconds since START, mostly in waking hours (EAT)."""
        return day * 86400 + float(np.clip(self.rng.normal(14, 3.5), 6.5, 23.5)) * 3600 + self.rng.uniform(0, 60)


def make_phase2_world(out_dir, days=60, n_users=900, n_traders=18, n_mules=10, n_victims=60,
                      decoy_factor=1.0, timing_scale=1.0, fee_scale=1.0, seed=0):
    rng = np.random.default_rng(seed)
    W = _World(rng)
    rate = 2690 * np.exp(np.cumsum(rng.normal(0, 0.002, days)))     # daily USD/TZS (synthetic walk)

    hot = [W.wallet(f"exchange-{i}", "hot_wallet") for i in range(2)]
    deposit = {}

    def deposit_addr(entity, ex, ts):
        if (entity, ex) not in deposit:
            deposit[(entity, ex)] = W.wallet(f"exchange-{ex}", "deposit")
            W.activate(ts, hot[ex], deposit[(entity, ex)])
        return deposit[(entity, ex)]

    def first_use(ts, wallets, w):
        # first wallet is bought/withdrawn from an exchange; extra wallets are usually funded by the first
        if w == wallets[0] or rng.random() < 0.35:
            W.activate(ts, hot[rng.integers(2)], w)
        else:
            W.activate(ts, wallets[0], w)

    users = []
    for u in range(n_users):
        e = f"user-{u:04d}"
        ws = [W.wallet(e, "user") for _ in range(rng.choice([1, 2, 3], p=[.80, .17, .03]))]
        users.append((e, ws, W.account(e) if rng.random() < 0.85 else None))
    traders = []
    for t in range(n_traders):
        e = f"trader-{t:02d}"
        ws = [W.wallet(e, "trader") for _ in range(rng.choice([1, 2], p=[.7, .3]))]
        ops = rng.choice(OPERATORS, rng.choice([1, 2], p=[.6, .4]), replace=False)
        traders.append((e, ws, [W.account(e, op) for op in ops]))
        for w in ws:
            W.activate(0, hot[rng.integers(2)], w)
    scam = [W.wallet("scam-ring", "scam_collection") for _ in range(5)]
    for w in scam:
        W.activate(0, hot[rng.integers(2)], w)
    mules = []
    for m in range(n_mules):
        e = f"mule-{m:02d}"
        ws = [W.wallet(e, "mule") for _ in range(rng.choice([1, 2]))]
        mules.append((e, ws, W.account(e)))
    merchants = [W.account(f"merchant-{i:03d}") for i in range(200)]
    user_mm = [u for u in users if u[2]]
    contacts = [rng.choice(n_users, rng.integers(3, 9), replace=False) for _ in range(n_users)]
    victims = rng.choice(len(users), n_victims, replace=False)

    def trade(day, trader, ce, cw, cacc, side, usdt=None, after=0.0):
        te, tws, taccs = trader
        tw, ta = tws[rng.integers(len(tws))], taccs[rng.integers(len(taccs))]
        if usdt is None:
            usdt = rng.choice(USDT_SIZES, p=USDT_P) * (1 if rng.random() < .75 else rng.uniform(.8, 1.2))
        fee = rng.uniform(0.005, 0.03) * fee_scale
        delay = rng.uniform(1, 20) * 60 * timing_scale
        t = max(W.daytime(day), after + rng.uniform(10, 240) * 60)
        r = rate[min(int(t // 86400), len(rate) - 1)]
        settled_by_mm = rng.random() > 0.08            # some trades settle by bank or cash: no record
        if side == "sell":                             # counterparty sells USDT, trader pays shillings
            c = W.send(t, cw, tw, usdt)
            m = W.pay(t + delay, ta, cacc, usdt * r * (1 - fee)) if settled_by_mm else -1
        else:                                          # counterparty buys USDT, pays shillings first
            m = W.pay(t, cacc, ta, usdt * r * (1 + fee)) if settled_by_mm else -1
            c = W.send(t + delay, tw, cw, usdt)
        W.trades.append((c, m, side, te, ce))

    scam_balance = {w: 0.0 for w in scam}
    for d in range(days):
        r = rate[d]
        # ordinary P2P trades
        for tr in traders:
            for _ in range(rng.poisson(6)):
                ue, uws, uacc = user_mm[rng.integers(len(user_mm))]
                uw = uws[rng.integers(len(uws))]
                first_use(W.daytime(d), uws, uw)
                trade(d, tr, ue, uw, uacc, "sell" if rng.random() < .5 else "buy")
        # user-to-user transfers, mostly within each person's small circle of contacts
        for _ in range(rng.poisson(250)):
            a = rng.integers(len(users))
            b = contacts[a][rng.integers(len(contacts[a]))] if rng.random() < .9 else rng.integers(len(users))
            if a == b:
                continue
            wa, wb = users[a][1][0], users[b][1][rng.integers(len(users[b][1]))]
            t = W.daytime(d)
            first_use(t, users[a][1], wa); first_use(t, users[b][1], wb)
            W.send(t, wa, wb, max(1, rng.lognormal(np.log(60), .9)))
        # exchange deposits (swept to the hot wallet) and withdrawals
        for _ in range(rng.poisson(50)):
            ue, uws, _ = users[rng.integers(len(users))]
            uw, ex, t = uws[rng.integers(len(uws))], rng.integers(2), W.daytime(d)
            first_use(t, uws, uw)
            dep, amt = deposit_addr(ue, ex, t), max(5, rng.lognormal(np.log(150), .8))
            W.send(t, uw, dep, amt)
            W.send(t + rng.uniform(5, 120) * 60, dep, hot[ex], amt)
        for _ in range(rng.poisson(50)):
            ue, uws, _ = users[rng.integers(len(users))]
            uw, t = uws[rng.integers(len(uws))], W.daytime(d)
            first_use(t, uws, uw)
            W.send(t, hot[rng.integers(2)], uw, max(5, rng.lognormal(np.log(150), .8)))
        # traders restock from exchanges and deposit surplus
        for te, tws, _ in traders:
            for _ in range(rng.poisson(1)):
                W.send(W.daytime(d), hot[rng.integers(2)], tws[rng.integers(len(tws))], rng.uniform(2000, 8000))
            if rng.random() < 0.4:
                ex, t = rng.integers(2), W.daytime(d)
                dep, amt = deposit_addr(te, ex, t), rng.uniform(1000, 5000)
                W.send(t, tws[rng.integers(len(tws))], dep, amt)
                W.send(t + rng.uniform(5, 120) * 60, dep, hot[ex], amt)
        # scam: victims pay collection wallets; every third day the ring pays mules, who cash out
        for _ in range(rng.poisson(4)):
            ue, uws, _ = users[victims[rng.integers(n_victims)]]
            cw, amt, t = scam[rng.integers(len(scam))], max(50, rng.lognormal(np.log(350), .7)), W.daytime(d)
            first_use(t, uws, uws[0])
            W.send(t, uws[0], cw, amt)
            scam_balance[cw] += amt
        if d % 3 == 2:
            for cw in scam:
                if scam_balance[cw] < 100:
                    continue
                for part in scam_balance[cw] * rng.dirichlet(np.ones(rng.integers(1, 4))):
                    me, mws, macc = mules[rng.integers(n_mules)]
                    t = W.daytime(d)
                    W.activate(t, hot[rng.integers(2)], mws[0])
                    W.send(t, cw, mws[0], part)
                    src, ready = mws[0], t
                    if len(mws) > 1 and rng.random() < 0.5:          # hop to the mule's second wallet
                        W.activate(t, mws[0], mws[1])
                        ready = t + rng.uniform(10, 90) * 60
                        W.send(ready, mws[0], mws[1], part)
                        src = mws[1]
                    left = part
                    if rng.random() < 0.15:                          # some goes to an exchange instead
                        ex, cut = rng.integers(2), round(part * rng.uniform(.2, .5), 2)
                        dep = deposit_addr(me, ex, t)
                        W.send(t + 3600, src, dep, cut)
                        W.send(t + 3600 + rng.uniform(5, 120) * 60, dep, hot[ex], cut)
                        left -= cut
                    while left >= 100:                               # sell in round chunks to P2P traders
                        chunk = min(left, 50 * rng.integers(2, 21))
                        trade(min(days - 1, d + rng.integers(0, 3)), traders[rng.integers(n_traders)],
                              me, src, macc, "sell", usdt=chunk, after=ready)
                        left -= chunk
                scam_balance[cw] = 0.0
        # mobile-money traffic on trader accounts that has nothing to do with crypto (decoys)
        for _, _, taccs in traders:
            for ta in taccs:
                for _ in range(rng.poisson(12 * decoy_factor)):
                    other = merchants[rng.integers(len(merchants))] if rng.random() < .6 else \
                        user_mm[rng.integers(len(user_mm))][2]
                    tzs = rng.choice(USDT_SIZES, p=USDT_P) * r * rng.uniform(.97, 1.03) if rng.random() < .5 \
                        else rng.lognormal(np.log(40000), .9)
                    t = W.daytime(d)
                    W.pay(t, ta, other, tzs) if rng.random() < .5 else W.pay(t, other, ta, tzs)
        # background mobile-money traffic
        accs = [a for a, _, _ in W.accounts]
        for _ in range(rng.poisson(300)):
            a, b = rng.choice(len(accs), 2, replace=False)
            W.pay(W.daytime(d), accs[a], accs[b], rng.lognormal(np.log(30000), 1.0))

    return _write(W, out_dir, rate, traders, scam, rng)


def _write(W, out_dir, rate, traders, scam, rng):
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = lambda s: START + pd.to_timedelta(np.asarray(s, dtype=float), unit="s")

    chain = pd.DataFrame(W.chain, columns=["t", "asset", "src", "dst", "amount"])
    chain["idx"] = np.arange(len(chain))
    chain = chain.sort_values("t", kind="stable").reset_index(drop=True)
    chain["tx_id"] = [f"syn{rng.integers(1 << 60):015x}" for _ in range(len(chain))]
    chain["ts"] = ts(chain["t"])
    chain_id = dict(zip(chain["idx"], chain["tx_id"]))
    chain[["tx_id", "ts", "asset", "src", "dst", "amount"]].to_csv(out_dir / "chain_transfers.csv", index=False)

    op_of = {a: op for a, _, op in W.accounts}
    mm = pd.DataFrame(W.mm, columns=["t", "src", "dst", "amount_tzs"])
    mm["idx"] = np.arange(len(mm))
    mm = mm.sort_values("t", kind="stable").reset_index(drop=True)
    mm["mm_id"] = [f"MMSYN{i:08d}" for i in range(len(mm))]
    mm["ts"] = ts(mm["t"])
    mm["operator"] = mm["src"].map(op_of)            # network the payment was sent from
    mm["dst_operator"] = mm["dst"].map(op_of)
    mm_id = dict(zip(mm["idx"], mm["mm_id"]))
    mm[["mm_id", "ts", "operator", "dst_operator", "src", "dst", "amount_tzs"]].to_csv(out_dir / "mobile_money.csv", index=False)

    pd.DataFrame({"date": [(START + pd.Timedelta(days=i)).date() for i in range(len(rate))],
                  "usd_tzs": np.round(rate, 2)}).to_csv(out_dir / "fx_rates.csv", index=False)
    rows = [(te, "wallet", w) for te, ws, _ in traders for w in ws] + \
           [(te, "mm_account", a) for te, _, accs in traders for a in accs]
    pd.DataFrame(rows, columns=["trader_id", "kind", "identifier"]).to_csv(out_dir / "trader_directory.csv", index=False)
    reports = chain[chain["dst"].isin(scam) & (chain["asset"] == "USDT")].groupby("dst").size()
    reports.rename_axis("wallet").reset_index(name="reports").to_csv(out_dir / "reported_wallets.csv", index=False)

    pd.DataFrame(W.wallets, columns=["address", "entity", "role"]).to_csv(out_dir / "truth_wallets.csv", index=False)
    pd.DataFrame(W.accounts, columns=["account", "entity", "operator"]).to_csv(out_dir / "truth_accounts.csv", index=False)
    pd.DataFrame([(chain_id[c], mm_id.get(m, ""), s, t, e) for c, m, s, t, e in W.trades],
                 columns=["chain_tx", "mm_tx", "side", "trader", "counterparty"]
                 ).to_csv(out_dir / "truth_trades.csv", index=False)
    return out_dir
