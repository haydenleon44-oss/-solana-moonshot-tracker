import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timezone
from supabase import create_client

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="Solana Moonshot Tracker",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Moonshot Tracker V2")
st.caption(
    "Multi-source discovery • persistent tracking • momentum • risk • "
    "deterioration • performance validation"
)

BASE = "https://api.dexscreener.com"

LATEST_PROFILES = f"{BASE}/token-profiles/latest/v1"
RECENT_PROFILES = f"{BASE}/token-profiles/recent-updates/v1"
COMMUNITY = f"{BASE}/community-takeovers/latest/v1"
BOOSTS = f"{BASE}/token-boosts/latest/v1"

TOKEN_URL = f"{BASE}/latest/dex/tokens/{{}}"

REQUEST_TIMEOUT = 10


# ============================================================
# DATABASE
# ============================================================

@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_SECRET_KEY"]
    )


db = get_supabase()


# ============================================================
# HTTP
# ============================================================

@st.cache_resource
def get_http():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "SolanaMoonshotTracker/2.0"
    })
    return session


http = get_http()


def api_get(url, attempts=3):
    for attempt in range(attempts):
        try:
            r = http.get(url, timeout=REQUEST_TIMEOUT)

            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue

            r.raise_for_status()
            return r.json()

        except requests.RequestException:
            if attempt == attempts - 1:
                return None

            time.sleep(0.5 * (attempt + 1))

    return None


# ============================================================
# HELPERS
# ============================================================

def num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except Exception:
            return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def age_minutes(timestamp_ms):
    if not timestamp_ms:
        return 999999

    try:
        created = datetime.fromtimestamp(
            float(timestamp_ms) / 1000,
            timezone.utc
        )

        return max(
            0,
            (utc_now() - created).total_seconds() / 60
        )

    except Exception:
        return 999999


def display_age(minutes):
    if minutes >= 999999:
        return "?"

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes / 60:.1f}h"

    return f"{minutes / 1440:.1f}d"


def pct_return(start, current):
    start = num(start)
    current = num(current)

    if start <= 0 or current <= 0:
        return None

    return ((current / start) - 1) * 100


# ============================================================
# DISCOVERY ENGINE V2
# ============================================================

def extract_addresses(payload):
    found = set()

    if not payload:
        return found

    if isinstance(payload, dict):
        payload = [payload]

    if not isinstance(payload, list):
        return found

    for item in payload:
        if not isinstance(item, dict):
            continue

        if item.get("chainId") != "solana":
            continue

        address = item.get("tokenAddress")

        if address:
            found.add(address)

    return found


@st.cache_data(ttl=20)
def discover_addresses():
    """
    Combines multiple documented DexScreener discovery surfaces.
    Deduplicates every contract before pair lookup.
    """

    sources = {
        "Latest Profiles": api_get(LATEST_PROFILES),
        "Recent Updates": api_get(RECENT_PROFILES),
        "Community": api_get(COMMUNITY),
        "Boosts": api_get(BOOSTS),
    }

    addresses = set()
    source_counts = {}

    for name, payload in sources.items():
        discovered = extract_addresses(payload)
        addresses.update(discovered)
        source_counts[name] = len(discovered)

    return list(addresses), source_counts


# ============================================================
# PAIR LOOKUP
# ============================================================

def best_pair_for_address(address):
    data = api_get(TOKEN_URL.format(address))

    if not data:
        return None

    pairs = data.get("pairs") or []

    pairs = [
        p for p in pairs
        if p.get("chainId") == "solana"
    ]

    if not pairs:
        return None

    return max(
        pairs,
        key=lambda p: num(
            (p.get("liquidity") or {}).get("usd")
        )
    )


# ============================================================
# FEATURE EXTRACTION
# ============================================================

