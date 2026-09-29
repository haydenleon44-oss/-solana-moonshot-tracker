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
    page_title="Solana Trade Radar",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Trade Radar")
st.caption(
    "Find strong early-momentum setups and detect when momentum begins to break down."
)

BASE = "https://api.dexscreener.com"

DISCOVERY_URLS = {
    "Latest": f"{BASE}/token-profiles/latest/v1",
    "Recent": f"{BASE}/token-profiles/recent-updates/v1",
    "Community": f"{BASE}/community-takeovers/latest/v1",
    "Boosts": f"{BASE}/token-boosts/latest/v1",
}

TOKEN_URL = f"{BASE}/latest/dex/tokens/{{}}"


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
        "User-Agent": "SolanaTradeRadar/3.0"
    })
    return s


http = get_session()


def api_get(url, retries=3):

    for attempt in range(retries):

        try:

            r = http.get(
                url,
                timeout=10
            )

            if r.status_code == 429:
                time.sleep(1.5 * (attempt + 1))
                continue

            r.raise_for_status()

            return r.json()

        except requests.RequestException:

            if attempt == retries - 1:
                return None

            time.sleep(0.5 * (attempt + 1))

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
    return max(low, min(high, value))


def now_utc():
    return datetime.now(timezone.utc)


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
            (
                now_utc() - created
            ).total_seconds() / 60
        )

    except Exception:
        return 999999


def age_text(minutes):

    if minutes >= 999999:
        return "Unknown"

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes / 60:.1f}h"

    return f"{minutes / 1440:.1f}d"


def percent_return(start, current):

    start = num(start)
    current = num(current)

    if start <= 0 or current <= 0:
        return None

    return (
        (current / start) - 1
    ) * 100


# ============================================================
# DISCOVERY
# ============================================================

def extract_addresses(data):

    addresses = set()

    if not data:
        return addresses

    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        return addresses

    for item in data:

        if not isinstance(item, dict):
            continue

        if item.get("chainId") != "solana":
            continue

        address = item.get(
            "tokenAddress"
        )

        if address:
            addresses.add(address)

    return addresses


@st.cache_data(ttl=20)
def discover():

    addresses = set()

    for url in DISCOVERY_URLS.values():

        data = api_get(url)

        addresses.update(
            extract_addresses(data)
        )

    return list(addresses)


# ============================================================
# PAIR DATA
# ============================================================

def best_pair(address):

    data = api_get(
        TOKEN_URL.format(address)
    )

    if not data:
        return None

    pairs = data.get("pairs") or []

    solana = [
        p for p in pairs
        if p.get("chainId") == "solana"
    ]

    if not solana:
        return None

    return max(
        solana,
        key=lambda p: num(
            (p.get("liquidity") or {})
            .get("usd")
        )
    )


# ============================================================
# ANALYSIS ENGINE
# ============================================================

