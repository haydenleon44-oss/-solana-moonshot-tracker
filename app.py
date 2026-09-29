import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timezone
from supabase import create_client

# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="Solana Early Radar",
    page_icon="🔥",
    layout="wide"
)

st.title("🔥 Solana Early Radar")
st.caption(
    "Early-launch detection • 30-second momentum tracking • "
    "acceleration & deterioration monitoring"
)

# ============================================================
# SETTINGS
# ============================================================

BASE = "https://api.dexscreener.com"

DISCOVERY_URLS = [
    f"{BASE}/token-profiles/latest/v1",
    f"{BASE}/token-profiles/recent-updates/v1",
    f"{BASE}/community-takeovers/latest/v1",
    f"{BASE}/token-boosts/latest/v1",
    f"{BASE}/token-boosts/top/v1",
]

TOKEN_URL = f"{BASE}/latest/dex/tokens/{{}}"

MAX_SCAN = 75
MAX_HISTORY = 300

# ============================================================
# DATABASE
# ============================================================

@st.cache_resource
def get_db():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SECRET_KEY"]
    )

db = get_db()

# ============================================================
# HTTP
# ============================================================

@st.cache_resource
def get_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "SolanaEarlyRadar/5.0"
    })
    return s

http = get_session()


def get_json(url):

    for attempt in range(3):

        try:
            r = http.get(url, timeout=10)

            if r.status_code == 429:
                time.sleep(1 + attempt)
                continue

            r.raise_for_status()
            return r.json()

        except requests.RequestException:

            if attempt == 2:
                return None

            time.sleep(0.5)

    return None

# ============================================================
# HELPERS
# ============================================================

def n(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def clamp(x, low, high):
    return max(low, min(high, x))


def now():
    return datetime.now(timezone.utc)


def parse_date(value):

    if not value:
        return None

    try:
        dt = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt

    except Exception:
        return None


def age_minutes(timestamp):

    if not timestamp:
        return 999999

    try:
        created = datetime.fromtimestamp(
            float(timestamp) / 1000,
            timezone.utc
        )

        return max(
            0,
            (now() - created).total_seconds() / 60
        )

    except Exception:
        return 999999


def age_label(minutes):

    if minutes >= 999999:
        return "?"

    if minutes < 1:
        return "<1m"

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes / 60:.1f}h"

    return f"{minutes / 1440:.1f}d"


def pct(old, new):

    old = n(old)
    new = n(new)

    if old <= 0:
        return 0.0

    return ((new - old) / old) * 100

# ============================================================
# DISCOVERY
# ============================================================

@st.cache_data(ttl=60)
def discover():

    addresses = []
    seen = set()

    for url in DISCOVERY_URLS:

        data = get_json(url)

        if not data:
            continue

        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list):
            continue

        for item in data:

            if not isinstance(item, dict):
                continue

            if item.get("chainId") != "solana":
                continue

            address = item.get("tokenAddress")

            if address and address not in seen:
                seen.add(address)
                addresses.append(address)

    return addresses

# ============================================================
# EXISTING HISTORY
# ============================================================

def load_history():

    try:
        result = (
            db.table("token_history")
            .select("*")
            .order("detected_at", desc=True)
            .limit(MAX_HISTORY)
            .execute()
        )

        return result.data or []

    except Exception:
        return []