def build_token(address, pair):
    base = pair.get("baseToken") or {}

    txns = pair.get("txns") or {}
    tx5 = txns.get("m5") or {}
    tx1 = txns.get("h1") or {}

    volumes = pair.get("volume") or {}
    changes = pair.get("priceChange") or {}

    price = num(pair.get("priceUsd"))
    liquidity = num(
        (pair.get("liquidity") or {}).get("usd")
    )

    market_cap = num(
        pair.get("marketCap") or pair.get("fdv")
    )

    volume5 = num(volumes.get("m5"))
    volume1 = num(volumes.get("h1"))

    buys5 = int(num(tx5.get("buys")))
    sells5 = int(num(tx5.get("sells")))

    buys1 = int(num(tx1.get("buys")))
    sells1 = int(num(tx1.get("sells")))

    trades5 = buys5 + sells5
    trades1 = buys1 + sells1

    buy_ratio5 = (
        buys5 / trades5 if trades5 else 0
    )

    buy_ratio1 = (
        buys1 / trades1 if trades1 else 0
    )

    change5 = num(changes.get("m5"))
    change1 = num(changes.get("h1"))

    age = age_minutes(pair.get("pairCreatedAt"))

    liquidity_ratio = (
        liquidity / market_cap
        if market_cap > 0
        else 0
    )

    turnover1 = (
        volume1 / liquidity
        if liquidity > 0
        else 0
    )

    info = pair.get("info") or {}

    socials = info.get("socials") or []
    websites = info.get("websites") or []

    boosts = pair.get("boosts") or {}
    active_boosts = int(num(boosts.get("active")))

    # ========================================================
    # MOMENTUM MODEL
    # ========================================================

    momentum = 0.0

    # Recent activity
    momentum += min(18, trades5 * 0.35)

    # Buy pressure
    if trades5 >= 5:
        if buy_ratio5 >= 0.72:
            momentum += 18
        elif buy_ratio5 >= 0.62:
            momentum += 13
        elif buy_ratio5 >= 0.55:
            momentum += 7
        elif buy_ratio5 < 0.42:
            momentum -= 12

    # Sustained pressure
    if trades1 >= 15:
        if buy_ratio1 >= 0.62:
            momentum += 7
        elif buy_ratio1 < 0.43:
            momentum -= 7

    # Volume
    if volume5 >= 50000:
        momentum += 15
    elif volume5 >= 20000:
        momentum += 12
    elif volume5 >= 7500:
        momentum += 8
    elif volume5 >= 2500:
        momentum += 4

    # Price acceleration without rewarding absurd spikes too much
    if 3 <= change5 <= 15:
        momentum += 18
    elif 15 < change5 <= 35:
        momentum += 14
    elif 35 < change5 <= 75:
        momentum += 8
    elif change5 > 150:
        momentum -= 8

    # Freshness
    if age <= 10:
        momentum += 14
    elif age <= 30:
        momentum += 10
    elif age <= 120:
        momentum += 5

    # Negative acceleration
    if change5 <= -10:
        momentum -= 15

    if change5 <= -20:
        momentum -= 15

    momentum = int(clamp(momentum, 0, 100))

    # ========================================================
    # LIQUIDITY QUALITY
    # ========================================================

    liquidity_quality = 0

    if liquidity >= 100000:
        liquidity_quality = 100
    elif liquidity >= 50000:
        liquidity_quality = 85
    elif liquidity >= 25000:
        liquidity_quality = 70
    elif liquidity >= 10000:
        liquidity_quality = 50
    elif liquidity >= 5000:
        liquidity_quality = 30
    else:
        liquidity_quality = 10

    if liquidity_ratio >= 0.20:
        liquidity_quality += 10
    elif liquidity_ratio < 0.03:
        liquidity_quality -= 15

    liquidity_quality = int(
        clamp(liquidity_quality, 0, 100)
    )

    # ========================================================
    # MARKET-BEHAVIOR RISK
    # ========================================================

    risk = 40

    if liquidity < 3000:
        risk += 35
    elif liquidity < 5000:
        risk += 25
    elif liquidity < 10000:
        risk += 15
    elif liquidity >= 50000:
        risk -= 10

    if market_cap > 0:
        if liquidity_ratio < 0.02:
            risk += 25
        elif liquidity_ratio < 0.05:
            risk += 15
        elif liquidity_ratio >= 0.20:
            risk -= 10

    if trades5 >= 10:
        if buy_ratio5 < 0.35:
            risk += 25
        elif buy_ratio5 < 0.45:
            risk += 12
        elif buy_ratio5 >= 0.65:
            risk -= 5

    if change5 > 150:
        risk += 20
    elif change5 > 80:
        risk += 10

    if change5 < -25:
        risk += 25

    if turnover1 > 25:
        risk += 18
    elif turnover1 > 12:
        risk += 10

    risk = int(clamp(risk, 0, 100))

    # ========================================================
    # DETERIORATION
    # ========================================================

    deterioration = 0

    if change5 < -5:
        deterioration += 20

    if change5 < -15:
        deterioration += 25

    if sells5 > buys5 and trades5 >= 8:
        deterioration += 20

    if buy_ratio5 < 0.40 and trades5 >= 10:
        deterioration += 20

    if momentum < 35:
        deterioration += 15

    deterioration = int(
        clamp(deterioration, 0, 100)
    )

    # ========================================================
    # EXPERIMENTAL SIGNAL
    # ========================================================

    signal_raw = (
        momentum * 0.55
        + liquidity_quality * 0.20
        + (100 - risk) * 0.25
    )

    signal = signal_raw / 10

    if liquidity < 5000:
        signal -= 1.5

    if risk >= 75:
        signal -= 1.5

    if deterioration >= 60:
        signal -= 1.0

    signal = round(clamp(signal, 1, 10), 1)

    # ========================================================
    # STATUS
    # ========================================================

    if risk >= 85 or liquidity < 2000:
        status = "🚨 DANGER"

    elif deterioration >= 70:
        status = "🔴 EXIT WARNING"

    elif deterioration >= 45:
        status = "🟡 COOLING"

    elif (
        momentum >= 80
        and risk <= 50
        and liquidity >= 10000
        and buy_ratio5 >= 0.60
        and change5 > 0
    ):
        status = "🔥 BREAKOUT"

    elif (
        momentum >= 65
        and risk <= 60
        and liquidity >= 5000
        and buy_ratio5 >= 0.55
        and change5 > 0
    ):
        status = "🟢 BUILDING"

    elif momentum >= 50:
        status = "👀 WATCH"

    else:
        status = "⚪ WEAK"

    # Fomo is deliberately NOT represented as confirmed tradability.
    fomo_search = (
        "🔎 Search contract"
        if liquidity >= 5000 and buys5 > 0 and sells5 > 0
        else "❌ Screened out"
    )

    return {
        "Token": base.get("symbol") or "???",
        "Address": address,
        "Age": display_age(age),
        "Age Minutes": age,
        "Price": price,
        "Signal": signal,
        "Momentum": momentum,
        "Liquidity Quality": liquidity_quality,
        "Risk": risk,
        "Deterioration": deterioration,
        "Market Cap": round(market_cap),
        "Liquidity": round(liquidity),
        "5m Volume": round(volume5),
        "1h Volume": round(volume1),
        "5m Buys": buys5,
        "5m Sells": sells5,
        "Buy %": round(buy_ratio5 * 100, 1),
        "5m Change %": round(change5, 2),
        "1h Change %": round(change1, 2),
        "Socials": len(socials),
        "Websites": len(websites),
        "Boosts": active_boosts,
        "Status": status,
        "Fomo Search": fomo_search,
    }


