import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="Moonshot Tracker",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Solana Moonshot Tracker")
st.caption("Early token detection • scam filtering • momentum monitoring")

tokens = pd.DataFrame([
    {
        "Token": "Example Alpha",
        "Age": "3m",
        "Market Cap": "$42K",
        "Liquidity": "$21K",
        "Moonshot": "9.2/10 🚀",
        "Momentum": "91/100",
        "Risk": "18/100 🟢",
        "Status": "🔥 ACCELERATING"
    },
    {
        "Token": "Example Beta",
        "Age": "8m",
        "Market Cap": "$97K",
        "Liquidity": "$33K",
        "Moonshot": "8.4/10",
        "Momentum": "82/100",
        "Risk": "31/100 🟡",
        "Status": "📈 STRONG"
    },
    {
        "Token": "Example Gamma",
        "Age": "5m",
        "Market Cap": "$28K",
        "Liquidity": "$12K",
        "Moonshot": "7.7/10",
        "Momentum": "76/100",
        "Risk": "64/100 🔴",
        "Status": "⚠️ HIGH RISK"
    }
])

col1, col2, col3, col4 = st.columns(4)

col1.metric("🔥 Tokens Tracked", len(tokens))
col2.metric("🚀 Top Moonshot", "9.2/10")
col3.metric("🛡️ Lowest Risk", "18/100")
col4.metric("📈 Highest Momentum", "91/100")

st.subheader("🔥 Live Opportunity Feed")

st.dataframe(
    tokens,
    use_container_width=True,
    hide_index=True
)

st.subheader("🚀 Moonshot Analysis")

st.write("""
The Moonshot Score will analyze:

• Buyer acceleration  
• Holder growth  
• Trading volume acceleration  
• Social/X mention acceleration  
• Smart-wallet activity  
• Liquidity strength  
• Creator/deployer history  
• Wallet concentration  
• Bot and manipulation activity
""")

st.subheader("📉 Exit Signal Monitor")

st.success("🟢 MOMENTUM CONTINUING")

st.write("""
The live version will continuously monitor:

• Buy vs sell pressure  
• Price from recent high  
• New buyer growth  
• Large-wallet selling  
• Liquidity changes  
• Volume deterioration  
• Social momentum
""")

st.warning(
    "DEMO MODE — These are example tokens. "
    "Live Solana/Pump.fun data will be connected next."
)
