import streamlit as st
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from auth import setup_page
import pandas as pd
import plotly.express as px

from database import get_journey_intent_results_by_tenant, get_contact_activity_by_tenant, get_all_contacts_by_tenant

# Setup authentication and logout button (with title)
setup_page("Journey Analytics")
tenant_id = st.session_state.get("tenant_id")

st.markdown("""
<style>
/* Stage cards */
[data-testid="stMetric"] {
    background: #1e1e2e;
    border: 1px solid #2e2e4e;
    border-radius: 12px;
    padding: 20px 24px;
    transition: border-color 0.2s ease;
}
[data-testid="stMetric"]:hover {
    border-color: #6366f1;
}
[data-testid="stMetricLabel"] {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.03em;
    color: #a0a0c0 !important;
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
}
[data-testid="stMetricValue"] {
    font-size: 2.4rem !important;
    font-weight: 700 !important;
    color: #ffffff !important;
}
[data-testid="stMetricDelta"] {
    font-size: 0.8rem !important;
    color: #6366f1 !important;
}
/* Remove default delta arrow colour overrides */
[data-testid="stMetricDeltaIcon"] {
    display: none;
}
/* Caption below each card */
[data-testid="stMetric"] + div > small {
    color: #6b6b8a !important;
    font-size: 0.75rem !important;
}
/* Column gap */
[data-testid="stHorizontalBlock"] {
    gap: 10px;
}
/* Widen the page content area */
.block-container {
    max-width: 1200px !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}
</style>
""", unsafe_allow_html=True)

journey_stages_dict = {
    'order_support': ('💰', 'Order Support', 'Confirmed buyers'),
    'purchase_intent': ('🔥', 'Ready to Buy', 'Ready to buy'),
    'product_evaluation': ('🔍', 'Product Evaluation', 'Comparing options'),
    'wholesale_inquiry': ('🏢', 'Wholesale', 'B2B opportunities'),
    'browsing': ('👀', 'Browsing', 'Exploring catalog'),
    'location_inquiry': ('📍', 'Location', 'Seeking store info'),
    'spam_unrelated': ('🚫', 'Spam/Unrelated', 'Not interested'),
}

# ── Refresh button ───────────────────────────────────────────────────────────
if st.button("🔄 Refresh", help="Clear cached data and reload from the database"):
    st.cache_data.clear()
    st.rerun()

# ── Load data (shared between tabs) ──────────────────────────────────────────
data = get_journey_intent_results_by_tenant(tenant_id)
all_contacts = get_all_contacts_by_tenant(tenant_id)
activity = get_contact_activity_by_tenant(tenant_id)

if isinstance(data, str):
    st.error(data)
    st.stop()

if not data:
    st.info("No classification results yet.")
    st.stop()

# Pre-process: latest classification per contact
latest_per_contact = {}
for row in data:
    cid = row["contact_id"]
    if cid not in latest_per_contact or row["classified_at"] > latest_per_contact[cid]["classified_at"]:
        latest_per_contact[cid] = row

# Contact lookup by ID (for name + phone)
contacts_by_id = {c["contact_id"]: c for c in all_contacts}

# Activity DataFrame
activity_df = pd.DataFrame(activity) if not isinstance(activity, str) and activity else pd.DataFrame()

# Phone fallback: activity_df carries Wati-facing lookup phones for contacts that
# may be missing from contacts_by_id
activity_phone_by_id: dict = {}
activity_stage_by_id: dict = {}
if not activity_df.empty and "contact_id" in activity_df.columns:
    for _, r in activity_df.iterrows():
        cid = r["contact_id"]
        activity_phone_by_id[cid] = r.get("wati_lookup_phone", "") or r.get("phone_normalized", "")
        activity_stage_by_id[cid] = r.get("current_journey_stage", "")


