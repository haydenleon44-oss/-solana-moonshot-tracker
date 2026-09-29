import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timezone

st.set_page_config(
    page_title="Solana Moonshot Tracker",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Moonshot Tracker")
st.caption(
    "Live Solana scanner • breakout detection • risk filtering • exit warnings"
)

PROFILE_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


# ------------------------------------------------
# HELPERS
# ------------------------------------------------

def num(value):
    try:
        return float(value or 0)
    except:
        return 0


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

    except:
        return 999999


def display_age(minutes):

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes/60:.1f}h"

    return f"{minutes/1440:.1f}d"


# ------------------------------------------------
# LIVE DATA
# ------------------------------------------------

@st.cache_data(ttl=20)
def scan():

    response = requests.get(
        PROFILE_URL,
        timeout=15
    )

    response.raise_for_status()

    profiles = response.json()

    solana = [
        p for p in profiles
        if p.get("chainId") == "solana"
    ]

    rows = []

    for profile in solana[:30]:

        address = profile.get("tokenAddress")

        try:

            response = requests.get(
                TOKEN_URL.format(address),
                timeout=10
            )

            response.raise_for_status()

            pairs = response.json().get("pairs") or []

            pairs = [
                p for p in pairs
                if p.get("chainId") == "solana"
            ]

            if not pairs:
                continue

            # Use highest-liquidity pair
            pair = max(
                pairs,
                key=lambda p: num(
                    (p.get("liquidity") or {}).get("usd")
                )
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

            txns = pair.get("txns") or {}

            t5 = txns.get("m5") or {}
            t1 = txns.get("h1") or {}

            buys5 = num(t5.get("buys"))
            sells5 = num(t5.get("sells"))

            buys1 = num(t1.get("buys"))
            sells1 = num(t1.get("sells"))

            trades5 = buys5 + sells5
            trades1 = buys1 + sells1

            buy_ratio5 = (
                buys5 / trades5
                if trades5 else 0
            )

            buy_ratio1 = (
                buys1 / trades1
                if trades1 else 0
            )

            age = age_minutes(
                pair.get("pairCreatedAt")
            )

            liq_ratio = (
                liquidity / market_cap
                if market_cap > 0
                else 0
            )

            # ========================================
            # MOMENTUM SCORE
            # ========================================

            momentum = 0

            # Recent transaction activity
            momentum += min(
                20,
                trades5 * 0.4
            )

            # Buy pressure
            if buy_ratio5 >= .72:
                momentum += 20

            elif buy_ratio5 >= .62:
                momentum += 14

            elif buy_ratio5 >= .54:
                momentum += 7

            # 1-hour confirmation
            if buy_ratio1 >= .60:
                momentum += 8

            # Recent volume
            if volume5 >= 25000:
                momentum += 15

            elif volume5 >= 10000:
                momentum += 10

            elif volume5 >= 3000:
                momentum += 5

            # Healthy short-term price acceleration
            if 3 <= change5 <= 20:
                momentum += 18

            elif 20 < change5 <= 50:
                momentum += 13

            elif 50 < change5 <= 100:
                momentum += 7

            # Launch freshness
            if age <= 10:
                momentum += 15

            elif age <= 30:
                momentum += 10

            elif age <= 120:
                momentum += 5

            # Negative-price penalties
            if change5 <= -10:
                momentum -= 15

            if change5 <= -20:
                momentum -= 15

            momentum = int(
                max(0, min(100, momentum))
            )

            # ========================================
            # RISK SCORE
            # ========================================

            risk = 45

            # Liquidity
            if liquidity < 3000:
                risk += 35

            elif liquidity < 10000:
                risk += 20

            elif liquidity < 20000:
                risk += 10

            elif liquidity >= 50000:
                risk -= 10

            # Liquidity vs market cap
            if liq_ratio < .03:
                risk += 20

            elif liq_ratio < .08:
                risk += 10

            elif liq_ratio >= .20:
                risk -= 10

            # Sell pressure
            if trades5 >= 10:

                if buy_ratio5 < .40:
                    risk += 25

                elif buy_ratio5 < .48:
                    risk += 10

                elif buy_ratio5 >= .62:
                    risk -= 5

            # Extreme pump
            if change5 > 100:
                risk += 15

            # Extreme crash
            if change5 < -25:
                risk += 20

            # Suspicious turnover
            if liquidity > 0:

                turnover = volume1h / liquidity

                if turnover > 20:
                    risk += 15

                elif turnover > 10:
                    risk += 7

            risk = int(
                max(0, min(100, risk))
            )

            # ========================================
            # MOONSHOT SIGNAL
            # ========================================

            signal = (
                momentum * .70
                + (100 - risk) * .30
            ) / 10

            # Hard penalties
            if liquidity < 5000:
                signal -= 1.5

            if risk >= 75:
                signal -= 1.5

            if change5 <= -20:
                signal -= 1

            signal = round(
                max(1, min(10, signal)),
                1
            )

            # ========================================
            # ENTRY / EXIT ENGINE
            # ========================================

            # Severe danger first
            if (
                risk >= 80
                or liquidity < 2000
            ):

                status = "🚨 DANGER"

            # Strong deterioration
            elif (
                change5 <= -15
                and sells5 > buys5
            ):

                status = "🔴 EXIT WARNING"

            # Price collapsing even if buys look active
            elif change5 <= -25:

                status = "🔴 COOLING FAST"

            # Strong breakout conditions
            elif (
                momentum >= 80
                and risk <= 45
                and buy_ratio5 >= .60
                and change5 > 0
            ):

                status = "🔥 BREAKOUT"

            # Early acceleration
            elif (
                momentum >= 65
                and risk <= 60
                and buy_ratio5 >= .55
                and change5 > 0
            ):

                status = "🟢 BUILDING"

            # Momentum but no confirmation
            elif momentum >= 55:

                status = "👀 WATCH"

            else:

                status = "⚪ WEAK"

            rows.append({

                "Token":
                    pair.get(
                        "baseToken", {}
                    ).get("symbol", "???"),

                "Age":
                    display_age(age),

                "Moonshot":
                    signal,

                "Momentum":
                    momentum,

                "Risk":
                    risk,

                "Market Cap":
                    round(market_cap),

                "Liquidity":
                    round(liquidity),

                "5m Volume":
                    round(volume5),

                "5m Buys":
                    int(buys5),

                "5m Sells":
                    int(sells5),

                "Buy %":
                    round(
                        buy_ratio5 * 100,
                        1
                    ),

                "5m Change %":
                    round(change5, 2),

                "1h Change %":
                    round(change1h, 2),

                "Status":
                    status,

                "Address":
                    address
            })

        except:
            continue

    return pd.DataFrame(rows)


# ------------------------------------------------
# DASHBOARD
# ------------------------------------------------

try:

    tokens = scan()

    if tokens.empty:

        st.warning(
            "No Solana tokens currently available."
        )

    else:

        st.sidebar.header(
            "🎯 Scanner Filters"
        )

        max_risk = st.sidebar.slider(
            "Maximum Risk",
            0,
            100,
            60
        )

        min_liq = st.sidebar.number_input(
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
            .1
        )

        filtered = tokens[
            (tokens["Risk"] <= max_risk)
            &
            (tokens["Liquidity"] >= min_liq)
            &
            (tokens["Moonshot"] >= min_signal)
        ]

        filtered = filtered.sort_values(
            ["Moonshot", "Momentum"],
            ascending=False
        )

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "🔥 Passing Filters",
            len(filtered)
        )

        c2.metric(
            "🚀 Highest Signal",
            (
                f"{filtered['Moonshot'].max()}/10"
                if len(filtered)
                else "—"
            )
        )

        c3.metric(
            "📈 Highest Momentum",
            (
                f"{filtered['Momentum'].max()}/100"
                if len(filtered)
                else "—"
            )
        )

        c4.metric(
            "🛡️ Lowest Risk",
            (
                f"{filtered['Risk'].min()}/100"
                if len(filtered)
                else "—"
            )
        )

        st.subheader(
            "🔥 Live Opportunity Feed"
        )

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True
        )

        # ========================================
        # BEST CURRENT SETUPS
        # ========================================

        candidates = filtered[
            filtered["Status"].isin(
                [
                    "🔥 BREAKOUT",
                    "🟢 BUILDING"
                ]
            )
        ]

        if len(candidates):

            st.subheader(
                "🚀 Current Momentum Setups"
            )

            for _, coin in candidates.iterrows():

                st.success(
                    f"""
**{coin['Token']}**

🚀 Signal: **{coin['Moonshot']}/10**  
📈 Momentum: **{coin['Momentum']}/100**  
🛡️ Risk: **{coin['Risk']}/100**  
💧 Liquidity: **${coin['Liquidity']:,}**  
🟢 5m Buys: **{coin['5m Buys']}**  
🔴 5m Sells: **{coin['5m Sells']}**  
⚖️ Buy Ratio: **{coin['Buy %']}%**  
📊 5m Price: **{coin['5m Change %']}%**

**{coin['Status']}**
"""
                )

        # ========================================
        # EXIT WARNINGS
        # ========================================

        exits = tokens[
            tokens["Status"].isin(
                [
                    "🔴 EXIT WARNING",
                    "🔴 COOLING FAST",
                    "🚨 DANGER"
                ]
            )
        ]

        if len(exits):

            st.subheader(
                "⚠️ Deterioration Monitor"
            )

            for _, coin in exits.head(5).iterrows():

                st.error(
                    f"""
**{coin['Token']}**

Status: **{coin['Status']}**  
5m Price: **{coin['5m Change %']}%**  
Buy Ratio: **{coin['Buy %']}%**  
Risk: **{coin['Risk']}/100**
"""
                )

        st.caption(
            "Scanner data refreshes approximately every 20 seconds."
        )

except Exception as error:

    st.error(
        "Scanner failed to load."
    )

    st.code(str(error))


st.divider()

st.subheader("🧪 Development Status")

st.write("""
This version distinguishes between **BUILDING, BREAKOUT, WATCH,
COOLING, EXIT WARNING and DANGER** conditions.

The Moonshot score measures relative signal strength. It is **not**
the probability of a 50,000% or 100,000% return.

The next major step is historical tracking/backtesting. Until we have
measured how these signals perform over many launches, they should be
treated as experimental rather than reliable trading recommendations.
""")
