
import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(
    page_title="Solana Trade Radar",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Trade Radar LIVE")
st.caption(
    "30-second momentum monitoring • expanded Solana discovery • "
    "acceleration detection • persistent trade research"
)

BASE = "https://api.dexscreener.com"

DISCOVERY_URLS = [
    f"{BASE}/token-profiles/latest/v1",
    f"{BASE}/token-profiles/recent-updates/v1",
    f"{BASE}/community-takeovers/latest/v1",
    f"{BASE}/token-boosts/latest/v1",
    f"{BASE}/token-boosts/top/v1",
    f"{BASE}/ads/latest/v1",
]

TOKEN_URL = f"{BASE}/latest/dex/tokens/{{}}"

# Discovery can consider a much larger pool.
MAX_DISCOVERY_POOL = 200

# Each 30-second cycle prioritizes this many contracts.
MAX_LIVE_SCAN = 75

# Previously discovered coins can remain in rotation.
MAX_TRACKED_ROTATION = 75


# ============================================================
# SUPABASE
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
def get_http():
    session = requests.Session()

    session.headers.update({
        "User-Agent": "SolanaTradeRadar/4.0"
    })

    return session


http = get_http()


def api_get(url, attempts=3):

    for attempt in range(attempts):

        try:
            response = http.get(
                url,
                timeout=10
            )

            if response.status_code == 429:
                time.sleep(
                    1.5 * (attempt + 1)
                )
                continue

            response.raise_for_status()

            return response.json()

        except requests.RequestException:

            if attempt == attempts - 1:
                return None

            time.sleep(
                0.5 * (attempt + 1)
            )

    return None


# ============================================================
# HELPERS
# ============================================================

def num(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def clamp(value, low, high):
    return max(
        low,
        min(high, value)
    )


def utc_now():
    return datetime.now(
        timezone.utc
    )


def parse_time(value):

    if not value:
        return None

    try:

        dt = datetime.fromisoformat(
            str(value).replace(
                "Z",
                "+00:00"
            )
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt

    except Exception:
        return None


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
            (
                utc_now() - created
            ).total_seconds() / 60
        )

    except Exception:
        return 999999


def age_text(minutes):

    if minutes >= 999999:
        return "?"

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes / 60:.1f}h"

    return f"{minutes / 1440:.1f}d"


def pct_change(old, new):

    old = num(old)
    new = num(new)

    if old <= 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100


# ============================================================
# DISCOVERY ENGINE
# ============================================================

def extract_addresses(payload):

    addresses = []

    if not payload:
        return addresses

    if isinstance(payload, dict):
        payload = [payload]

    if not isinstance(payload, list):
        return addresses

    for item in payload:

        if not isinstance(item, dict):
            continue

        if item.get("chainId") != "solana":
            continue

        address = item.get(
            "tokenAddress"
        )

        if address:
            addresses.append(address)

    return addresses


@st.cache_data(ttl=120)
def discover_tokens():

    ordered = []

    seen = set()

    for url in DISCOVERY_URLS:

        payload = api_get(url)

        for address in extract_addresses(
            payload
        ):

            if address not in seen:

                seen.add(address)
                ordered.append(address)

    return ordered[
        :MAX_DISCOVERY_POOL
    ]


# ============================================================
# EXISTING TRACKED CONTRACTS
# ============================================================

def load_history():

    try:

        result = (
            db.table("token_history")
            .select("*")
            .order(
                "detected_at",
                desc=True
            )
            .limit(500)
            .execute()
        )

        return result.data or []

    except Exception:
        return []


def recent_tracked_addresses(
    records
):

    now = utc_now()

    addresses = []

    for record in records:

        address = record.get(
            "address"
        )

        detected = parse_time(
            record.get(
                "detected_at"
            )
        )

        if (
            not address
            or not detected
        ):
            continue

        age = (
            now - detected
        ).total_seconds() / 3600

        # Prioritize coins from last 24h.
        if age <= 24:
            addresses.append(address)

    return addresses[
        :MAX_TRACKED_ROTATION
    ]


# ============================================================
# PAIR FETCH
# ============================================================

def best_pair(address):

    data = api_get(
        TOKEN_URL.format(address)
    )

    if not data:
        return None

    pairs = data.get(
        "pairs"
    ) or []

    solana_pairs = [
        pair
        for pair in pairs
        if pair.get(
            "chainId"
        ) == "solana"
    ]

    if not solana_pairs:
        return None

    return max(
        solana_pairs,
        key=lambda pair: num(
            (
                pair.get(
                    "liquidity"
                ) or {}
            ).get("usd")
        )
    )


# ============================================================
# PREVIOUS SNAPSHOT
# ============================================================

def previous_snapshot(
    address
):

    try:

        result = (
            db.table(
                "token_snapshots"
            )
            .select("*")
            .eq(
                "address",
                address
            )
            .order(
                "recorded_at",
                desc=True
            )
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception:
        pass

    return None


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def analyze_token(
    address,
    pair,
    previous
):

    base = (
        pair.get("baseToken")
        or {}
    )

    symbol = (
        base.get("symbol")
        or "UNKNOWN"
    )

    price = num(
        pair.get("priceUsd")
    )

    liquidity = num(
        (
            pair.get("liquidity")
            or {}
        ).get("usd")
    )

    market_cap = num(
        pair.get("marketCap")
        or pair.get("fdv")
    )

    volume = (
        pair.get("volume")
        or {}
    )

    volume5 = num(
        volume.get("m5")
    )

    volume1h = num(
        volume.get("h1")
    )

    changes = (
        pair.get(
            "priceChange"
        ) or {}
    )

    change5 = num(
        changes.get("m5")
    )

    change1h = num(
        changes.get("h1")
    )

    txns = (
        pair.get("txns")
        or {}
    )

    tx5 = (
        txns.get("m5")
        or {}
    )

    tx1 = (
        txns.get("h1")
        or {}
    )

    buys5 = int(
        num(tx5.get("buys"))
    )

    sells5 = int(
        num(tx5.get("sells"))
    )

    buys1 = int(
        num(tx1.get("buys"))
    )

    sells1 = int(
        num(tx1.get("sells"))
    )

    trades5 = (
        buys5 + sells5
    )

    trades1 = (
        buys1 + sells1
    )

    buy_ratio = (
        buys5 / trades5
        if trades5
        else 0
    )

    buy_ratio1 = (
        buys1 / trades1
        if trades1
        else 0
    )

    age = age_minutes(
        pair.get(
            "pairCreatedAt"
        )
    )

    liquidity_ratio = (
        liquidity / market_cap
        if market_cap > 0
        else 0
    )

    turnover = (
        volume1h / liquidity
        if liquidity > 0
        else 0
    )

    # ========================================================
    # CHANGE SINCE PREVIOUS 30s OBSERVATION
    # ========================================================

    previous_volume = num(
        previous.get(
            "volume_5m"
        )
        if previous
        else 0
    )

    previous_buy_ratio = num(
        previous.get(
            "buy_ratio"
        )
        if previous
        else 0
    )

    previous_liquidity = num(
        previous.get(
            "liquidity"
        )
        if previous
        else 0
    )

    previous_price = num(
        previous.get(
            "price"
        )
        if previous
        else 0
    )

    previous_momentum = num(
        previous.get(
            "momentum"
        )
        if previous
        else 0
    )

    volume_accel = (
        pct_change(
            previous_volume,
            volume5
        )
        if previous_volume > 0
        else 0
    )

    buy_pressure_change = (
        (buy_ratio - previous_buy_ratio)
        * 100
        if previous
        else 0
    )

    liquidity_change = (
        pct_change(
            previous_liquidity,
            liquidity
        )
        if previous_liquidity > 0
        else 0
    )

    price_since_scan = (
        pct_change(
            previous_price,
            price
        )
        if previous_price > 0
        else 0
    )

    # ========================================================
    # MOMENTUM
    # ========================================================

    momentum = 0.0

    momentum += min(
        18,
        trades5 * 0.35
    )

    if trades5 >= 5:

        if buy_ratio >= 0.70:
            momentum += 18

        elif buy_ratio >= 0.62:
            momentum += 13

        elif buy_ratio >= 0.55:
            momentum += 7

        elif buy_ratio < 0.42:
            momentum -= 12

    if trades1 >= 15:

        if buy_ratio1 >= 0.60:
            momentum += 7

        elif buy_ratio1 < 0.43:
            momentum -= 7

    if volume5 >= 50000:
        momentum += 15

    elif volume5 >= 20000:
        momentum += 12

    elif volume5 >= 7500:
        momentum += 8

    elif volume5 >= 2500:
        momentum += 4

    if 3 <= change5 <= 15:
        momentum += 18

    elif 15 < change5 <= 35:
        momentum += 13

    elif 35 < change5 <= 75:
        momentum += 8

    elif change5 > 150:
        momentum -= 10

    if age <= 10:
        momentum += 15

    elif age <= 30:
        momentum += 10

    elif age <= 120:
        momentum += 5

    # Acceleration bonuses.
    if previous:

        if volume_accel >= 25:
            momentum += 8

        elif volume_accel >= 10:
            momentum += 4

        if buy_pressure_change >= 5:
            momentum += 7

        elif buy_pressure_change <= -8:
            momentum -= 8

        if price_since_scan > 3:
            momentum += 5

        if liquidity_change >= 5:
            momentum += 4

    if change5 <= -10:
        momentum -= 15

    if change5 <= -20:
        momentum -= 15

    momentum = int(
        clamp(
            momentum,
            0,
            100
        )
    )

    momentum_change = (
        momentum
        - previous_momentum
        if previous
        else 0
    )

    # ========================================================
    # LIQUIDITY QUALITY
    # ========================================================

    if liquidity >= 100000:
        liquidity_score = 100

    elif liquidity >= 50000:
        liquidity_score = 90

    elif liquidity >= 25000:
        liquidity_score = 75

    elif liquidity >= 10000:
        liquidity_score = 60

    elif liquidity >= 5000:
        liquidity_score = 40

    else:
        liquidity_score = 10

    if liquidity_ratio >= 0.20:
        liquidity_score += 10

    elif (
        market_cap > 0
        and liquidity_ratio < 0.03
    ):
        liquidity_score -= 20

    liquidity_score = int(
        clamp(
            liquidity_score,
            0,
            100
        )
    )

    # ========================================================
    # RISK
    # ========================================================

    risk = 35

    if liquidity <= 0:
        risk = 100

    elif liquidity < 3000:
        risk += 45

    elif liquidity < 5000:
        risk += 30

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

        if buy_ratio < 0.35:
            risk += 25

        elif buy_ratio < 0.45:
            risk += 12

        elif buy_ratio >= 0.65:
            risk -= 5

    if change5 > 150:
        risk += 25

    elif change5 > 80:
        risk += 12

    if change5 < -25:
        risk += 25

    if turnover > 25:
        risk += 20

    elif turnover > 12:
        risk += 10

    # Sudden liquidity loss.
    if (
        previous
        and liquidity_change <= -20
    ):
        risk += 25

    risk = int(
        clamp(
            risk,
            0,
            100
        )
    )

    # ========================================================
    # DETERIORATION
    # ========================================================

    deterioration = 0

    if change5 < -5:
        deterioration += 15

    if change5 < -12:
        deterioration += 20

    if change5 < -20:
        deterioration += 20

    if (
        sells5 > buys5
        and trades5 >= 8
    ):
        deterioration += 15

    if (
        buy_ratio < 0.40
        and trades5 >= 10
    ):
        deterioration += 15

    if previous:

        if momentum_change <= -15:
            deterioration += 20

        elif momentum_change <= -8:
            deterioration += 10

        if buy_pressure_change <= -10:
            deterioration += 15

        if price_since_scan <= -5:
            deterioration += 15

        if liquidity_change <= -15:
            deterioration += 20

    deterioration = int(
        clamp(
            deterioration,
            0,
            100
        )
    )

    # ========================================================
    # SETUP SCORE
    # ========================================================

    score = (
        momentum * 0.55
        + liquidity_score * 0.20
        + (100 - risk) * 0.25
    ) / 10

    if liquidity < 5000:
        score -= 2

    if risk >= 75:
        score -= 1.5

    if deterioration >= 50:
        score -= 1

    score = round(
        clamp(
            score,
            1,
            10
        ),
        1
    )

    # ========================================================
    # TREND
    # ========================================================

    if not previous:

        trend = "🆕 NEW"

    elif (
        momentum_change >= 10
        and buy_pressure_change > 0
    ):

        trend = "🚀 ACCELERATING"

    elif (
        momentum_change >= 4
        or (
            price_since_scan > 0
            and buy_pressure_change > 0
        )
    ):

        trend = "📈 STRENGTHENING"

    elif (
        momentum_change <= -10
        or buy_pressure_change <= -8
    ):

        trend = "📉 FADING"

    else:

        trend = "➡️ STEADY"

    # ========================================================
    # SIMPLE ACTION ENGINE
    # ========================================================

    if (
        liquidity < 3000
        or risk >= 85
    ):

        action = "⛔ AVOID"

        reason = (
            "Liquidity/risk conditions fail the safety screen."
        )

    elif deterioration >= 70:

        action = "🔴 EXIT WARNING"

        reason = (
            "Multiple momentum deterioration signals are active."
        )

    elif deterioration >= 45:

        action = "🟠 WEAKENING"

        reason = (
            "Momentum or buyer strength is deteriorating."
        )

    elif (
        score >= 7.5
        and momentum >= 75
        and risk <= 50
        and liquidity >= 10000
        and buy_ratio >= 0.60
        and change5 > 0
        and (
            trend
            in [
                "🚀 ACCELERATING",
                "📈 STRENGTHENING",
                "🆕 NEW"
            ]
        )
    ):

        action = "🟢 STRONG SETUP"

        reason = (
            "High momentum, buyer pressure and liquidity with "
            "positive short-term behavior."
        )

    elif (
        score >= 6
        and momentum >= 58
        and risk <= 65
        and liquidity >= 5000
        and buy_ratio >= 0.54
    ):

        action = "🟡 WATCH"

        reason = (
            "Promising activity, but stronger confirmation is needed."
        )

    else:

        action = "⚪ WAIT"

        reason = (
            "No high-confidence momentum setup detected."
        )

    return {
        "Token": symbol,
        "Address": address,
        "Action": action,
        "Trend": trend,
        "Reason": reason,
        "Score": score,
        "Momentum": momentum,
        "Momentum Δ": round(
            momentum_change,
            1
        ),
        "Risk": risk,
        "Deterioration": deterioration,
        "Liquidity Quality": liquidity_score,
        "Price": price,
        "Market Cap": round(market_cap),
        "Liquidity": round(liquidity),
        "5m Volume": round(volume5),
        "5m Buys": buys5,
        "5m Sells": sells5,
        "Buy %": round(
            buy_ratio * 100,
            1
        ),
        "Buy Pressure Δ": round(
            buy_pressure_change,
            1
        ),
        "Volume Δ": round(
            volume_accel,
            1
        ),
        "Liquidity Δ": round(
            liquidity_change,
            1
        ),
        "30s Price Δ": round(
            price_since_scan,
            2
        ),
        "5m Change %": round(
            change5,
            2
        ),
        "1h Change %": round(
            change1h,
            2
        ),
        "Age": age_text(age),
        "Age Minutes": age,
    }


# ============================================================
# SAVE SNAPSHOT
# ============================================================

def save_snapshot(coin):

    try:

        db.table(
            "token_snapshots"
        ).insert({
            "address":
                coin["Address"],

            "token":
                coin["Token"],

            "recorded_at":
                utc_now().isoformat(),

            "price":
                float(
                    coin["Price"]
                ),

            "market_cap":
                float(
                    coin["Market Cap"]
                ),

            "liquidity":
                float(
                    coin["Liquidity"]
                ),

            "volume_5m":
                float(
                    coin["5m Volume"]
                ),

            "buys_5m":
                int(
                    coin["5m Buys"]
                ),

            "sells_5m":
                int(
                    coin["5m Sells"]
                ),

            "buy_ratio":
                float(
                    coin["Buy %"]
                ) / 100,

            "price_change_5m":
                float(
                    coin["5m Change %"]
                ),

            "momentum":
                int(
                    coin["Momentum"]
                ),

            "risk":
                int(
                    coin["Risk"]
                ),

            "deterioration":
                int(
                    coin["Deterioration"]
                ),

            "setup_score":
                float(
                    coin["Score"]
                ),
        }).execute()

    except Exception:
        pass


# ============================================================
# SAVE FIRST DETECTION
# ============================================================

def save_history_if_new(
    coin,
    known_addresses
):

    address = coin["Address"]

    if address in known_addresses:
        return

    try:

        db.table(
            "token_history"
        ).insert({
            "address":
                address,

            "token":
                coin["Token"],

            "detected_at":
                utc_now().isoformat(),

            "start_price":
                float(
                    coin["Price"]
                ),

            "start_moonshot":
                float(
                    coin["Score"]
                ),

            "start_momentum":
                int(
                    coin["Momentum"]
                ),

            "start_risk":
                int(
                    coin["Risk"]
                ),

            "start_status":
                coin["Action"],

            "latest_return":
                0.0,

            "best_return":
                0.0,

            "worst_return":
                0.0,

            "last_price":
                float(
                    coin["Price"]
                ),

            "last_updated":
                utc_now().isoformat(),
        }).execute()

        known_addresses.add(
            address
        )

    except Exception:
        pass


# ============================================================
# UPDATE PERFORMANCE HISTORY
# ============================================================

def update_performance(
    coin,
    record
):

    if not record:
        return

    start_price = num(
        record.get(
            "start_price"
        )
    )

    detected = parse_time(
        record.get(
            "detected_at"
        )
    )

    current = num(
        coin["Price"]
    )

    if (
        start_price <= 0
        or current <= 0
        or not detected
    ):
        return

    performance = pct_change(
        start_price,
        current
    )

    performance = round(
        performance,
        2
    )

    elapsed = (
        utc_now() - detected
    ).total_seconds() / 60

    updates = {
        "latest_return":
            performance,

        "best_return":
            max(
                num(
                    record.get(
                        "best_return"
                    )
                ),
                performance
            ),

        "worst_return":
            min(
                num(
                    record.get(
                        "worst_return"
                    )
                ),
                performance
            ),

        "last_price":
            current,

        "last_updated":
            utc_now().isoformat(),
    }

    checkpoints = {
        "return_5m": 5,
        "return_15m": 15,
        "return_30m": 30,
        "return_1h": 60,
        "return_6h": 360,
        "return_24h": 1440,
    }

    for column, minutes in checkpoints.items():

        if (
            elapsed >= minutes
            and record.get(
                column
            ) is None
        ):

            updates[column] = (
                performance
            )

    try:

        (
            db.table(
                "token_history"
            )
            .update(updates)
            .eq(
                "address",
                coin["Address"]
            )
            .execute()
        )

    except Exception:
        pass


# ============================================================
# BUILD ROTATING SCAN LIST
# ============================================================

def build_scan_addresses():

    discovered = discover_tokens()

    history = load_history()

    tracked = (
        recent_tracked_addresses(
            history
        )
    )

    combined = []

    seen = set()

    # New discoveries get first priority.
    for address in discovered:

        if address not in seen:

            seen.add(address)
            combined.append(address)

    # Then tracked coins.
    for address in tracked:

        if address not in seen:

            seen.add(address)
            combined.append(address)

    # Rotate through pool between fragment runs.
    if "rotation_offset" not in st.session_state:
        st.session_state.rotation_offset = 0

    if not combined:
        return [], 0

    pool_size = len(combined)

    start = (
        st.session_state.rotation_offset
        % pool_size
    )

    rotated = (
        combined[start:]
        + combined[:start]
    )

    selected = rotated[
        :MAX_LIVE_SCAN
    ]

    st.session_state.rotation_offset = (
        start
        + MAX_LIVE_SCAN
    ) % pool_size

    return selected, pool_size


# ============================================================
# SCAN ONE LIVE CYCLE
# ============================================================

def live_scan():

    addresses, pool_size = (
        build_scan_addresses()
    )

    history = load_history()

    history_map = {
        row.get("address"): row
        for row in history
        if row.get("address")
    }

    known = set(
        history_map.keys()
    )

    rows = []

    for address in addresses:

        pair = best_pair(address)

        if not pair:
            continue

        # Ignore dead/no-liquidity pairs early.
        liquidity = num(
            (
                pair.get(
                    "liquidity"
                ) or {}
            ).get("usd")
        )

        if liquidity <= 0:
            continue

        previous = (
            previous_snapshot(
                address
            )
        )

        try:

            coin = analyze_token(
                address,
                pair,
                previous
            )

        except Exception:
            continue

        if coin["Price"] <= 0:
            continue

        rows.append(coin)

        save_history_if_new(
            coin,
            known
        )

        save_snapshot(
            coin
        )

        update_performance(
            coin,
            history_map.get(
                address
            )
        )

    if not rows:

        return (
            pd.DataFrame(),
            pool_size
        )

    df = pd.DataFrame(
        rows
    )

    df = (
        df
        .drop_duplicates(
            "Address"
        )
        .sort_values(
            [
                "Score",
                "Momentum"
            ],
            ascending=False
        )
    )

    return df, pool_size


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.header(
    "⚡ Live Scanner"
)

st.sidebar.success(
    "AUTO REFRESH: 30 SECONDS"
)

st.sidebar.caption(
    "Keep this page open for live 30-second monitoring."
)

if st.sidebar.button(
    "🔄 Refresh Discovery Pool",
    use_container_width=True
):

    st.cache_data.clear()
    st.rerun()


# ============================================================
# LIVE 30-SECOND DASHBOARD
# ============================================================

@st.fragment(
    run_every="30s"
)
def live_dashboard():

    scan_started = utc_now()

    with st.spinner(
        "Scanning live Solana markets..."
    ):

        tokens, pool_size = (
            live_scan()
        )

    st.caption(
        "Last scan: "
        + scan_started.strftime(
            "%H:%M:%S UTC"
        )
        + " • next automatic scan ≈ 30 seconds"
    )

    if tokens.empty:

        st.warning(
            "No usable token data was returned during this rotation."
        )

        return

    strong = tokens[
        tokens["Action"]
        == "🟢 STRONG SETUP"
    ].copy()

    watch = tokens[
        tokens["Action"]
        == "🟡 WATCH"
    ].copy()

    accelerating = tokens[
        tokens["Trend"].isin(
            [
                "🚀 ACCELERATING",
                "📈 STRENGTHENING"
            ]
        )
    ].copy()

    danger = tokens[
        tokens["Action"].isin(
            [
                "🔴 EXIT WARNING",
                "🟠 WEAKENING"
            ]
        )
    ].copy()

    # ========================================================
    # METRICS
    # ========================================================

    a, b, c, d, e = (
        st.columns(5)
    )

    a.metric(
        "🟢 Strong",
        len(strong)
    )

    b.metric(
        "🚀 Accelerating",
        len(accelerating)
    )

    c.metric(
        "🟡 Watch",
        len(watch)
    )

    d.metric(
        "🔴 Weakening",
        len(danger)
    )

    e.metric(
        "📡 Discovery Pool",
        pool_size
    )

    # ========================================================
    # STRONG SETUPS
    # ========================================================

    st.subheader(
        "🟢 Strong Setups"
    )

    if strong.empty:

        st.info(
            "No coin currently meets every Strong Setup requirement."
        )

    else:

        strong = strong.sort_values(
            [
                "Score",
                "Momentum"
            ],
            ascending=False
        )

        for _, coin in strong.head(
            10
        ).iterrows():

            st.success(
                f"""
### {coin['Token']} — {coin['Trend']}

**Signal: {coin['Score']}/10**

{coin['Reason']}

Momentum: **{coin['Momentum']}/100** ({coin['Momentum Δ']:+.0f})  
Risk: **{coin['Risk']}/100**  
Buy share: **{coin['Buy %']}%**  
Buy-pressure change: **{coin['Buy Pressure Δ']:+.1f} pts**  
30s price change: **{coin['30s Price Δ']:+.2f}%**  
5m change: **{coin['5m Change %']:+.2f}%**  
Liquidity: **${coin['Liquidity']:,}**  
Liquidity change: **{coin['Liquidity Δ']:+.1f}%**  
5m volume: **${coin['5m Volume']:,}**  
Age: **{coin['Age']}**

Contract:

`{coin['Address']}`
"""
            )

    # ========================================================
    # ACCELERATION RADAR
    # ========================================================

    st.subheader(
        "🚀 Momentum Acceleration Radar"
    )

    if accelerating.empty:

        st.write(
            "No significant acceleration detected this cycle."
        )

    else:

        st.dataframe(
            accelerating[
                [
                    "Token",
                    "Trend",
                    "Action",
                    "Score",
                    "Momentum",
                    "Momentum Δ",
                    "Buy %",
                    "Buy Pressure Δ",
                    "30s Price Δ",
                    "Volume Δ",
                    "Liquidity",
                    "Risk",
                    "Address",
                ]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # WATCH
    # ========================================================

    st.subheader(
        "🟡 Watchlist"
    )

    if watch.empty:

        st.write(
            "No developing setups qualify right now."
        )

    else:

        st.dataframe(
            watch[
                [
                    "Token",
                    "Trend",
                    "Score",
                    "Momentum",
                    "Momentum Δ",
                    "Risk",
                    "Buy %",
                    "30s Price Δ",
                    "5m Change %",
                    "Liquidity",
                    "Age",
                    "Address",
                ]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # EXIT WARNINGS
    # ========================================================

    st.subheader(
        "🔴 Exit / Deterioration Radar"
    )

    if danger.empty:

        st.write(
            "No major deterioration signals detected this cycle."
        )

    else:

        danger = danger.sort_values(
            "Deterioration",
            ascending=False
        )

        st.dataframe(
            danger[
                [
                    "Token",
                    "Action",
                    "Trend",
                    "Deterioration",
                    "Momentum",
                    "Momentum Δ",
                    "Buy %",
                    "Buy Pressure Δ",
                    "30s Price Δ",
                    "Liquidity Δ",
                    "Risk",
                    "Address",
                ]
            ].head(20),
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # EVERYTHING SCANNED THIS ROTATION
    # ========================================================

    with st.expander(
        "🔬 Advanced data — current rotation"
    ):

        st.dataframe(
            tokens,
            use_container_width=True,
            hide_index=True
        )


live_dashboard()


# ============================================================
# MODEL VALIDATION
# ============================================================

st.divider()

st.subheader(
    "🧪 Model Validation"
)

history = load_history()

if not history:

    st.info(
        "No historical signals stored yet."
    )

else:

    rows = []

    for record in history:

        rows.append({
            "Token":
                record.get(
                    "token"
                ),

            "Signal":
                record.get(
                    "start_moonshot"
                ),

            "Initial Action":
                record.get(
                    "start_status"
                ),

            "5m %":
                record.get(
                    "return_5m"
                ),

            "15m %":
                record.get(
                    "return_15m"
                ),

            "30m %":
                record.get(
                    "return_30m"
                ),

            "1h %":
                record.get(
                    "return_1h"
                ),

            "6h %":
                record.get(
                    "return_6h"
                ),

            "24h %":
                record.get(
                    "return_24h"
                ),
        })

    history_df = pd.DataFrame(
        rows
    )

    completed = history_df[
        history_df["5m %"].notna()
    ].copy()

    v1, v2, v3 = (
        st.columns(3)
    )

    v1.metric(
        "Tokens Tracked",
        len(history_df)
    )

    v2.metric(
        "Completed 5m Tests",
        len(completed)
    )

    if not completed.empty:

        returns = pd.to_numeric(
            completed["5m %"],
            errors="coerce"
        ).dropna()

        v3.metric(
            "5m Positive Rate",
            (
                f"{returns.gt(0).mean() * 100:.1f}%"
                if not returns.empty
                else "—"
            )
        )

    else:

        v3.metric(
            "5m Positive Rate",
            "—"
        )

    with st.expander(
        "Historical performance"
    ):

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# NOTICE
# ============================================================

st.divider()

st.caption(
    """
LIVE mode automatically updates approximately every 30 seconds while
the Streamlit session is active. Discovery is cached separately so the
app can monitor active coins frequently without repeatedly rebuilding
the entire discovery universe.

The scanner evaluates observable market behavior. It cannot guarantee
profit, identify every malicious contract, or determine an optimal
entry/exit with certainty. STRONG SETUP is a research signal, not a
guaranteed buy instruction. EXIT WARNING means measured conditions
have deteriorated, not that a particular sale price is guaranteed to
be optimal.
"""
)
