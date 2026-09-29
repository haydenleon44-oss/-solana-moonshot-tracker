import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timezone

st.set_page_config(
    page_title="Solana Moonshot Tracker",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Moonshot Tracker")
st.caption("Live Solana scanner • early momentum • risk filtering • exit warnings")

PROFILE_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{}"


def safe_num(value):
    try:
        return float(value or 0)
    except:
        return 0


def token_age_minutes(created_at):
    if not created_at:
        return 999999

    try:
        created = datetime.fromtimestamp(
            created_at / 1000,
            tz=timezone.utc
        )

        now = datetime.now(timezone.utc)

        return max(
            0,
            (now - created).total_seconds() / 60
        )
    except:
        return 999999


def age_display(minutes):

    if minutes < 60:
        return f"{int(minutes)}m"

    if minutes < 1440:
        return f"{minutes / 60:.1f}h"

    return f"{minutes / 1440:.1f}d"


@st.cache_data(ttl=20)
def get_live_tokens():

    profiles = requests.get(
        PROFILE_URL,
        timeout=15
    ).json()

    solana = [
        x for x in profiles
        if x.get("chainId") == "solana"
    ]

    rows = []

    for profile in solana[:30]:

        address = profile.get("tokenAddress")

        try:

            response = requests.get(
                TOKEN_URL.format(address),
                timeout=10
            )

            pairs = response.json().get("pairs") or []

            pairs = [
                p for p in pairs
                if p.get("chainId") == "solana"
            ]

            if not pairs:
                continue

            pair = max(
                pairs,
                key=lambda p:
                safe_num(
                    (p.get("liquidity") or {}).get("usd")
                )
            )

            liquidity = safe_num(
                (pair.get("liquidity") or {}).get("usd")
            )

            market_cap = safe_num(
                pair.get("marketCap")
                or pair.get("fdv")
            )

            volume = pair.get("volume") or {}

            volume_5m = safe_num(volume.get("m5"))
            volume_1h = safe_num(volume.get("h1"))
            volume_24h = safe_num(volume.get("h24"))

            changes = pair.get("priceChange") or {}

            change_5m = safe_num(changes.get("m5"))
            change_1h = safe_num(changes.get("h1"))

            txns = pair.get("txns") or {}

            m5 = txns.get("m5") or {}
            h1 = txns.get("h1") or {}

            buys_5m = safe_num(m5.get("buys"))
            sells_5m = safe_num(m5.get("sells"))

            buys_1h = safe_num(h1.get("buys"))
            sells_1h = safe_num(h1.get("sells"))

            trades_5m = buys_5m + sells_5m
            trades_1h = buys_1h + sells_1h

            buy_ratio_5m = (
                buys_5m / trades_5m
                if trades_5m else 0
            )

            buy_ratio_1h = (
                buys_1h / trades_1h
                if trades_1h else 0
            )

            age_min = token_age_minutes(
                pair.get("pairCreatedAt")
            )

            # --------------------------
            # LIQUIDITY QUALITY
            # --------------------------

            liq_mcap_ratio = (
                liquidity / market_cap
                if market_cap > 0
                else 0
            )

            # --------------------------
            # MOMENTUM
            # --------------------------

            momentum = 0

            # Very recent transactions
            momentum += min(
                20,
                trades_5m * 0.5
            )

            # 5m buy pressure
            if buy_ratio_5m >= .70:
                momentum += 20

            elif buy_ratio_5m >= .60:
                momentum += 14

            elif buy_ratio_5m >= .52:
                momentum += 7

            # 1h confirmation
            if buy_ratio_1h >= .60:
                momentum += 10

            # Recent volume
            if volume_5m >= 25000:
                momentum += 15

            elif volume_5m >= 10000:
                momentum += 10

            elif volume_5m >= 3000:
                momentum += 5

            # Price acceleration
            if 5 <= change_5m <= 30:
                momentum += 15

            elif 30 < change_5m <= 80:
                momentum += 10

            elif change_5m > 80:
                momentum += 4

            # Early-launch bonus
            if age_min <= 10:
                momentum += 15

            elif age_min <= 30:
                momentum += 10

            elif age_min <= 120:
                momentum += 5

            momentum = round(
                min(100, momentum)
            )

            # --------------------------
            # RISK SCORE
            # --------------------------

            risk = 45

            # Thin liquidity
            if liquidity < 3000:
                risk += 35

            elif liquidity < 10000:
                risk += 20

            elif liquidity < 20000:
                risk += 10

            elif liquidity >= 50000:
                risk -= 10

            # Liquidity relative to market cap
            if liq_mcap_ratio < .03:
                risk += 20

            elif liq_mcap_ratio < .08:
                risk += 10

            elif liq_mcap_ratio >= .20:
                risk -= 10

            # Heavy selling
            if trades_5m >= 10:

                if buy_ratio_5m < .40:
                    risk += 20

                elif buy_ratio_5m >= .60:
                    risk -= 5

            # Extreme short-term pump
            if change_5m > 100:
                risk += 15

            # Extremely high volume compared with liquidity
            if liquidity > 0:

                vol_liq = volume_1h / liquidity

                if vol_liq > 15:
                    risk += 10

            risk = int(
                max(0, min(100, risk))
            )

            # --------------------------
            # MOONSHOT SIGNAL
            # --------------------------

            moonshot = (
                momentum * .70
                + (100 - risk) * .30
            ) / 10

            # Hard penalties
            if liquidity < 5000:
                moonshot -= 1.5

            if risk >= 75:
                moonshot -= 1.5

            moonshot = round(
                max(1, min(10, moonshot)),
                1
            )

            # --------------------------
            # STATUS
            # --------------------------

            if risk >= 80:

                status = "🚨 DANGER"

            elif (
                change_5m < -15
                and sells_5m > buys_5m
            ):

                status = "🔴 EXIT WARNING"

            elif (
                momentum >= 80
                and risk <= 50
            ):

                status = "🔥 ACCELERATING"

            elif momentum >= 65:

                status = "📈 STRONG"

            elif momentum >= 45:

                status = "👀 WATCH"

            else:

                status = "⚪ WEAK"

            rows.append({

                "Token":
                    pair.get(
                        "baseToken", {}
                    ).get("symbol", "???"),

                "Age":
                    age_display(age_min),

                "Moonshot":
                    moonshot,

                "Momentum":
                    momentum,

                "Risk":
                    risk,

                "Market Cap":
                    round(market_cap),

                "Liquidity":
                    round(liquidity),

                "5m Volume":
                    round(volume_5m),

                "1h Volume":
                    round(volume_1h),

                "5m Buys":
                    int(buys_5m),

                "5m Sells":
                    int(sells_5m),

                "5m Change %":
                    round(change_5m, 2),

                "1h Change %":
                    round(change_1h, 2),

                "Status":
                    status,

                "Address":
                    address
            })

        except:
            continue

    return pd.DataFrame(rows)


try:

    tokens = get_live_tokens()

    if tokens.empty:

        st.warning(
            "No live Solana tokens returned."
        )

    else:

        # --------------------------
        # SIDEBAR FILTERS
        # --------------------------

        st.sidebar.header(
            "🎯 Scanner Filters"
        )

        max_risk = st.sidebar.slider(
            "Maximum Risk",
            0,
            100,
            65
        )

        min_liquidity = st.sidebar.number_input(
            "Minimum Liquidity ($)",
            value=5000,
            step=1000
        )

        min_moonshot = st.sidebar.slider(
            "Minimum Moonshot Signal",
            1.0,
            10.0,
            5.0,
            .1
        )

        filtered = tokens[
            (tokens["Risk"] <= max_risk)
            &
            (tokens["Liquidity"] >= min_liquidity)
            &
            (tokens["Moonshot"] >= min_moonshot)
        ]

        filtered = filtered.sort_values(
            [
                "Moonshot",
                "Momentum"
            ],
            ascending=False
        )

        # --------------------------
        # TOP METRICS
        # --------------------------

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

        # --------------------------
        # HIGH SIGNAL ALERTS
        # --------------------------

        alerts = filtered[
            (filtered["Moonshot"] >= 8)
            &
            (filtered["Risk"] <= 50)
        ]

        if len(alerts):

            st.subheader(
                "🚨 High-Signal Watchlist"
            )

            for _, token in alerts.iterrows():

                st.success(
                    f"""
🚀 {token['Token']} — {token['Moonshot']}/10

Momentum: {token['Momentum']}/100  
Risk: {token['Risk']}/100  
Age: {token['Age']}  
Liquidity: ${token['Liquidity']:,}  
5m Buys/Sells: {token['5m Buys']} / {token['5m Sells']}  
Status: {token['Status']}
"""
                )

except Exception as error:

    st.error(
        "Scanner connection failed."
    )

    st.code(str(error))


st.divider()

st.subheader("⚠️ Important")

st.write("""
The Moonshot number is a **relative signal-strength score**, not the
probability that a token will increase 50,000% or 100,000%.

The current Risk score checks market/trading behavior. It still cannot
detect every rug, bundled wallet, malicious creator, fake holder network,
or manipulated token.

The next major improvement is **historical outcome tracking** so we can
measure whether high scores actually outperform low scores instead of
assuming the formula works.
""")
