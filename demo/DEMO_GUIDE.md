# Demo data and test guide

Everything here is **real, public blockchain data**: no invented transactions. The sanctioned addresses come
from the OFAC SDN list. The other addresses are public examples of a *pattern* (pass-through, mixing, exchange
activity), not allegations about their owners. Scores were measured on 11 Oct 2026; live chains keep moving, so
amounts and some scores will drift.

For a printable sheet of inputs to enter yourself (TRON, Ethereum, Bitcoin, cross-chain, contracts, mobile money,
each with High, Medium and Low examples), see `demo/TEST_DATA.pdf` (or `TEST_DATA.html` to copy addresses).

## 1. Start the demo

```bash
.venv/bin/python demo/seed_demo.py                                  # about 3 minutes, needs internet
PLATFORM_DB=data/demo.db .venv/bin/streamlit run app.py --server.port 8502
```

The seed builds `data/demo.db` from scratch each time it runs, and it never touches `data/platform.db`. It also
writes `demo/output/case_1_evidence_<date>.zip` and an altered copy, `…_TAMPERED.zip`.

| Account | Role | Can |
|---|---|---|
| `supervisor` | supervisor | everything: decide leads, close cases, remove watchlist entries, verify the audit chain and packs |
| `investigator` | investigator | investigate, open cases, attach leads, add to the watchlist |
| `reviewer` | viewer | read only |

Passwords are in `.streamlit/secrets.toml`.

## 2. What the seed creates

| Case | Subject | Expected |
|---|---|---|
| #1 Ethereum (Escalated) | `0x098B716B8Aaf21512996dC57EB0615e2383E2f96`, Ronin bridge exploiter (OFAC) | 100/100 High; 5 traced leads, all **Confirmed** by the demo rule (they are sanctioned too) |
| #2 TRON (Open) | `TTjHn8qNVxazB3UroiekGRPuM2w2GwvNbn`, OFAC-listed | 60/100 High (on the watchlist); 6 funding wallets: 2 exchanges **Dismissed**, 4 **Pending** for you |
| #3 Bitcoin (Open) | `34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo` | 20/100 Medium (CoinJoin); 4 funding addresses, all **Pending** |
| #4 Contract (Open) | `demo/contracts/01_reentrancy_SimpleDAO.sol` | 30/100 Medium; Slither `reentrancy-eth` (High impact) |
| #5 Cross-chain (Open) | Binance Ethereum hot wallet + a high-volume TRON wallet | dozens of High-confidence candidate hops (36–44 in our runs): they show how many *coincidental* matches two exchanges produce, which is why hops are leads, not proof |

The watchlist holds 15 OFAC SDN addresses (10 TRON, 2 Ethereum, 3 Bitcoin; `demo/watchlist_ofac_sample.csv`).
The demo rule decides only clear-cut leads: sanctioned, watchlisted or frozen leads are Confirmed, and exchanges
or large services are Dismissed. Everything else is left for a person to decide.

## 3. Addresses to try

**Ethereum** (Investigate → Ethereum wallets)

| Address | What it is | Expected |
|---|---|---|
| `0x8589427373D6D84E98730D7795D8f6f8731FDA16` | Tornado Cash donation address | 100 High: sanctioned, frozen, mixer, exposure flags |
| `0x098B716B8Aaf21512996dC57EB0615e2383E2f96` | Ronin bridge exploiter | 100 High: sanctioned, frozen, pass-through |
| `0x7F367cC41522cE07553e823bf3be79A889DEbe1B` | OFAC-listed address | 100 High: sanctioned, frozen |
| `0xd90e2f925DA726b50C4Ed8D0Fb90Ad053324F31b` | Tornado Cash Router (contract) | 100 High; **Contract audit** tab: verified source, solc 0.6.12, 39 files |
| `0x28C6c06298d514Db089934071355E5743bf21d60` | Binance hot wallet | 10 Low: "Likely exchange or large service" |
| `0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045` | Vitalik Buterin | 0 Low: no indicators (a clean control) |

**TRON / USDT** (Investigate → TRON wallets)

| Address | Expected |
|---|---|
| `TTjHn8qNVxazB3UroiekGRPuM2w2GwvNbn` | OFAC-listed: High through the watchlist (+60) in the demo database |
| `TEEYCuGDyeNkuDj4u6GQRXxXo3Nh29r2vP` | OFAC-listed, about 1.26 M USDT moved: High through the watchlist |
| `TXSsAGqvTMBtC5TRV4prdBjdh5ZMD2kwe1` | pattern example: 45 Medium (pass-through, round amounts, new wallet with large volume) |
| `TLRMGs4JEmo5uwZviEmL1DkAJWTd2kgi6J` | pattern example: 30 Medium (pass-through, new wallet with large volume) |
| `TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe` | high-volume service: Low, traced through as a service |