# ============================================================
# SCAN
# ============================================================

@st.cache_data(ttl=20)
def run_scan():
    addresses, counts = discover_addresses()

    rows = []

    # Safety cap prevents hammering the public API.
    for address in addresses[:60]:
        pair = best_pair_for_address(address)

        if not pair:
            continue

        try:
            row = build_token(address, pair)

            if row["Price"] > 0:
                rows.append(row)

        except Exception:
            continue

    df = pd.DataFrame(rows)

    if not df.empty:
        df = (
            df.drop_duplicates("Address")
            .sort_values(
                ["Signal", "Momentum"],
                ascending=False
            )
        )

    return df, counts


# ============================================================
# DATABASE HISTORY
# ============================================================

def load_raw_history():
    try:
        result = (
            db.table("token_history")
            .select("*")
            .order("detected_at", desc=True)
            .limit(500)
            .execute()
        )

        return result.data or []

    except Exception:
        return []


def insert_new_signals(tokens, records):
    existing = {
        r.get("address")
        for r in records
        if r.get("address")
    }

    now = utc_now()

    for _, token in tokens.iterrows():
        address = token["Address"]

        if (
            not address
            or address in existing
            or num(token["Price"]) <= 0
        ):
            continue

        record = {
            "address": address,
            "token": token["Token"],
            "detected_at": now.isoformat(),
            "start_price": float(token["Price"]),
            "start_moonshot": float(token["Signal"]),
            "start_momentum": int(token["Momentum"]),
            "start_risk": int(token["Risk"]),
            "start_status": token["Status"],
            "latest_return": 0.0,
            "best_return": 0.0,
            "worst_return": 0.0,
            "last_price": float(token["Price"]),
            "last_updated": now.isoformat(),
        }

        try:
            (
                db.table("token_history")
                .insert(record)
                .execute()
            )
            existing.add(address)

        except Exception:
            pass


