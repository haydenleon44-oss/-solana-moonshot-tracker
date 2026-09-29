import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timezone

# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Solana Moonshot Tracker",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Moonshot Tracker")
st.caption(
    "Live Solana scanner • momentum detection • risk filtering • "
    "Fomo compatibility screening • performance tracking"
)

PROFILE_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


# ============================================================
# SESSION HISTORY
# ============================================================

if "token_history" not in st.session_state:
    st.session_state.token_history = {}


# ============================================================
# HELPERS
# ============================================================

def num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def age_minutes(created):
    if not created:
        return 999999

    try:
        created_time = datetime.fromtimestamp(
            created / 1000,
            tz=timezone.utc
        )

        now = datetime.now(timezone.utc)

        return max(
            0,
            (now - created_time).total_seconds() / 60
        )

    except (TypeError, ValueError, OSError):
        return 999999


def display_age(minutes):
    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes / 60:.1f}h"

    return f"{minutes / 1440:.1f}d"


def percent_change(start_price, current_price):
    if start_price <= 0:
        return None

    return (
        (current_price - start_price)
        / start_price
    ) * 100


# ============================================================
# LIVE SCANNER
# ============================================================

@st.cache_data(ttl=20)
def scan():

    response = requests.get(
        PROFILE_URL,
        timeout=15
    )

    response.raise_for_status()

    profiles = response.json()

    solana_profiles = [
        profile
        for profile in profiles
        if profile.get("chainId") == "solana"
    ]

    rows = []

    for profile in solana_profiles[:30]:

        address = profile.get("tokenAddress")

        if not address:
            continue

        try:

            response = requests.get(
                TOKEN_URL.format(address),
                timeout=10
            )

            response.raise_for_status()

            pairs = response.json().get("pairs") or []

            solana_pairs = [
                pair
                for pair in pairs
                if pair.get("chainId") == "solana"
            ]

            if not solana_pairs:
                continue

            pair = max(
                solana_pairs,
                key=lambda p: num(
                    (p.get("liquidity") or {}).get("usd")
                )
            )

            base_token = pair.get("baseToken") or {}

            symbol = base_token.get("symbol") or "???"

            price_usd = num(
                pair.get("priceUsd")
            )

            liquidity = num(
                (pair.get("liquidity") or {}).get("usd")
            )

            market_cap = num(
                pair.get("marketCap")
                or pair.get("fdv")
            )

            volumes = pair.get("volume") or {}

            volume5 = num(volumes.get("m5"))
            volume1h = num(volumes.get("h1"))

            changes = pair.get("priceChange") or {}

            change5 = num(changes.get("m5"))
            change1h = num(changes.get("h1"))

            transactions = pair.get("txns") or {}

            transactions5 = transactions.get("m5") or {}
            transactions1h = transactions.get("h1") or {}

            buys5 = num(
                transactions5.get("buys")
            )

            sells5 = num(
                transactions5.get("sells")
            )

            buys1h = num(
                transactions1h.get("buys")
            )

            sells1h = num(
                transactions1h.get("sells")
            )

            trades5 = buys5 + sells5
            trades1h = buys1h + sells1h

            buy_ratio5 = (
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

            # ====================================================
            # MOMENTUM
            # ====================================================

            momentum = 0

            momentum += min(
                20,
                trades5 * 0.4
            )

            if buy_ratio5 >= 0.72:
                momentum += 20

            elif buy_ratio5 >= 0.62:
                momentum += 14

            elif buy_ratio5 >= 0.54:
                momentum += 7

            if buy_ratio1h >= 0.60:
                momentum += 8

            if volume5 >= 25000:
                momentum += 15

            elif volume5 >= 10000:
                momentum += 10

            elif volume5 >= 3000:
                momentum += 5

            if 3 <= change5 <= 20:
                momentum += 18

            elif 20 < change5 <= 50:
                momentum += 13

            elif 50 < change5 <= 100:
                momentum += 7

            if age <= 10:
                momentum += 15

            elif age <= 30:
                momentum += 10

            elif age <= 120:
                momentum += 5

            if change5 <= -10:
                momentum -= 15

            if change5 <= -20:
                momentum -= 15

            momentum = int(
                max(
                    0,
                    min(100, momentum)
                )
            )

            # ====================================================
            # RISK
            # ====================================================

            risk = 45

            if liquidity < 3000:
                risk += 35

            elif liquidity < 10000:
                risk += 20

            elif liquidity < 20000:
                risk += 10

            elif liquidity >= 50000:
                risk -= 10

            if liquidity_ratio < 0.03:
                risk += 20

            elif liquidity_ratio < 0.08:
                risk += 10

            elif liquidity_ratio >= 0.20:
                risk -= 10

            if trades5 >= 10:

                if buy_ratio5 < 0.40:
                    risk += 25

                elif buy_ratio5 < 0.48:
                    risk += 10

                elif buy_ratio5 >= 0.62:
                    risk -= 5

            if change5 > 100:
                risk += 15

            if change5 < -25:
                risk += 20

            if liquidity > 0:

                turnover = (
                    volume1h / liquidity
                )

                if turnover > 20:
                    risk += 15

                elif turnover > 10:
                    risk += 7

            risk = int(
                max(
                    0,
                    min(100, risk)
                )
            )

            # ====================================================
            # MOONSHOT SIGNAL
            # ====================================================

            moonshot = (
                momentum * 0.70
                + (100 - risk) * 0.30
            ) / 10

            if liquidity < 5000:
                moonshot -= 1.5

            if risk >= 75:
                moonshot -= 1.5

            if change5 <= -20:
                moonshot -= 1.0

            moonshot = round(
                max(
                    1,
                    min(10, moonshot)
                ),
                1
            )

            # ====================================================
            # STATUS ENGINE
            # ====================================================

            if (
                risk >= 80
                or liquidity < 2000
            ):

                status = "🚨 DANGER"

            elif change5 <= -25:

                status = "🔴 EXIT WARNING"

            elif (
                change5 <= -15
                and sells5 > buys5
            ):

                status = "🔴 EXIT WARNING"

            elif (
                change5 <= -10
                and momentum < 60
            ):

                status = "🟡 COOLING"

            elif (
                momentum >= 80
                and risk <= 45
                and buy_ratio5 >= 0.60
                and change5 > 0
            ):

                status = "🔥 BREAKOUT"

            elif (
                momentum >= 65
                and risk <= 60
                and buy_ratio5 >= 0.55
                and change5 > 0
            ):

                status = "🟢 BUILDING"

            elif momentum >= 55:

                status = "👀 WATCH"

            else:

                status = "⚪ WEAK"

            # ====================================================
            # FOMO COMPATIBILITY SCREEN
            # ====================================================

            if (
                liquidity >= 5000
                and buys5 > 0
                and sells5 > 0
                and address
            ):

                fomo_status = (
                    "🔎 Search contract in Fomo"
                )

            else:

                fomo_status = "❌ Excluded"

            rows.append(
                {
                    "Token": symbol,
                    "Age": display_age(age),
                    "Price": price_usd,
                    "Moonshot": moonshot,
                    "Momentum": momentum,
                    "Risk": risk,
                    "Market Cap": round(market_cap),
                    "Liquidity": round(liquidity),
                    "5m Volume": round(volume5),
                    "1h Volume": round(volume1h),
                    "5m Buys": int(buys5),
                    "5m Sells": int(sells5),
                    "Buy %": round(
                        buy_ratio5 * 100,
                        1
                    ),
                    "5m Change %": round(
                        change5,
                        2
                    ),
                    "1h Change %": round(
                        change1h,
                        2
                    ),
                    "Status": status,
                    "Fomo": fomo_status,
                    "Address": address
                }
            )

        except requests.RequestException:
            continue

        except Exception:
            continue

    return pd.DataFrame(rows)


# ============================================================
# PERFORMANCE TRACKING
# ============================================================

def update_history(tokens):

    now = datetime.now(timezone.utc)

    checkpoints = {
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "6h": 360,
        "24h": 1440
    }

    for _, token in tokens.iterrows():

        address = token["Address"]
        price = num(token["Price"])

        if not address or price <= 0:
            continue

        if address not in st.session_state.token_history:

            st.session_state.token_history[address] = {
                "Token": token["Token"],
                "Address": address,
                "Detected": now,
                "Start Price": price,
                "Start Moonshot": token["Moonshot"],
                "Start Momentum": token["Momentum"],
                "Start Risk": token["Risk"],
                "Start Status": token["Status"],
                "5m": None,
                "15m": None,
                "30m": None,
                "1h": None,
                "6h": None,
                "24h": None,
                "Latest": 0.0,
                "Best": 0.0,
                "Worst": 0.0
            }

        record = st.session_state.token_history[
            address
        ]

        elapsed = (
            now - record["Detected"]
        ).total_seconds() / 60

        performance = percent_change(
            record["Start Price"],
            price
        )

        if performance is None:
            continue

        record["Latest"] = round(
            performance,
            2
        )

        record["Best"] = round(
            max(
                record["Best"],
                performance
            ),
            2
        )

        record["Worst"] = round(
            min(
                record["Worst"],
                performance
            ),
            2
        )

        for label, minutes in checkpoints.items():

            if (
                elapsed >= minutes
                and record[label] is None
            ):

                record[label] = round(
                    performance,
                    2
                )


def history_dataframe():

    rows = []

    for record in st.session_state.token_history.values():

        detected = record["Detected"]

        rows.append(
            {
                "Token":
                    record["Token"],

                "Detected":
                    detected.strftime(
                        "%H:%M:%S"
                    ),

                "Start Signal":
                    record["Start Moonshot"],

                "Start Momentum":
                    record["Start Momentum"],

                "Start Risk":
                    record["Start Risk"],

                "Start Status":
                    record["Start Status"],

                "Latest %":
                    record["Latest"],

                "Best %":
                    record["Best"],

                "Worst %":
                    record["Worst"],

                "5m %":
                    record["5m"],

                "15m %":
                    record["15m"],

                "30m %":
                    record["30m"],

                "1h %":
                    record["1h"],

                "6h %":
                    record["6h"],

                "24h %":
                    record["24h"],

                "Address":
                    record["Address"]
            }
        )

    return pd.DataFrame(rows)


# ============================================================
# DASHBOARD
# ============================================================

try:

    tokens = scan()

    if tokens.empty:

        st.warning(
            "No Solana tokens are currently available."
        )

    else:

        # Track everything returned by scanner.
        update_history(tokens)

        # --------------------------------------------------------
        # SIDEBAR
        # --------------------------------------------------------

        st.sidebar.header(
            "🎯 Scanner Filters"
        )

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
            "Minimum Moonshot Signal",
            1.0,
            10.0,
            4.0,
            0.1
        )

        if st.sidebar.button(
            "🔄 Refresh Data",
            use_container_width=True
        ):

            st.cache_data.clear()
            st.rerun()

        # --------------------------------------------------------
        # FILTERED FEED
        # --------------------------------------------------------

        filtered = tokens[
            (tokens["Risk"] <= max_risk)
            &
            (tokens["Liquidity"] >= min_liquidity)
            &
            (tokens["Moonshot"] >= min_signal)
            &
            (tokens["5m Buys"] > 0)
            &
            (tokens["5m Sells"] > 0)
            &
            (tokens["Fomo"] != "❌ Excluded")
        ].copy()

        filtered = filtered.sort_values(
            ["Moonshot", "Momentum"],
            ascending=False
        )

        # --------------------------------------------------------
        # METRICS
        # --------------------------------------------------------

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "🔥 Passing Filters",
            len(filtered)
        )

        col2.metric(
            "🚀 Highest Signal",
            (
                f"{filtered['Moonshot'].max():.1f}/10"
                if not filtered.empty
                else "—"
            )
        )

        col3.metric(
            "📈 Highest Momentum",
            (
                f"{int(filtered['Momentum'].max())}/100"
                if not filtered.empty
                else "—"
            )
        )

        col4.metric(
            "🛡️ Lowest Risk",
            (
                f"{int(filtered['Risk'].min())}/100"
                if not filtered.empty
                else "—"
            )
        )

        # --------------------------------------------------------
        # OPPORTUNITY FEED
        # --------------------------------------------------------

        st.subheader(
            "🔥 Live Opportunity Feed"
        )

        if filtered.empty:

            st.info(
                "Nothing currently passes all filters."
            )

        else:

            display_columns = [
                "Token",
                "Age",
                "Moonshot",
                "Momentum",
                "Risk",
                "Market Cap",
                "Liquidity",
                "5m Volume",
                "5m Buys",
                "5m Sells",
                "Buy %",
                "5m Change %",
                "1h Change %",
                "Status",
                "Fomo",
                "Address"
            ]

            st.dataframe(
                filtered[display_columns],
                use_container_width=True,
                hide_index=True
            )

        # --------------------------------------------------------
        # CURRENT SETUPS
        # --------------------------------------------------------

        candidates = filtered[
            filtered["Status"].isin(
                [
                    "🔥 BREAKOUT",
                    "🟢 BUILDING"
                ]
            )
        ]

        if not candidates.empty:

            st.subheader(
                "🚀 Current Momentum Setups"
            )

            for _, coin in candidates.iterrows():

                st.success(
                    f"""
**{coin['Token']}**

Status: **{coin['Status']}**

🚀 Signal: **{coin['Moonshot']}/10**  
📈 Momentum: **{coin['Momentum']}/100**  
🛡️ Risk: **{coin['Risk']}/100**  
💧 Liquidity: **${coin['Liquidity']:,}**  
📊 5m Volume: **${coin['5m Volume']:,}**  
🟢 Buys: **{coin['5m Buys']}**  
🔴 Sells: **{coin['5m Sells']}**  
⚖️ Buy Ratio: **{coin['Buy %']}%**  
📈 5m Price: **{coin['5m Change %']}%**

Fomo: **{coin['Fomo']}**

Contract:

`{coin['Address']}`
"""
                )

        # --------------------------------------------------------
        # DETERIORATION
        # --------------------------------------------------------

        danger_tokens = tokens[
            tokens["Status"].isin(
                [
                    "🟡 COOLING",
                    "🔴 EXIT WARNING",
                    "🚨 DANGER"
                ]
            )
        ].copy()

        if not danger_tokens.empty:

            danger_tokens = danger_tokens.sort_values(
                ["Risk", "5m Change %"],
                ascending=[False, True]
            )

            st.subheader(
                "⚠️ Deterioration Monitor"
            )

            for _, coin in danger_tokens.head(5).iterrows():

                st.error(
                    f"""
**{coin['Token']}**

Status: **{coin['Status']}**  
5m Price: **{coin['5m Change %']}%**  
Buy Ratio: **{coin['Buy %']}%**  
Momentum: **{coin['Momentum']}/100**  
Risk: **{coin['Risk']}/100**
"""
                )

        # --------------------------------------------------------
        # PERFORMANCE LAB
        # --------------------------------------------------------

        st.divider()

        st.subheader(
            "🧪 Signal Performance Lab"
        )

        st.caption(
            "Tracks what happens after this session first detects a token."
        )

        history = history_dataframe()

        if not history.empty:

            st.metric(
                "Tokens Being Tracked",
                len(history)
            )

            history = history.sort_values(
                "Start Signal",
                ascending=False
            )

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True
            )

            completed5 = history[
                history["5m %"].notna()
            ]

            if not completed5.empty:

                st.subheader(
                    "📊 Early Results"
                )

                result1, result2, result3 = st.columns(3)

                result1.metric(
                    "5m Samples",
                    len(completed5)
                )

                result2.metric(
                    "Average 5m Return",
                    f"{completed5['5m %'].mean():.2f}%"
                )

                winners = (
                    completed5["5m %"] > 0
                ).mean() * 100

                result3.metric(
                    "5m Positive Rate",
                    f"{winners:.1f}%"
                )

        st.caption(
            "Click Refresh Data to collect another live snapshot."
        )


except requests.RequestException as error:

    st.error(
        "DexScreener could not be reached."
    )

    st.code(str(error))


except Exception as error:

    st.error(
        "The scanner failed to load."
    )

    st.code(str(error))


# ============================================================
# DEVELOPMENT NOTICE
# ============================================================

st.divider()

st.subheader(
    "🔬 Tracker Status"
)

st.write(
    """
The app is now collecting experimental outcome data.

When a token is first observed, its price, Moonshot score,
Momentum score, Risk score and status are recorded. Later scans
measure its return relative to that detection price.

The 5-minute, 15-minute, 30-minute, 1-hour, 6-hour and 24-hour
columns fill in as those checkpoints are reached.

**Important:** this version stores history only in the current
Streamlit session. A server restart or session reset can erase it.
Persistent storage is the next infrastructure upgrade.

The Moonshot score is still experimental and should not be interpreted
as a probability or guarantee of future returns.
"""
)
