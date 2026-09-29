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
    "Live Solana scanner • breakout detection • risk filtering • "
    "momentum analysis • deterioration warnings"
)

PROFILE_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


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

            # Choose the pair with the most USD liquidity.
            pair = max(
                solana_pairs,
                key=lambda p: num(
                    (p.get("liquidity") or {}).get("usd")
                )
            )

            base_token = pair.get("baseToken") or {}

            symbol = base_token.get("symbol") or "???"

            liquidity = num(
                (pair.get("liquidity") or {}).get("usd")
            )

            market_cap = num(
                pair.get("marketCap") or pair.get("fdv")
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

            buys5 = num(transactions5.get("buys"))
            sells5 = num(transactions5.get("sells"))

            buys1h = num(transactions1h.get("buys"))
            sells1h = num(transactions1h.get("sells"))

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
            # MOMENTUM SCORE
            # ====================================================

            momentum = 0

            # Recent trading activity
            momentum += min(
                20,
                trades5 * 0.4
            )

            # Five-minute buy pressure
            if buy_ratio5 >= 0.72:
                momentum += 20

            elif buy_ratio5 >= 0.62:
                momentum += 14

            elif buy_ratio5 >= 0.54:
                momentum += 7

            # One-hour confirmation
            if buy_ratio1h >= 0.60:
                momentum += 8

            # Five-minute volume
            if volume5 >= 25000:
                momentum += 15

            elif volume5 >= 10000:
                momentum += 10

            elif volume5 >= 3000:
                momentum += 5

            # Short-term price acceleration
            if 3 <= change5 <= 20:
                momentum += 18

            elif 20 < change5 <= 50:
                momentum += 13

            elif 50 < change5 <= 100:
                momentum += 7

            # Freshness
            if age <= 10:
                momentum += 15

            elif age <= 30:
                momentum += 10

            elif age <= 120:
                momentum += 5

            # Falling-price penalties
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
            # RISK SCORE
            # ====================================================

            risk = 45

            # Liquidity risk
            if liquidity < 3000:
                risk += 35

            elif liquidity < 10000:
                risk += 20

            elif liquidity < 20000:
                risk += 10

            elif liquidity >= 50000:
                risk -= 10

            # Liquidity relative to market cap
            if liquidity_ratio < 0.03:
                risk += 20

            elif liquidity_ratio < 0.08:
                risk += 10

            elif liquidity_ratio >= 0.20:
                risk -= 10

            # Buy/sell pressure
            if trades5 >= 10:

                if buy_ratio5 < 0.40:
                    risk += 25

                elif buy_ratio5 < 0.48:
                    risk += 10

                elif buy_ratio5 >= 0.62:
                    risk -= 5

            # Extreme short-term pump
            if change5 > 100:
                risk += 15

            # Extreme short-term collapse
            if change5 < -25:
                risk += 20

            # Volume relative to liquidity
            if liquidity > 0:

                turnover = volume1h / liquidity

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

            # Hard penalties
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
            # SIGNAL / EXIT ENGINE
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
            # FOMO-COMPATIBILITY SCREEN
            # ====================================================

            # This does NOT claim Fomo itself has confirmed the token.
            # It means the token has the basic Solana market conditions
            # we want before manually searching its contract in Fomo.

            if (
                liquidity >= 5000
                and buys5 > 0
                and sells5 > 0
                and address
            ):
                fomo_status = "🔎 Search contract in Fomo"
            else:
                fomo_status = "❌ Excluded"

            rows.append(
                {
                    "Token": symbol,
                    "Age": display_age(age),
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
# DASHBOARD
# ============================================================

try:

    tokens = scan()

    if tokens.empty:

        st.warning(
            "No Solana tokens are currently available from the scanner."
        )

    else:

        # --------------------------------------------------------
        # SIDEBAR
        # --------------------------------------------------------

        st.sidebar.header(
            "🎯 Scanner Filters"
        )

        max_risk = st.sidebar.slider(
            "Maximum Risk",
            min_value=0,
            max_value=100,
            value=60
        )

        min_liquidity = st.sidebar.number_input(
            "Minimum Liquidity ($)",
            min_value=0,
            value=5000,
            step=1000
        )

        min_signal = st.sidebar.slider(
            "Minimum Moonshot Signal",
            min_value=1.0,
            max_value=10.0,
            value=4.0,
            step=0.1
        )

        if st.sidebar.button(
            "🔄 Refresh Data",
            use_container_width=True
        ):
            st.cache_data.clear()
            st.rerun()

        # --------------------------------------------------------
        # MAIN FILTER
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
        # TOP METRICS
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
                "Nothing currently passes all of your filters. "
                "The scanner will not force a recommendation."
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
        # BREAKOUT / BUILDING CANDIDATES
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

🚀 Moonshot Signal: **{coin['Moonshot']}/10**  
📈 Momentum: **{coin['Momentum']}/100**  
🛡️ Risk: **{coin['Risk']}/100**  
💧 Liquidity: **${coin['Liquidity']:,}**  
📊 5m Volume: **${coin['5m Volume']:,}**  
🟢 5m Buys: **{coin['5m Buys']}**  
🔴 5m Sells: **{coin['5m Sells']}**  
⚖️ Buy Ratio: **{coin['Buy %']}%**  
📈 5m Price: **{coin['5m Change %']}%**

**Fomo check:** {coin['Fomo']}

**Contract:** `{coin['Address']}`
"""
                )

        # --------------------------------------------------------
        # DETERIORATION MONITOR
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

        st.caption(
            "Data is cached for 20 seconds. Use Refresh Data to request a new scan."
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
    "🧪 Development Status"
)

st.write(
    """
The scanner analyzes live Solana market activity and separates
BUILDING, BREAKOUT, WATCH, COOLING, EXIT WARNING and DANGER conditions.

**Fomo:** A token shown in the Opportunity Feed has an active Solana
market, sufficient configured liquidity, recent buys and recent sells.
The contract address is provided so it can be searched in Fomo.

This does **not** mean Fomo has independently confirmed that the token
is executable at that exact moment.

The Moonshot score is a relative experimental signal score — not the
probability of a 50,000% or 100,000% return.

The scoring system has not yet been validated through sufficient
historical testing. The next major upgrade is outcome tracking so the
app can measure what happens after a token is detected.
"""
)