# ============================================================
# TRACK OLD CONTRACTS INDEPENDENTLY
# ============================================================

def update_tracked_contracts(records, live_df):
    """
    Critical V2 improvement:
    Previously detected contracts continue being queried even if they
    disappear from the discovery feed.
    """

    now = utc_now()

    live_prices = {}

    if not live_df.empty:
        live_prices = {
            row["Address"]: num(row["Price"])
            for _, row in live_df.iterrows()
        }

    checkpoints = {
        "return_5m": 5,
        "return_15m": 15,
        "return_30m": 30,
        "return_1h": 60,
        "return_6h": 360,
        "return_24h": 1440,
    }

    active_records = []

    for record in records:
        detected = parse_time(record.get("detected_at"))

        if not detected:
            continue

        elapsed = (
            now - detected
        ).total_seconds() / 60

        # Keep actively tracking through the 24h evaluation period.
        if elapsed <= 1500:
            active_records.append((record, elapsed))

    # Newest first and cap requests.
    active_records = active_records[:60]

    for record, elapsed in active_records:
        address = record.get("address")
        start_price = num(record.get("start_price"))

        if not address or start_price <= 0:
            continue

        current_price = live_prices.get(address, 0)

        # If no longer in discovery results, query contract directly.
        if current_price <= 0:
            pair = best_pair_for_address(address)

            if pair:
                current_price = num(pair.get("priceUsd"))

        if current_price <= 0:
            continue

        performance = pct_return(
            start_price,
            current_price
        )

        if performance is None:
            continue

        performance = round(performance, 2)

        old_best = num(record.get("best_return"))
        old_worst = num(record.get("worst_return"))

        updates = {
            "latest_return": performance,
            "best_return": max(old_best, performance),
            "worst_return": min(old_worst, performance),
            "last_price": current_price,
            "last_updated": now.isoformat(),
        }

        # These are first-observed-at-or-after checkpoint returns.
        for column, threshold in checkpoints.items():
            if (
                elapsed >= threshold
                and record.get(column) is None
            ):
                updates[column] = performance

        try:
            (
                db.table("token_history")
                .update(updates)
                .eq("address", address)
                .execute()
            )

        except Exception:
            continue


# ============================================================
# HISTORY DISPLAY
# ============================================================

def history_dataframe(records):
    rows = []

    for r in records:
        detected = parse_time(r.get("detected_at"))

        rows.append({
            "Token": r.get("token"),
            "Detected": (
                detected.strftime("%m/%d %H:%M")
                if detected else "?"
            ),
            "Start Signal": r.get("start_moonshot"),
            "Start Momentum": r.get("start_momentum"),
            "Start Risk": r.get("start_risk"),
            "Start Status": r.get("start_status"),
            "Latest %": r.get("latest_return"),
            "Best %": r.get("best_return"),
            "Worst %": r.get("worst_return"),
            "5m %": r.get("return_5m"),
            "15m %": r.get("return_15m"),
            "30m %": r.get("return_30m"),
            "1h %": r.get("return_1h"),
            "6h %": r.get("return_6h"),
            "24h %": r.get("return_24h"),
            "Address": r.get("address"),
        })

    return pd.DataFrame(rows)


# ============================================================
# APP EXECUTION
# ============================================================

if st.sidebar.button(
    "🔄 Refresh Everything",
    use_container_width=True
):
    st.cache_data.clear()
    st.rerun()


with st.spinner("Scanning Solana markets..."):
    tokens, source_counts = run_scan()


# ============================================================
# DATABASE UPDATE
# ============================================================

records_before = load_raw_history()

if not tokens.empty:
    insert_new_signals(tokens, records_before)

# Reload to include newly inserted tokens.
records = load_raw_history()

update_tracked_contracts(
    records,
    tokens
)

# Reload final state.
records = load_raw_history()
history = history_dataframe(records)


# ============================================================
# SIDEBAR FILTERS
# ============================================================