def build_campaign_csv(contact_ids: set, segment_name: str) -> str:
    rows = []
    for cid in contact_ids:
        contact = contacts_by_id.get(cid, {})
        phone = (
            contact.get("wati_lookup_phone")
            or activity_phone_by_id.get(cid, "")
            or contact.get("phone_normalized")
        )
        stage = (
            latest_per_contact.get(cid, {}).get("journey_stage")
            or activity_stage_by_id.get(cid, "unclassified")
        )
        rows.append({
            "name": contact.get("name", ""),
            "phone_number": phone,
            "allowBroadcast": True,
            "allowSMS": True,
            "journey_stage": stage or "unclassified",
            "segment": segment_name,
        })
    return pd.DataFrame(rows).to_csv(index=False)


tab1, tab2, tab3 = st.tabs(["Journey Analytics", "Campaign Imports", "Messages Analytics"])
with tab1:
    # ── Recent Activity ───────────────────────────────────────────────────────
    if not activity_df.empty:
        now = datetime.now(timezone.utc)
        cutoff_7d  = (now - timedelta(days=7)).isoformat()
        cutoff_30d = (now - timedelta(days=30)).isoformat()
        cutoff_90d = (now - timedelta(days=90)).isoformat()

        active_7d  = sum(1 for _, r in activity_df.iterrows() if r["last_inbound_at"] and r["last_inbound_at"] > cutoff_7d)
        active_30d = sum(1 for _, r in activity_df.iterrows() if r["last_inbound_at"] and r["last_inbound_at"] > cutoff_30d)
        active_90d = sum(1 for _, r in activity_df.iterrows() if r["last_inbound_at"] and r["last_inbound_at"] > cutoff_90d)
        st.subheader("Recent Activity")
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            st.metric(label="📊 Total Contacts", value=len(all_contacts), delta="contacts messaged")
        with a2:
            st.metric(label="📅 Last 7 Days", value=active_7d, delta="contacts messaged")
        with a3:
            st.metric(label="📅 Last 30 Days", value=active_30d, delta="contacts messaged")
        with a4:
            st.metric(label="📅 Last 90 Days", value=active_90d, delta="contacts messaged")
        st.info("Some of the contacts registered here might not have been classified yet.")
    st.divider()

    # Count per stage
    stage_counts = defaultdict(int)
    for row in latest_per_contact.values():
        stage_counts[row["journey_stage"]] += 1

    total_contacts = sum(stage_counts.values())
    st.subheader("Journey Stage Distribution")
    cols = st.columns(4)
    for i, (stage_key, (emoji, label, description)) in enumerate(journey_stages_dict.items()):
        count = stage_counts.get(stage_key, 0)
        pct = (count / total_contacts * 100) if total_contacts else 0
        with cols[i % 4]:
            st.metric(
                label=f"{emoji} {label}",
                value=count,
                delta=f"{pct:.1f}% of total are {description}",
            )

    st.divider()
    st.subheader("Journey Stage Pie Chart")
    stage_counts_df = pd.DataFrame(stage_counts.items(), columns=['journey_stage', 'count'])
    fig = px.pie(stage_counts_df, values='count', names='journey_stage')
    st.plotly_chart(fig)