def load_previous(address):

    try:
        result = (
            db.table("token_snapshots")
            .select("*")
            .eq("address", address)
            .order("recorded_at", desc=True)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception:
        pass

    return None

# ============================================================
# DEX PAIR
# ============================================================

def best_pair(address):

    data = get_json(
        TOKEN_URL.format(address)
    )

    if not data:
        return None

    pairs = data.get("pairs") or []

    pairs = [
        p for p in pairs
        if p.get("chainId") == "solana"
    ]

    if not pairs:
        return None

    # Prefer pair with greatest real liquidity.
    return max(
        pairs,
        key=lambda p: n(
            (p.get("liquidity") or {}).get("usd")
        )
    )

# ============================================================
# ANALYSIS
# ============================================================

def analyze(address, pair, previous):

    token = pair.get("baseToken") or {}

    symbol = token.get("symbol") or "UNKNOWN"

    price = n(pair.get("priceUsd"))

    market_cap = n(
        pair.get("marketCap") or pair.get("fdv")
    )

    liquidity = n(
        (pair.get("liquidity") or {}).get("usd")
    )

    volume = pair.get("volume") or {}

    volume5 = n(volume.get("m5"))
    volume1h = n(volume.get("h1"))

    changes = pair.get("priceChange") or {}

    change5 = n(changes.get("m5"))
    change1h = n(changes.get("h1"))

    transactions = pair.get("txns") or {}

    m5 = transactions.get("m5") or {}
    h1 = transactions.get("h1") or {}

    buys5 = int(n(m5.get("buys")))
    sells5 = int(n(m5.get("sells")))

    buys1h = int(n(h1.get("buys")))
    sells1h = int(n(h1.get("sells")))

    trades5 = buys5 + sells5
    trades1h = buys1h + sells1h

    buy_ratio = (
        buys5 / trades5
        if trades5 > 0
        else 0
    )

    buy_ratio1h = (
        buys1h / trades1h
        if trades1h > 0
        else 0
    )

    age = age_minutes(
        pair.get("pairCreatedAt")
    )

    liq_ratio = (
        liquidity / market_cap
        if market_cap > 0
        else 0
    )

    # --------------------------------------------------------
    # PREVIOUS OBSERVATION
    # --------------------------------------------------------

    prev_price = n(
        previous.get("price")
        if previous else 0
    )

    prev_mc = n(
        previous.get("market_cap")
        if previous else 0
    )

    prev_liq = n(
        previous.get("liquidity")
        if previous else 0
    )

    prev_volume = n(
        previous.get("volume_5m")
        if previous else 0
    )

    prev_buy_ratio = n(
        previous.get("buy_ratio")
        if previous else 0
    )

    prev_momentum = n(
        previous.get("momentum")
        if previous else 0
    )

    price_delta = (
        pct(prev_price, price)
        if prev_price > 0 else 0
    )

    mc_delta = (
        pct(prev_mc, market_cap)
        if prev_mc > 0 else price_delta
    )

    liq_delta = (
        pct(prev_liq, liquidity)
        if prev_liq > 0 else 0
    )

    volume_delta = (
        pct(prev_volume, volume5)
        if prev_volume > 0 else 0
    )

    buyer_delta = (
        (buy_ratio - prev_buy_ratio) * 100
        if previous else 0
    )

    # ========================================================
    # EARLY MOMENTUM SCORE
    # ========================================================

    early = 0.0

    # Age is extremely important for this score.
    if age <= 2:
        early += 22

    elif age <= 5:
        early += 19

    elif age <= 10:
        early += 15

    elif age <= 20:
        early += 10

    elif age <= 60:
        early += 4

    # Actual transaction activity.
    if trades5 >= 100:
        early += 18

    elif trades5 >= 50:
        early += 15

    elif trades5 >= 20:
        early += 11

    elif trades5 >= 8:
        early += 6

    # Buyer pressure.
    if trades5 >= 5:

        if buy_ratio >= .72:
            early += 17

        elif buy_ratio >= .64:
            early += 13

        elif buy_ratio >= .57:
            early += 8

        elif buy_ratio < .40:
            early -= 12

    # Early volume.
    if volume5 >= 50000:
        early += 15

    elif volume5 >= 20000:
        early += 12

    elif volume5 >= 7500:
        early += 9

    elif volume5 >= 2500:
        early += 5

    elif volume5 >= 500:
        early += 2

    # Price behavior.
    if 2 <= change5 <= 20:
        early += 12

    elif 20 < change5 <= 50:
        early += 9

    elif 50 < change5 <= 100:
        early += 5

    # Avoid blindly rewarding absurd first candle pumps.
    elif change5 > 150:
        early -= 10

    if change5 < -10:
        early -= 15

    # Liquidity.
    if liquidity >= 25000:
        early += 10

    elif liquidity >= 10000:
        early += 7

    elif liquidity >= 5000:
        early += 4

    elif liquidity < 2000:
        early -= 15

    # --------------------------------------------------------
    # ACCELERATION BETWEEN 30 SECOND OBSERVATIONS
    # --------------------------------------------------------

    acceleration = 0

    if previous:

        if price_delta >= 5:
            acceleration += 12

        elif price_delta >= 2:
            acceleration += 7

        elif price_delta > 0:
            acceleration += 3

        if mc_delta >= 5:
            acceleration += 8

        elif mc_delta >= 2:
            acceleration += 4

        if volume_delta >= 20:
            acceleration += 10

        elif volume_delta >= 8:
            acceleration += 5

        if buyer_delta >= 8:
            acceleration += 10

        elif buyer_delta >= 3:
            acceleration += 5

        if liq_delta >= 5:
            acceleration += 7

        elif liq_delta >= 2:
            acceleration += 3

        if price_delta <= -5:
            acceleration -= 15

        if buyer_delta <= -10:
            acceleration -= 12

        if liq_delta <= -15:
            acceleration -= 20

    early += acceleration

    early_score = int(
        clamp(early, 0, 100)
    )

    # ========================================================
    # RISK
    # ========================================================

    risk = 35

    # New coins are inherently risky.
    if age <= 5:
        risk += 15

    elif age <= 15:
        risk += 8

    if liquidity < 2000:
        risk += 45

    elif liquidity < 5000:
        risk += 30

    elif liquidity < 10000:
        risk += 15

    elif liquidity >= 50000:
        risk -= 10

    if market_cap > 0:

        if liq_ratio < .02:
            risk += 25

        elif liq_ratio < .05:
            risk += 12

        elif liq_ratio >= .20:
            risk -= 8

    if trades5 >= 8 and buy_ratio < .35:
        risk += 25

    if change5 > 150:
        risk += 20

    if change5 < -25:
        risk += 25

    if previous and liq_delta <= -20:
        risk += 30

    risk = int(
        clamp(risk, 0, 100)
    )

    # ========================================================
    # DETERIORATION
    # ========================================================

    deterioration = 0

    if change5 <= -5:
        deterioration += 15

    if change5 <= -15:
        deterioration += 20

    if trades5 >= 8 and sells5 > buys5:
        deterioration += 15

    if trades5 >= 8 and buy_ratio < .40:
        deterioration += 15

    if previous:

        if price_delta <= -5:
            deterioration += 20

        if buyer_delta <= -8:
            deterioration += 15

        if liq_delta <= -10:
            deterioration += 20

        if volume_delta <= -25:
            deterioration += 10

    deterioration = int(
        clamp(deterioration, 0, 100)
    )

    # ========================================================
    # MOMENTUM
    # ========================================================

    momentum = early_score

    if age > 60:

        # Older tokens receive less of the age bonus.
        momentum = int(
            clamp(
                early_score - 10,
                0,
                100
            )
        )

    momentum_delta = (
        momentum - prev_momentum
        if previous else 0
    )

    # ========================================================
    # SETUP SCORE
    # ========================================================

    setup = (
        momentum * .60
        + (100 - risk) * .25
        + min(100, liquidity / 500) * .15
    ) / 10

    setup = round(
        clamp(setup, 1, 10),
        1
    )

    # ========================================================
    # STAGE
    # ========================================================

    if risk >= 90 or liquidity < 1500:

        stage = "⛔ AVOID"

    elif deterioration >= 65:

        stage = "🔴 EXIT WARNING"

    elif deterioration >= 45:

        stage = "📉 FADING"

    # NEW COIN RULES
    elif age <= 15:

        if (
            early_score >= 75
            and trades5 >= 10
            and buy_ratio >= .58
            and liquidity >= 5000
        ):
            stage = "🚀 EARLY ACCELERATION"

        elif (
            early_score >= 55
            and trades5 >= 5
            and liquidity >= 3000
        ):
            stage = "🔥 EARLY MOMENTUM"

        else:
            stage = "🆕 JUST LAUNCHED"

    # DEVELOPING TOKEN
    elif age <= 60:

        if (
            setup >= 7
            and momentum >= 70
            and risk <= 65
        ):
            stage = "🟢 STRONG SETUP"

        elif (
            momentum >= 55
            and risk <= 75
        ):
            stage = "🟡 DEVELOPING"

        else:
            stage = "⚪ WAIT"

    # OLDER TOKEN
    else:

        if (
            setup >= 7.5
            and momentum >= 70
            and risk <= 55
            and liquidity >= 10000
        ):
            stage = "🟢 STRONG SETUP"

        elif (
            setup >= 6
            and momentum >= 55
            and risk <= 70
        ):
            stage = "🟡 WATCH"

        else:
            stage = "⚪ WAIT"

    # ========================================================
    # TREND
    # ========================================================

    if not previous:
        trend = "NEW"

    elif acceleration >= 15:
        trend = "ACCELERATING"

    elif acceleration >= 5:
        trend = "IMPROVING"

    elif deterioration >= 45:
        trend = "DETERIORATING"

    else:
        trend = "STEADY"

    return {
        "Token": symbol,
        "Address": address,
        "Stage": stage,
        "Trend": trend,

        "Early Score": early_score,
        "Setup": setup,
        "Risk": risk,
        "Deterioration": deterioration,

        "Age": age_label(age),
        "Age Min": round(age, 1),

        "Price": price,
        "Market Cap": round(market_cap),
        "Liquidity": round(liquidity),

        "5m Volume": round(volume5),
        "5m Trades": trades5,
        "Buys": buys5,
        "Sells": sells5,
        "Buy %": round(buy_ratio * 100, 1),

        "5m Price %": round(change5, 2),
        "1h Price %": round(change1h, 2),

        "30s Price Δ": round(price_delta, 2),
        "MC Δ": round(mc_delta, 2),
        "Volume Δ": round(volume_delta, 1),
        "Buy Pressure Δ": round(buyer_delta, 1),
        "Liquidity Δ": round(liq_delta, 1),

        "Momentum": momentum,
        "Momentum Δ": round(momentum_delta, 1),
    }

# ============================================================
# SAVE SNAPSHOT
# ============================================================

def save_snapshot(c):

    try:

        db.table("token_snapshots").insert({
            "address": c["Address"],
            "token": c["Token"],
            "recorded_at": now().isoformat(),

            "price": float(c["Price"]),
            "market_cap": float(c["Market Cap"]),
            "liquidity": float(c["Liquidity"]),

            "volume_5m": float(c["5m Volume"]),
            "buys_5m": int(c["Buys"]),
            "sells_5m": int(c["Sells"]),
            "buy_ratio": float(c["Buy %"]) / 100,

            "price_change_5m": float(c["5m Price %"]),

            "momentum": int(c["Momentum"]),
            "risk": int(c["Risk"]),
            "deterioration": int(c["Deterioration"]),
            "setup_score": float(c["Setup"]),
        }).execute()

    except Exception:
        pass

# ============================================================
# FIRST DETECTION
# ============================================================

def save_new_token(c, known):

    if c["Address"] in known:
        return

    try:

        db.table("token_history").insert({
            "address": c["Address"],
            "token": c["Token"],
            "detected_at": now().isoformat(),

            "start_price": float(c["Price"]),
            "start_moonshot": float(c["Setup"]),
            "start_momentum": int(c["Momentum"]),
            "start_risk": int(c["Risk"]),
            "start_status": c["Stage"],

            "latest_return": 0,
            "best_return": 0,
            "worst_return": 0,

            "last_price": float(c["Price"]),
            "last_updated": now().isoformat(),
        }).execute()

        known.add(c["Address"])

    except Exception:
        pass

# ============================================================
# PERFORMANCE
# ============================================================

def update_history(c, record):

    if not record:
        return

    start_price = n(record.get("start_price"))
    detected = parse_date(record.get("detected_at"))

    if start_price <= 0 or not detected:
        return

    current = n(c["Price"])

    if current <= 0:
        return

    result = round(
        pct(start_price, current),
        2
    )

    elapsed = (
        now() - detected
    ).total_seconds() / 60

    update = {
        "latest_return": result,

        "best_return": max(
            n(record.get("best_return")),
            result
        ),

        "worst_return": min(
            n(record.get("worst_return")),
            result
        ),

        "last_price": current,
        "last_updated": now().isoformat(),
    }

    checkpoints = {
        "return_5m": 5,
        "return_15m": 15,
        "return_30m": 30,
        "return_1h": 60,
        "return_6h": 360,
        "return_24h": 1440,
    }

    for column, minute in checkpoints.items():

        if (
            elapsed >= minute
            and record.get(column) is None
        ):
            update[column] = result

    try:

        (
            db.table("token_history")
            .update(update)
            .eq("address", c["Address"])
            .execute()
        )

    except Exception:
        pass

# ============================================================
# SCAN POOL
# ============================================================

def make_pool():

    discovered = discover()
    history = load_history()

    addresses = []
    seen = set()

    # New discoveries always first.
    for address in discovered:

        if address not in seen:
            seen.add(address)
            addresses.append(address)

    # Continue following previously detected coins.
    for row in history:

        address = row.get("address")
        detected = parse_date(row.get("detected_at"))

        if not address or not detected:
            continue

        hours = (
            now() - detected
        ).total_seconds() / 3600

        if hours <= 24 and address not in seen:
            seen.add(address)
            addresses.append(address)

    return addresses

# ============================================================
# LIVE SCAN
# ============================================================

def scan():

    pool = make_pool()

    if "rotation" not in st.session_state:
        st.session_state.rotation = 0

    if not pool:
        return pd.DataFrame(), 0

    start = st.session_state.rotation % len(pool)

    rotated = (
        pool[start:]
        + pool[:start]
    )

    selected = rotated[:MAX_SCAN]

    st.session_state.rotation = (
        start + MAX_SCAN
    ) % len(pool)

    history = load_history()

    history_map = {
        r.get("address"): r
        for r in history
        if r.get("address")
    }

    known = set(history_map.keys())

    rows = []

    for address in selected:

        pair = best_pair(address)

        if not pair:
            continue

        previous = load_previous(address)

        try:
            coin = analyze(
                address,
                pair,
                previous
            )
        except Exception:
            continue

        if coin["Price"] <= 0:
            continue

        rows.append(coin)

        save_snapshot(coin)
        save_new_token(coin, known)

        update_history(
            coin,
            history_map.get(address)
        )

    if not rows:
        return pd.DataFrame(), len(pool)

    df = pd.DataFrame(rows)

    df = (
        df
        .drop_duplicates("Address")
        .sort_values(
            ["Early Score", "Setup"],
            ascending=False
        )
    )

    return df, len(pool)

# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header("📡 Scanner")

st.sidebar.success(
    "LIVE — 30 SECOND MONITORING"
)

st.sidebar.write(
    "New launches receive priority."
)

if st.sidebar.button(
    "🔄 Force Discovery Refresh",
    use_container_width=True
):
    st.cache_data.clear()
    st.rerun()

# ============================================================
# LIVE DASHBOARD
# ============================================================

@st.fragment(run_every="30s")
def dashboard():

    scan_time = now()

    with st.spinner(
        "Searching for new Solana launches..."
    ):
        df, pool_size = scan()

    st.caption(
        "Last scan: "
        + scan_time.strftime("%H:%M:%S UTC")
        + " • automatically rescans every 30 seconds"
    )

    if df.empty:

        st.warning(
            "No usable contracts returned this rotation."
        )

        return

    just_launched = df[
        df["Age Min"] <= 15
    ].copy()

    early = df[
        df["Stage"].isin([
            "🚀 EARLY ACCELERATION",
            "🔥 EARLY MOMENTUM"
        ])
    ].copy()

    strong = df[
        df["Stage"] == "🟢 STRONG SETUP"
    ].copy()

    danger = df[
        df["Stage"].isin([
            "🔴 EXIT WARNING",
            "📉 FADING",
            "⛔ AVOID"
        ])
    ].copy()

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "🆕 ≤15m Old",
        len(just_launched)
    )

    c2.metric(
        "🔥 Early Signals",
        len(early)
    )

    c3.metric(
        "🟢 Strong",
        len(strong)
    )

    c4.metric(
        "🔴 Deteriorating",
        len(danger)
    )

    c5.metric(
        "📡 Pool",
        pool_size
    )

    # ========================================================
    # JUST LAUNCHED
    # ========================================================

    st.subheader(
        "🔥 JUST LAUNCHED — Early Detection"
    )

    st.caption(
        "Tokens 15 minutes old or younger. "
        "These are extremely speculative and can fail quickly."
    )

    if just_launched.empty:

        st.info(
            "No ≤15-minute launches detected in this rotation."
        )

    else:

        just_launched = just_launched.sort_values(
            [
                "Early Score",
                "Age Min"
            ],
            ascending=[
                False,
                True
            ]
        )

        st.dataframe(
            just_launched[
                [
                    "Token",
                    "Stage",
                    "Trend",
                    "Age",
                    "Early Score",
                    "Risk",
                    "Market Cap",
                    "Liquidity",
                    "5m Volume",
                    "5m Trades",
                    "Buy %",
                    "5m Price %",
                    "30s Price Δ",
                    "MC Δ",
                    "Buy Pressure Δ",
                    "Address",
                ]
            ].head(25),
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # EARLY MOMENTUM
    # ========================================================

    st.subheader(
        "🚀 Early Momentum Leaders"
    )

    if early.empty:

        st.write(
            "Nothing has confirmed an early momentum signal yet."
        )

    else:

        for _, coin in early.head(10).iterrows():

            st.success(
                f"""
### {coin['Token']} — {coin['Stage']}

**Age:** {coin['Age']}  
**Early Momentum:** {coin['Early Score']}/100  
**Setup:** {coin['Setup']}/10  
**Risk:** {coin['Risk']}/100

Market cap: **${coin['Market Cap']:,}**  
Liquidity: **${coin['Liquidity']:,}**  
5m volume: **${coin['5m Volume']:,}**

Buy share: **{coin['Buy %']}%**  
5m trades: **{coin['5m Trades']}**

30s price change: **{coin['30s Price Δ']:+.2f}%**  
Market-cap change: **{coin['MC Δ']:+.2f}%**  
Buy-pressure change: **{coin['Buy Pressure Δ']:+.1f} pts**  
Liquidity change: **{coin['Liquidity Δ']:+.1f}%**

Contract:

`{coin['Address']}`

**Fomo:** search this contract manually before trading.
"""
            )

    # ========================================================
    # STRONG SETUPS
    # ========================================================

    st.subheader(
        "🟢 Confirmed Momentum Setups"
    )

    if strong.empty:

        st.write(
            "No older setup currently meets confirmation requirements."
        )

    else:

        st.dataframe(
            strong[
                [
                    "Token",
                    "Stage",
                    "Trend",
                    "Age",
                    "Setup",
                    "Momentum",
                    "Risk",
                    "Market Cap",
                    "Liquidity",
                    "Buy %",
                    "30s Price Δ",
                    "Address",
                ]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # DETERIORATION
    # ========================================================

    st.subheader(
        "🔴 Momentum Deterioration"
    )

    if danger.empty:

        st.write(
            "No major deterioration detected."
        )

    else:

        st.dataframe(
            danger[
                [
                    "Token",
                    "Stage",
                    "Age",
                    "Deterioration",
                    "Risk",
                    "Momentum",
                    "Momentum Δ",
                    "Buy %",
                    "30s Price Δ",
                    "Liquidity Δ",
                    "Address",
                ]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # ALL RESULTS
    # ========================================================

    with st.expander(
        "🔬 All scanned contracts"
    ):

        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True
        )

dashboard()

# ============================================================
# HISTORY
# ============================================================

st.divider()

st.subheader("🧪 Signal Performance")

history = load_history()

if history:

    hist = pd.DataFrame(history)

    a, b, c = st.columns(3)

    a.metric(
        "Contracts Recorded",
        len(hist)
    )

    completed = hist[
        hist["return_5m"].notna()
    ] if "return_5m" in hist.columns else pd.DataFrame()

    b.metric(
        "5m Tests",
        len(completed)
    )

    if not completed.empty:

        values = pd.to_numeric(
            completed["return_5m"],
            errors="coerce"
        ).dropna()

        c.metric(
            "5m Positive",
            (
                f"{(values > 0).mean() * 100:.1f}%"
                if len(values)
                else "—"
            )
        )

    else:
        c.metric(
            "5m Positive",
            "—"
        )

else:

    st.write(
        "Performance data will build as contracts are observed."
    )

st.divider()

st.caption(
    "Early Momentum and Strong Setup are experimental market signals, "
    "not predictions of future returns. Newly launched tokens can lose "
    "most or all of their value rapidly. DexScreener discovery does not "
    "guarantee detection of every Solana launch, and Fomo tradability "
    "must be checked separately."
)