st.sidebar.header("🎯 Filters")

max_risk = st.sidebar.slider(
    "Maximum Risk",
    0,
    100,
    60
)

min_liquidity = st.sidebar.number_input(
    "Minimum Liquidity ($)",
    min_value=0,
    value=5000,
    step=1000
)

min_signal = st.sidebar.slider(
    "Minimum Signal",
    1.0,
    10.0,
    5.0,
    0.1
)

max_age = st.sidebar.slider(
    "Maximum Pair Age (minutes)",
    5,
    1440,
    240
)


# ============================================================
# DISCOVERY STATUS
# ============================================================

st.subheader("📡 Discovery Engine")

c1, c2, c3, c4 = st.columns(4)

c1.metric(
    "Latest Profiles",
    source_counts.get("Latest Profiles", 0)
)

c2.metric(
    "Recent Updates",
    source_counts.get("Recent Updates", 0)
)

c3.metric(
    "Community",
    source_counts.get("Community", 0)
)

c4.metric(
    "Boosts",
    source_counts.get("Boosts", 0)
)


# ============================================================
# FILTER
# ============================================================

if tokens.empty:
    filtered = pd.DataFrame()

else:
    filtered = tokens[
        (tokens["Risk"] <= max_risk)
        & (tokens["Liquidity"] >= min_liquidity)
        & (tokens["Signal"] >= min_signal)
        & (tokens["Age Minutes"] <= max_age)
        & (tokens["5m Buys"] > 0)
        & (tokens["5m Sells"] > 0)
        & (tokens["Fomo Search"] != "❌ Screened out")
    ].copy()

    filtered = filtered.sort_values(
        ["Signal", "Momentum"],
        ascending=False
    )


# ============================================================
# TOP METRICS
# ============================================================

m1, m2, m3, m4, m5 = st.columns(5)

m1.metric(
    "Scanned",
    len(tokens)
)

m2.metric(
    "Passing",
    len(filtered)
)

m3.metric(
    "Highest Signal",
    (
        f"{filtered['Signal'].max():.1f}/10"
        if not filtered.empty
        else "—"
    )
)

m4.metric(
    "Highest Momentum",
    (
        f"{int(filtered['Momentum'].max())}/100"
        if not filtered.empty
        else "—"
    )
)

m5.metric(
    "Tracked",
    len(history)
)


# ============================================================
# OPPORTUNITY FEED
# ============================================================

st.subheader("🔥 Opportunity Feed")

if filtered.empty:
    st.info(
        "Nothing currently passes all selected filters."
    )

