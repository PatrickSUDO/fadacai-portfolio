"""Universe + sector mapping shared by all tests. Lists are hand-approximated (see README in output JSON)."""
import json, re
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[3]
LEDGER = str(_ROOT / 'research/trade-ledger.jsonl')
TL_PY = str(_ROOT / 'tools/trade_ledger.py')
BENCH_JSON = str(_ROOT / 'research/bench.json')

def semi_ai():
    src = open(TL_PY).read()
    m = re.search(r"SEMI_AI\s*=\s*\{(.*?)\}", src, re.S)
    return set(re.findall(r'"([A-Z.]+)"', m.group(1)))

HOLDINGS = "AMAT AMD ANET AVGO BE CLS CRM CRWD DDOG DIOD GLD LITE MU NET NVDA PLTR PWR SNPS TWLO VOO XLE".split()
EXITS_2026 = "MYRG CRDO ONTO STRL COHR ON ARM MRVL HWM LRCX GOOGL TSLA META KTOS USAR ALAB FSLY OKLO CCJ NEM".split()
# approximate top-25 SMH constituents (2026), hand-listed
SMH_TOP25 = "NVDA TSM AVGO AMD ASML TXN QCOM MU AMAT LRCX INTC KLAC ADI MRVL ARM SNPS CDNS NXPI MCHP ON MPWR TER STM SWKS ENTG".split()
# approximate top-20 IGV constituents (2026), hand-listed
IGV_TOP20 = "MSFT ORCL CRM NOW ADBE PLTR INTU PANW CRWD SNPS CDNS ADSK WDAY FTNT DDOG TEAM ROP ZS HUBS APP".split()
SOFTWARE = set("CRM CRWD DDOG NET PLTR TWLO FSLY NOW MNDY HUBS PAYC WDAY DOCU ZS OKTA MDB MSFT ORCL ADBE INTU PANW ADSK FTNT TEAM ROP APP SNOW".split())
EXTRA_SEMI = set("TXN ADI NXPI MCHP MPWR STM SWKS ENTG ALAB NVMI TSM ASML".split())
ETFS = {"SMH", "IGV", "SPY", "GLD", "VOO", "XLE", "SGOV", "BIL"}

def bench_names():
    d = json.load(open(BENCH_JSON))
    return list(d.get("L1", [])) + list(d.get("L2", []))

def sector_etf(sym):
    s = sym.upper()
    if s in semi_ai() or s in EXTRA_SEMI:
        return "SMH"
    if s in SOFTWARE:
        return "IGV"
    return "SPY"

def test2_universe():
    u = []
    for lst in (HOLDINGS, EXITS_2026, bench_names(), SMH_TOP25, IGV_TOP20):
        for s in lst:
            if s not in u and s not in ETFS:
                u.append(s)
    return u

def ledger_sold_symbols():
    syms = set()
    for line in open(LEDGER):
        r = json.loads(line)
        if r["side"] == "SOLD" and not r.get("is_option") and r["date"] >= "2026-01-01":
            syms.add(r["symbol"])
    return syms - ETFS

if __name__ == "__main__":
    print("SEMI_AI", sorted(semi_ai()))
    print("test2 universe", len(test2_universe()), test2_universe())
    print("ledger sold", sorted(ledger_sold_symbols()))