with tab2:
    st.header("Campaign Imports")

    with st.expander("How to use this tab"):
        st.write("**Engaged 30 days** — Contacts that messaged in the past 30 days (any stage)")
        st.write("**Engaged 90 days** — Contacts that messaged in the past 90 days (any stage)")
        st.write("**Ready to convert** — Contacts classified as purchase intent")
        st.write("**Wholesale** — Contacts classified as wholesale inquiry")
        st.write("Download a CSV and upload it to Wati to create a broadcast campaign.")

    now = datetime.now(timezone.utc)
    cutoff_30d = (now - timedelta(days=30)).isoformat()
    cutoff_90d = (now - timedelta(days=90)).isoformat()

    if not activity_df.empty and "last_inbound_at" in activity_df.columns:
        engaged_30_ids = set(
            activity_df[activity_df["last_inbound_at"].fillna("") > cutoff_30d]["contact_id"].tolist()
        )
        engaged_90_ids = set(
            activity_df[activity_df["last_inbound_at"].fillna("") > cutoff_90d]["contact_id"].tolist()
        )
    else:
        engaged_30_ids = set()
        engaged_90_ids = set()

    purchase_intent_ids = {
        cid for cid, row in latest_per_contact.items()
        if row["journey_stage"] == "purchase_intent"
    }
    wholesale_ids = {
        cid for cid, row in latest_per_contact.items()
        if row["journey_stage"] == "wholesale_inquiry"
    }

    col1, col2 = st.columns(2)

    with col1:
        with st.container():
            st.metric("Engaged 30 days", value=len(engaged_30_ids))
            st.caption("Contacts that messaged in the past 30 days (any stage)")
            if engaged_30_ids:
                st.download_button(
                    "⬇ Export CSV",
                    data=build_campaign_csv(engaged_30_ids, "Engaged 30 days"),
                    file_name="campaign_engaged_30d.csv",
                    mime="text/csv",
                    key="dl_engaged_30",
                    use_container_width=True,
                )

        with st.container():
            st.metric("Ready to convert", value=len(purchase_intent_ids))
            st.caption("Contacts classified as purchase intent")
            if purchase_intent_ids:
                st.download_button(
                    "⬇ Export CSV",
                    data=build_campaign_csv(purchase_intent_ids, "Ready to convert"),
                    file_name="campaign_ready_to_convert.csv",
                    mime="text/csv",
                    key="dl_purchase_intent",
                    use_container_width=True,
                )

    with col2:
        with st.container():
            st.metric("Engaged 90 days", value=len(engaged_90_ids))
            st.caption("Contacts that messaged in the past 90 days (any stage)")
            if engaged_90_ids:
                st.download_button(
                    "⬇ Export CSV",
                    data=build_campaign_csv(engaged_90_ids, "Engaged 90 days"),
                    file_name="campaign_engaged_90d.csv",
                    mime="text/csv",
                    key="dl_engaged_90",
                    use_container_width=True,
                )

        with st.container():
            st.metric("Wholesale", value=len(wholesale_ids))
            st.caption("Contacts classified as wholesale inquiry")
            if wholesale_ids:
                st.download_button(
                    "⬇ Export CSV",
                    data=build_campaign_csv(wholesale_ids, "Wholesale"),
                    file_name="campaign_wholesale.csv",
                    mime="text/csv",
                    key="dl_wholesale",
                    use_container_width=True,
                )

with tab3:
    st.header("Messages Analytics")

    import re

    # Source distribution
    st.subheader("Contact Sources")
    source_counts = {}
    for contact in all_contacts:
        source = contact.get("source") or ""
        if not source or not re.match(r"[A-Za-z]+://", source):
            continue
        # Clean up raw URLs to readable labels
        if "facebook.com" in source or "fb.com" in source:
            label = "Facebook Ad"
        elif "instagram.com" in source:
            label = "Instagram"
        elif "wa.me" in source or "whatsapp" in source.lower():
            label = "WhatsApp Direct"
        elif "google" in source.lower():
            label = "Google"
        else:
            try:
                label = source.split("://")[1].split("/")[0].replace("www.", "")
            except (IndexError, AttributeError):
                label = source[:40]
        source_counts[label] = source_counts.get(label, 0) + 1

    if source_counts:
        sorted_sources = sorted(source_counts.items(), key=lambda x: -x[1])
        source_df = pd.DataFrame(sorted_sources, columns=["Source", "Contacts"])

        col_chart, col_table = st.columns([2, 1])
        with col_chart:
            st.bar_chart(source_df.set_index("Source")["Contacts"])
        with col_table:
            st.dataframe(source_df.head(10), use_container_width=True, hide_index=True)
    else:
        st.info("No source data available yet.")

    # Message volume stats
    st.divider()
    st.subheader("Message Volume")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Contacts", f"{len(all_contacts):,}")
    with col2:
        st.metric("Classified", f"{len(latest_per_contact):,}")
    with col3:
        coverage = round(len(latest_per_contact) / len(all_contacts) * 100) if all_contacts else 0
        st.metric("Coverage", f"{coverage}%")