else:
    columns = [
        "Token",
        "Age",
        "Signal",
        "Momentum",
        "Liquidity Quality",
        "Risk",
        "Deterioration",
        "Market Cap",
        "Liquidity",
        "5m Volume",
        "5m Buys",
        "5m Sells",
        "Buy %",
        "5m Change %",
        "Status",
        "Fomo Search",
        "Address",
    ]

    st.dataframe(
        filtered[columns],
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# STRONG SETUPS
# ============================================================

strong = filtered[
    filtered["Status"].isin([
        "🔥 BREAKOUT",
        "🟢 BUILDING"
    ])
] if not filtered.empty else pd.DataFrame()

if not strong.empty:
    st.subheader("🚀 Momentum Setups")

    for _, coin in strong.head(8).iterrows():
        st.success(
            f"""
**{coin['Token']} — {coin['Status']}**

Signal: **{coin['Signal']}/10**  
Momentum: **{coin['Momentum']}/100**  
Liquidity Quality: **{coin['Liquidity Quality']}/100**  
Risk: **{coin['Risk']}/100**  
Deterioration: **{coin['Deterioration']}/100**

Liquidity: **${coin['Liquidity']:,}**  
5m Volume: **${coin['5m Volume']:,}**  
Buys / Sells: **{coin['5m Buys']} / {coin['5m Sells']}**  
Buy Ratio: **{coin['Buy %']}%**  
5m Price Change: **{coin['5m Change %']}%**

Fomo: **search this contract manually**

`{coin['Address']}`
"""
        )


# ============================================================
# DETERIORATION
# ============================================================

if not tokens.empty:
    deterioration = tokens[
        tokens["Status"].isin([
            "🟡 COOLING",
            "🔴 EXIT WARNING",
            "🚨 DANGER"
        ])
    ].sort_values(
        ["Deterioration", "Risk"],
        ascending=False
    )

    if not deterioration.empty:
        st.subheader("⚠️ Deterioration Monitor")

        st.dataframe(
            deterioration[
                [
                    "Token",
                    "Status",
                    "Deterioration",
                    "Momentum",
                    "Risk",
                    "Buy %",
                    "5m Change %",
                    "Liquidity",
                    "Address",
                ]
            ].head(15),
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# PERFORMANCE LAB
# ============================================================

st.divider()
st.subheader("🧪 Persistent Performance Lab")

st.caption(
    "Previously discovered contracts continue being queried even after "
    "they leave the discovery feed."
)

if history.empty:
    st.info("No stored observations yet.")

else:
    completed5 = history[
        history["5m %"].notna()
    ].copy()

    completed1h = history[
        history["1h %"].notna()
    ].copy()

    p1, p2, p3, p4 = st.columns(4)

    p1.metric(
        "Tracked Tokens",
        len(history)
    )

    p2.metric(
        "5m Samples",
        len(completed5)
    )

    if not completed5.empty:
        returns5 = pd.to_numeric(
            completed5["5m %"],
            errors="coerce"
        ).dropna()

        p3.metric(
            "Median 5m Return",
            (
                f"{returns5.median():.2f}%"
                if not returns5.empty
                else "—"
            )
        )

        p4.metric(
            "5m Positive Rate",
            (
                f"{(returns5.gt(0).mean() * 100):.1f}%"
                if not returns5.empty
                else "—"
            )
        )

    else:
        p3.metric("Median 5m Return", "—")
        p4.metric("5m Positive Rate", "—")

    st.dataframe(
        history,
        use_container_width=True,
        hide_index=True
    )

    # --------------------------------------------------------
    # SCORE VALIDATION
    # --------------------------------------------------------

    if len(completed5) >= 10:
        st.subheader("📊 Signal Validation")

        validation = completed5.copy()

        validation["Start Signal"] = pd.to_numeric(
            validation["Start Signal"],
            errors="coerce"
        )

        validation["5m %"] = pd.to_numeric(
            validation["5m %"],
            errors="coerce"
        )

        validation = validation.dropna(
            subset=["Start Signal", "5m %"]
        )

        validation["Signal Band"] = pd.cut(
            validation["Start Signal"],
            bins=[0, 4, 6, 8, 10],
            labels=[
                "1–4",
                "4–6",
                "6–8",
                "8–10"
            ],
            include_lowest=True
        )

        summary = (
            validation
            .groupby(
                "Signal Band",
                observed=True
            )
            .agg(
                Samples=("5m %", "count"),
                Median_Return=("5m %", "median"),
                Average_Return=("5m %", "mean"),
                Positive_Rate=(
                    "5m %",
                    lambda x: (x > 0).mean() * 100
                )
            )
            .reset_index()
        )

        summary["Median_Return"] = (
            summary["Median_Return"].round(2)
        )

        summary["Average_Return"] = (
            summary["Average_Return"].round(2)
        )

        summary["Positive_Rate"] = (
            summary["Positive_Rate"].round(1)
        )

        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# IMPORTANT MODEL INFORMATION
# ============================================================

st.divider()
st.subheader("🔬 Model Status")

st.write(
    """
**Discovery V2:** combines several documented DexScreener discovery
surfaces and deduplicates Solana contracts.

**Persistent tracking:** contracts already discovered remain tracked
through the evaluation period even when they disappear from the
discovery feed.

**Signal:** combines momentum, liquidity quality and observed
market-behavior risk.

**Deterioration:** separately looks for weakening price action,
sell pressure and loss of momentum.

**Performance Lab:** measures what actually happened after a signal
instead of assuming a high score predicts a gain.

Checkpoint values are the **first price observed at or after** each
time threshold. They are not exact historical candle closes yet.

The Risk score measures observable market behavior from the available
data. It does **not** prove that a contract is safe and does not yet
include complete holder concentration, creator-wallet, bundled-wallet,
mint/freeze-authority or funding-relationship analysis.

The Fomo field is intentionally a manual contract search rather than
a claim that Fomo has independently confirmed execution availability.

Treat the model as experimental until the Performance Lab contains a
meaningful sample across different market conditions.
"""
)