def analyze(address, pair):

    base = pair.get("baseToken") or {}

    symbol = (
        base.get("symbol")
        or "UNKNOWN"
    )

    price = num(
        pair.get("priceUsd")
    )

    liquidity = num(
        (pair.get("liquidity") or {})
        .get("usd")
    )

    market_cap = num(
        pair.get("marketCap")
        or pair.get("fdv")
    )

    volume = pair.get("volume") or {}

    volume5 = num(
        volume.get("m5")
    )

    volume1h = num(
        volume.get("h1")
    )

    changes = (
        pair.get("priceChange")
        or {}
    )

    change5 = num(
        changes.get("m5")
    )

    change1h = num(
        changes.get("h1")
    )

    txns = pair.get("txns") or {}

    tx5 = txns.get("m5") or {}
    tx1h = txns.get("h1") or {}

    buys5 = int(
        num(tx5.get("buys"))
    )

    sells5 = int(
        num(tx5.get("sells"))
    )

    buys1h = int(
        num(tx1h.get("buys"))
    )

    sells1h = int(
        num(tx1h.get("sells"))
    )

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
    # DATA QUALITY
    # ========================================================

    data_quality = 100

    if price <= 0:
        data_quality -= 100

    if liquidity <= 0:
        data_quality -= 70

    if market_cap <= 0:
        data_quality -= 10

    if trades5 == 0:
        data_quality -= 20

    data_quality = int(
        clamp(
            data_quality,
            0,
            100
        )
    )

    # ========================================================
    # MOMENTUM
    # ========================================================

    momentum = 0

    momentum += min(
        20,
        trades5 * 0.4
    )

    if trades5 >= 5:

        if buy_ratio >= 0.70:
            momentum += 20

        elif buy_ratio >= 0.62:
            momentum += 14

        elif buy_ratio >= 0.55:
            momentum += 8

        elif buy_ratio < 0.42:
            momentum -= 12

    if trades1h >= 15:

        if buy_ratio1h >= 0.60:
            momentum += 7

        elif buy_ratio1h < 0.43:
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
        momentum += 7

    elif change5 > 150:
        momentum -= 10

    if age <= 10:
        momentum += 15

    elif age <= 30:
        momentum += 10

    elif age <= 120:
        momentum += 5

    if change5 < -10:
        momentum -= 15

    if change5 < -20:
        momentum -= 15

    momentum = int(
        clamp(
            momentum,
            0,
            100
        )
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

    if liquidity < 3000:
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

    if data_quality < 70:
        risk += 30

    risk = int(
        clamp(
            risk,
            0,
            100
        )
    )

    # ========================================================
    # DETERIORATION / EXIT ENGINE
    # ========================================================

    deterioration = 0

    if change5 < -5:
        deterioration += 20

    if change5 < -12:
        deterioration += 20

    if change5 < -20:
        deterioration += 20

    if (
        sells5 > buys5
        and trades5 >= 8
    ):
        deterioration += 20

    if (
        buy_ratio < 0.40
        and trades5 >= 10
    ):
        deterioration += 20

    if momentum < 30:
        deterioration += 10

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

    setup_score = (
        momentum * 0.55
        + liquidity_score * 0.20
        + (100 - risk) * 0.25
    ) / 10

    if liquidity < 5000:
        setup_score -= 2

    if risk >= 75:
        setup_score -= 1.5

    if deterioration >= 50:
        setup_score -= 1

    setup_score = round(
        clamp(
            setup_score,
            1,
            10
        ),
        1
    )

    # ========================================================
    # SIMPLE ACTION
    # ========================================================

    if (
        data_quality < 60
        or liquidity < 3000
        or risk >= 85
    ):

        action = "⛔ AVOID"

        reason = (
            "Very high risk or weak market data"
        )

    elif deterioration >= 70:

        action = "🔴 EXIT WARNING"

        reason = (
            "Momentum and buyer strength are breaking down"
        )

    elif deterioration >= 45:

        action = "🟠 WEAKENING"

        reason = (
            "Selling pressure or momentum deterioration detected"
        )

    elif (
        setup_score >= 7.5
        and momentum >= 75
        and risk <= 50
        and liquidity >= 10000
        and buy_ratio >= 0.60
        and change5 > 0
    ):

        action = "🟢 STRONG SETUP"

        reason = (
            "Strong momentum, buyer pressure and usable liquidity"
        )

    elif (
        setup_score >= 6
        and momentum >= 60
        and risk <= 65
        and liquidity >= 5000
        and buy_ratio >= 0.55
    ):

        action = "🟡 WATCH"

        reason = (
            "Promising activity but confirmation is still developing"
        )

    else:

        action = "⚪ WAIT"

        reason = (
            "No strong setup currently detected"
        )

    return {
        "Token": symbol,
        "Action": action,
        "Score": setup_score,
        "Reason": reason,
        "Age": age_text(age),
        "Age Minutes": age,
        "Momentum": momentum,
        "Risk": risk,
        "Liquidity Quality": liquidity_score,
        "Deterioration": deterioration,
        "Liquidity": round(liquidity),
        "Market Cap": round(market_cap),
        "5m Volume": round(volume5),
        "Buy %": round(
            buy_ratio * 100,
            1
        ),
        "5m Buys": buys5,
        "5m Sells": sells5,
        "5m Change %": round(
            change5,
            2
        ),
        "1h Change %": round(
            change1h,
            2
        ),
        "Price": price,
        "Address": address,
    }


# ============================================================
# SCAN
# ============================================================

@st.cache_data(ttl=20)
def scan():

    addresses = discover()

    rows = []

    for address in addresses[:60]:

        pair = best_pair(address)

        if not pair:
            continue

        try:

            result = analyze(
                address,
                pair
            )

            if result["Price"] > 0:
                rows.append(result)

        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    return (
        df
        .drop_duplicates("Address")
        .sort_values(
            ["Score", "Momentum"],
            ascending=False
        )
    )


# ============================================================
# DATABASE
# ============================================================

def load_history():

    try:

        response = (
            db.table("token_history")
            .select("*")
            .order(
                "detected_at",
                desc=True
            )
            .limit(500)
            .execute()
        )

        return response.data or []

    except Exception:
        return []


def save_new_tokens(
    tokens,
    records
):

    known = {
        row.get("address")
        for row in records
    }

    now = now_utc()

    for _, coin in tokens.iterrows():

        address = coin["Address"]

        if (
            not address
            or address in known
        ):
            continue

        try:

            (
                db.table("token_history")
                .insert({
                    "address":
                        address,

                    "token":
                        coin["Token"],

                    "detected_at":
                        now.isoformat(),

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
                        now.isoformat(),
                })
                .execute()
            )

            known.add(address)

        except Exception:
            continue


# ============================================================
# TRACK OLD TOKENS
# ============================================================

def update_history(
    records,
    live_tokens
):

    now = now_utc()

    live_prices = {}

    if not live_tokens.empty:

        live_prices = {
            row["Address"]:
                num(row["Price"])

            for _, row
            in live_tokens.iterrows()
        }

    checkpoints = {
        "return_5m": 5,
        "return_15m": 15,
        "return_30m": 30,
        "return_1h": 60,
        "return_6h": 360,
        "return_24h": 1440,
    }

    active = []

    for record in records:

        detected = parse_time(
            record.get(
                "detected_at"
            )
        )

        if not detected:
            continue

        elapsed = (
            now - detected
        ).total_seconds() / 60

        if elapsed <= 1500:

            active.append(
                (
                    record,
                    elapsed
                )
            )

    for record, elapsed in active[:60]:

        address = record.get(
            "address"
        )

        start_price = num(
            record.get(
                "start_price"
            )
        )

        if (
            not address
            or start_price <= 0
        ):
            continue

        current = live_prices.get(
            address,
            0
        )

        if current <= 0:

            pair = best_pair(
                address
            )

            if pair:

                current = num(
                    pair.get(
                        "priceUsd"
                    )
                )

        if current <= 0:
            continue

        result = percent_return(
            start_price,
            current
        )

        if result is None:
            continue

        result = round(
            result,
            2
        )

        old_best = num(
            record.get(
                "best_return"
            )
        )

        old_worst = num(
            record.get(
                "worst_return"
            )
        )

        updates = {
            "latest_return":
                result,

            "best_return":
                max(
                    old_best,
                    result
                ),

            "worst_return":
                min(
                    old_worst,
                    result
                ),

            "last_price":
                current,

            "last_updated":
                now.isoformat(),
        }

        for column, minutes in checkpoints.items():

            if (
                elapsed >= minutes
                and record.get(column)
                is None
            ):

                updates[column] = (
                    result
                )

        try:

            (
                db.table(
                    "token_history"
                )
                .update(updates)
                .eq(
                    "address",
                    address
                )
                .execute()
            )

        except Exception:
            continue


# ============================================================
# REFRESH
# ============================================================

if st.sidebar.button(
    "🔄 Scan Now",
    use_container_width=True
):

    st.cache_data.clear()
    st.rerun()


# ============================================================
# RUN
# ============================================================

with st.spinner(
    "Searching Solana markets..."
):

    tokens = scan()


records = load_history()

if not tokens.empty:

    save_new_tokens(
        tokens,
        records
    )


records = load_history()

update_history(
    records,
    tokens
)

records = load_history()


# ============================================================
# SIMPLE DASHBOARD
# ============================================================

if tokens.empty:

    st.warning(
        "No market data was returned."
    )

else:

    strong = tokens[
        tokens["Action"]
        == "🟢 STRONG SETUP"
    ]

    watch = tokens[
        tokens["Action"]
        == "🟡 WATCH"
    ]

    exits = tokens[
        tokens["Action"].isin(
            [
                "🔴 EXIT WARNING",
                "🟠 WEAKENING"
            ]
        )
    ]

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "🟢 Strong Setups",
        len(strong)
    )

    c2.metric(
        "🟡 Watch",
        len(watch)
    )

    c3.metric(
        "🔴 Weakening",
        len(exits)
    )

    c4.metric(
        "📡 Coins Scanned",
        len(tokens)
    )

    # ========================================================
    # STRONG SETUPS
    # ========================================================

    st.subheader(
        "🟢 Strong Setups"
    )

    st.caption(
        "Highest-quality setups detected by the current experimental model."
    )

    if strong.empty:

        st.info(
            "No strong setup right now. "
            "The scanner is waiting instead of forcing a trade."
        )

    else:

        for _, coin in strong.head(10).iterrows():

            st.success(
                f"""
### {coin['Token']}

**🟢 STRONG SETUP**

Signal strength: **{coin['Score']}/10**

{coin['Reason']}

Momentum: **{coin['Momentum']}/100**  
Risk: **{coin['Risk']}/100**  
Buyer share: **{coin['Buy %']}%**  
Liquidity: **${coin['Liquidity']:,}**  
5-minute move: **{coin['5m Change %']}%**  
Age: **{coin['Age']}**

Contract:

`{coin['Address']}`

**Fomo:** Search the contract manually before attempting an order.
"""
            )

    # ========================================================
    # WATCHLIST
    # ========================================================

    st.subheader(
        "🟡 Developing Watchlist"
    )

    if watch.empty:

        st.write(
            "No developing setups currently qualify."
        )

    else:

        st.dataframe(
            watch[
                [
                    "Token",
                    "Score",
                    "Momentum",
                    "Risk",
                    "Buy %",
                    "Liquidity",
                    "5m Change %",
                    "Age",
                    "Address",
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # EXIT / WEAKENING
    # ========================================================

    st.subheader(
        "🔴 Momentum Breakdown"
    )

    st.caption(
        "These are deterioration warnings, not guaranteed optimal sell prices."
    )

    if exits.empty:

        st.write(
            "No major deterioration signals currently detected."
        )

    else:

        st.dataframe(
            exits[
                [
                    "Token",
                    "Action",
                    "Deterioration",
                    "Momentum",
                    "Risk",
                    "Buy %",
                    "5m Change %",
                    "Liquidity",
                    "Address",
                ]
            ],
            use_container_width=True,
            hide_index=True
        )

    # ========================================================
    # ALL COINS
    # ========================================================

    with st.expander(
        "🔬 Advanced Data"
    ):

        st.dataframe(
            tokens[
                [
                    "Token",
                    "Action",
                    "Score",
                    "Momentum",
                    "Risk",
                    "Liquidity Quality",
                    "Deterioration",
                    "Liquidity",
                    "Market Cap",
                    "5m Volume",
                    "5m Buys",
                    "5m Sells",
                    "Buy %",
                    "5m Change %",
                    "1h Change %",
                    "Age",
                    "Address",
                ]
            ],
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# PERFORMANCE LAB
# ============================================================

st.divider()

st.subheader(
    "🧪 Model Performance"
)

history_rows = []

for record in records:

    history_rows.append({
        "Token":
            record.get("token"),

        "Initial Signal":
            record.get(
                "start_moonshot"
            ),

        "Initial Status":
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
    history_rows
)


if history_df.empty:

    st.info(
        "The model is collecting its first observations."
    )

else:

    completed = history_df[
        history_df["5m %"].notna()
    ].copy()

    p1, p2, p3 = st.columns(3)

    p1.metric(
        "Tokens Tracked",
        len(history_df)
    )

    p2.metric(
        "Completed 5m Tests",
        len(completed)
    )

    if not completed.empty:

        values = pd.to_numeric(
            completed["5m %"],
            errors="coerce"
        ).dropna()

        p3.metric(
            "5m Positive Rate",
            (
                f"{values.gt(0).mean() * 100:.1f}%"
                if not values.empty
                else "—"
            )
        )

    else:

        p3.metric(
            "5m Positive Rate",
            "—"
        )

    with st.expander(
        "View historical tests"
    ):

        st.dataframe(
            history_df,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# IMPORTANT
# ============================================================

st.divider()

st.caption(
    """
The scanner identifies market setups from available trading data.
STRONG SETUP does not mean guaranteed profit or that a token is safe.
The risk model cannot currently detect every malicious contract,
creator-wallet action, holder concentration, bundled launch, or rug.
Performance tracking is being used to test whether the model's signals
actually have predictive value before they should be relied on with
significant real money.
"""
)