**Bitcoin** (Investigate → Bitcoin addresses)

| Address | Expected |
|---|---|
| `34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo` | 20 Medium: CoinJoin participation, with transaction links |
| `1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa` | Genesis address, 66 k+ dust transactions: 20 Medium (a CoinJoin output among them) |
| `bc1qm34lsc65zpw79lxes69zkqmk6ee3ewf0j77s3h` | Very large exchange cold wallet: 10 Low, "Likely exchange" |
| `123WBUDmSJv4GctdVEz6Qq6z8nXSKrJ4KX` | OFAC-listed: "Watchlisted" in the demo database |

**Bad input** (each should show a clear error, never a crash): `TTjHn8qNVxazB3UroiekGRPuM2w2GwvNbm` (TRON
checksum broken), `0x1234` (Ethereum too short), `bc1qnotanaddress` (Bitcoin), `hello` in the Overview lookup.

## 4. Test checklist

**Sign-in and roles**
1. A wrong password shows "Wrong username or password", and **Audit and custody** then lists a `failed sign-in`.
2. Sign in as `supervisor` with **My last case** selected: it opens a case.
3. Sign in as `reviewer`: Open case, Add to watchlist and lead decisions are disabled, with a reason shown.

**Investigation pages**
4. Ethereum: look up the Tornado donation address, then **Fund flow trace → Trace**. Graph nodes for mixers and exchanges are yellow and are not traced through.
5. Ethereum: look up the Tornado Router, then **Contract audit → Audit deployed contract**. Turning off "Only the contract's own file" adds the library findings.
6. TRON: look up `TEEYCu…`. It shows "Watchlisted", and its counterparties show exposure to it.
7. Bitcoin: look up `34xp4v…`. The **Risk indicators** tab lists the CoinJoin transactions with explorer links.
8. Cross-chain: run the Binance Ethereum wallet together with `TJDENs…`. You get candidate hops with a confidence level, plus a same-key check (no active twin expected).

**Smart-contract audit** (upload each file in `demo/contracts/`)

| File | Expected |
|---|---|
| `01_reentrancy_SimpleDAO.sol` | 30 Medium: `reentrancy-eth` |
| `02_overflow_BECToken.sol` | 0 Low: a **known miss**. Slither has no overflow detector for Solidity 0.4 (see the Phase 3 results) |
| `03_access_control_constructor.sol` | 0 Low: a **known miss** (wrongly named constructor) |
| `04_unchecked_call_KingOfTheEther.sol` | 100 High: `controlled-array-length`, `msg-value-in-nonpayable`, `unchecked-send` |
| `05_safe_Vault.sol` | 0 Low: the control sample, written defensively |

**Mobile money**
9. **Training sample** shows the matched payments and attribution links.
10. Import `demo/statements/statement_missing_column.csv` → "Statement is missing columns: counterparty_account".
11. Import `demo/statements/statement_bad_direction.csv` → "direction must be 'in' or 'out' on every row".

**Casework**
12. **Cases → #1**: check the Case graph (sanctioned leads), the Timeline and the Evidence pack tabs.
13. **Feedback loop test**, as `supervisor`: open case #3's **Review queue**. Confirm `34xp4v…`, `bc1qvjp8…` and `bc1qy08c…` (score 20), and dismiss `bc1q9g59…` and `bc1qm9gp…` (score 0). After the fifth decision the Bitcoin-address High threshold drops **from 50 to 20**, and the **Feedback loop** page shows the change and its reason.
14. Control test: in case #2, confirm three of the four pending score-35 TRON leads. That makes 5 decisions, all at score 35, with 3 confirmed and 2 dismissed. At 60% this misses the 80% target, so High correctly **stays at 50**, and the reason says so.
15. **Entity graph**: search `0x098b…`. You see the exploiter with its sanctioned leads.

**Governance**
16. **Audit and custody → Verify chain** reports the chain intact.
17. Tamper test: edit one audit entry behind the platform's back, then press Verify chain again. It reports the chain broken at #5. Re-run the seed afterwards.
    ```bash
    .venv/bin/python -c "import sqlite3; c=sqlite3.connect('data/demo.db'); c.execute(\"UPDATE audit SET detail='edited' WHERE id=5\"); c.commit()"
    ```
18. **Verify evidence pack**: upload `demo/output/case_1_evidence_*.zip`. It passes and is found in the custody register. Upload `…_TAMPERED.zip`: it fails on `report.html` and is not registered.
