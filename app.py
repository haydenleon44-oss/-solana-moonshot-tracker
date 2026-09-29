import streamlit as st
import pandas as pd
import requests

st.set_page_config(
    page_title="Solana Moonshot Tracker",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Moonshot Tracker")
st.caption("LIVE Solana market scanner • momentum • risk filtering")

# DexScreener public API
URL = "https://api.dexscreener.com/token-profiles/latest/v1"

@st.cache_data(ttl=20)
def get_live_tokens():
    response = requests.get(URL, timeout=10)
    response.raise_for_status()

    data = response.json()

    # Only Solana tokens
    solana = [
        token for token in data
        if token.get("chainId") == "solana"
    ]

    rows = []

    # Limit API requests
    for token in solana[:20]:

        address = token.get("tokenAddress")

        try:
            pair_response = requests.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{address}",
                timeout=10
            )

            pair_data = pair_response.json()
            pairs = pair_data.get("pairs") or []

            if not pairs:
                continue

            # Prefer highest-liquidity market
            pair = max(
                pairs,
                key=lambda x: (x.get("liquidity") or {}).get("usd", 0)
            )

            liquidity = (pair.get("liquidity") or {}).get("usd", 0) or 0
            volume = (pair.get("volume") or {}).get("h24", 0) or 0
            mcap = pair.get("marketCap") or pair.get("fdv") or 0

            changes = pair.get("priceChange") or {}
            h1 = changes.get("h1", 0) or 0
            h6 = changes.get("h6", 0) or 0

            txns = pair.get("txns") or {}
            h1_txns = txns.get("h1") or {}

            buys = h1_txns.get("buys", 0) or 0
            sells = h1_txns.get("sells", 0) or 0

            total = buys + sells

            buy_ratio = (
                buys / total
                if total > 0
                else 0
            )

            # -------------------------
            # MOMENTUM SCORE
            # -------------------------

            momentum = 0

            momentum += min(30, buys / 3)
            momentum += min(20, volume / 5000)

            if buy_ratio >= 0.70:
                momentum += 20
            elif buy_ratio >= 0.60:
                momentum += 12

            if h1 > 20:
                momentum += 15

            if h6 > 50:
                momentum += 15

            momentum = min(100, round(momentum))

            # -------------------------
            # BASIC RISK FILTER
            # -------------------------

            risk = 50

            if liquidity >= 50000:
                risk -= 20
            elif liquidity >= 20000:
                risk -= 10
            elif liquidity < 5000:
                risk += 25

            if total >= 100:
                risk -= 10

            if buy_ratio < 0.40:
                risk += 15

            risk = max(0, min(100, risk))

            # -------------------------
            # MOONSHOT SCORE
            # -------------------------

            moonshot = (
                (momentum * 0.65)
                + ((100 - risk) * 0.35)
            ) / 10

            moonshot = round(
                min(10, max(1, moonshot)),
                1
            )

            if risk >= 75:
                status = "🚨 HIGH RISK"

            elif momentum >= 85:
                status = "🔥 ACCELERATING"

            elif momentum >= 70:
                status = "📈 STRONG"

            elif momentum >= 50:
                status = "👀 WATCH"

            else:
                status = "⚪ LOW MOMENTUM"

            rows.append({
                "Token": pair.get("baseToken", {}).get("symbol", "???"),
                "Moonshot": moonshot,
                "Momentum": momentum,
                "Risk": risk,
                "Market Cap": mcap,
                "Liquidity": liquidity,
                "24H Volume": volume,
                "1H Buys": buys,
                "1H Sells": sells,
                "1H Change %": h1,
                "Status": status,
                "Address": address
            })

        except Exception:
            continue

    return pd.DataFrame(rows)


try:

    tokens = get_live_tokens()

    if tokens.empty:

        st.warning(
            "No live Solana tokens were returned. "
            "Refresh the scanner shortly."
        )

    else:

        tokens = tokens.sort_values(
            ["Moonshot", "Momentum"],
            ascending=False
        )

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "🔥 Tokens Found",
            len(tokens)
        )

        col2.metric(
            "🚀 Highest Moonshot",
            f"{tokens['Moonshot'].max()}/10"
        )

        col3.metric(
            "📈 Highest Momentum",
            f"{tokens['Momentum'].max()}/100"
        )

        col4.metric(
            "🛡️ Lowest Risk",
            f"{tokens['Risk'].min()}/100"
        )

        st.subheader("🔥 LIVE Opportunity Feed")

        st.dataframe(
            tokens,
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            "Data refreshes approximately every 20 seconds."
        )

except Exception as error:

    st.error(
        "Live market connection failed."
    )

    st.code(str(error))


st.divider()

st.subheader("🧠 What the scores currently mean")

st.write("""
**Moonshot Score:** Combines current momentum and basic market risk.

**Momentum:** Uses buys, buy/sell balance, volume and price acceleration.

**Risk:** Currently checks liquidity and trading behavior.

This is the first live layer. It does NOT yet include the advanced
creator-wallet, holder concentration, sniper detection, X/social,
smart-wallet, or historical-learning systems.
""")

st.warning(
    "Scores are experimental signals, not predictions or guarantees. "
    "A 10/10 does not mean a token will rise 50,000% or 100,000%."
)
