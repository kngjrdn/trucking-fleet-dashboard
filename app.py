import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime
import io

# ========================
# PAGE CONFIG & STYLING
# ========================
st.set_page_config(page_title="Trucking Fleet Dashboard", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    [data-testid="stSidebar"][aria-expanded="true"] {
        background-color: #0d1117;
        border-right: 1px solid #30363d;
    }
    .kpi-card {
        background: linear-gradient(145deg, #1c2128, #161b22);
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        margin-bottom: 15px;
    }
    .kpi-value { font-size: 2rem; font-weight: 700; margin: 8px 0 4px 0; }
    .kpi-label { font-size: 0.95rem; color: #8b949e; }
    .kpi-delta { font-size: 0.9rem; }
    .alert-box {
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
        border-left: 4px solid;
    }
    .alert-danger { background: #2d0d0d; border-color: #ff5555; color: #f08888; }
    .alert-warning { background: #332400; border-color: #e3b341; color: #f0c970; }
    .alert-success { background: #0b290b; border-color: #2ea043; color: #7ee787; }
    div[data-testid="stExpander"] > div > details > summary { font-size: 1rem; font-weight: 600; }
    .stDataFrame { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)

# ========================
# DATA PROCESSING
# ========================
@st.cache_data
def process_data(uploaded_file):
    if uploaded_file is None:
        return None
    
    try:
        df = pd.read_excel(uploaded_file, engine='openpyxl')
        df.columns = df.columns.str.strip()
        
        # Numeric conversion with error handling
        num_cols = [
            'Total Distance', 'Net Revenue', 'Revenue', 'Contribution',
            'Fuel Liters Actual', 'Fuel Cost', 'Lubricant', 'Repairs Cost',
            'Tyres Cost', 'Trip Allowance', 'Route Expense',
            'Loading Days', 'Transit Days', 'Offloading Days', 'Total Cycle Time', 'Idle Days'
        ]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        # Date parsing
        date_cols = ['Date of Dispatch', 'Date of Trip Commencement', 'Date of Arrival', 'Date of Termination']
        for col in date_cols:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                
        # Derived Metrics
        df['Revenue_per_KM'] = np.where(df['Total Distance'] > 0, df['Net Revenue'] / df['Total Distance'], 0)
        df['Contribution_per_KM'] = np.where(df['Total Distance'] > 0, df['Contribution'] / df['Total Distance'], 0)
        df['Fuel_Eff_KM_L'] = np.where(df['Fuel Liters Actual'] > 0, df['Total Distance'] / df['Fuel Liters Actual'], 0)
        df['Maint_Cost_per_KM'] = np.where(df['Total Distance'] > 0, 
                                           (df['Repairs Cost'] + df['Tyres Cost'] + df['Lubricant']) / df['Total Distance'], 0)
        df['Idle_Pct'] = np.where(df['Total Cycle Time'] > 0, df['Idle Days'] / df['Total Cycle Time'], 0)
        df['On_Time_Flag'] = df['Transit Days'] <= st.session_state.get('target_transit_days', 3)
        
        return df
    except Exception as e:
        st.error(f"Error processing file: {e}")
        return None

# ========================
# ALERTS LOGIC
# ========================
def generate_alerts(df, thresholds):
    if df is None or df.empty:
        return ""
    
    alerts = []
    # Thresholds are in GHS/KM, KM/L, %
    if thresholds['revenue_km_min'] > 0 and (df['Revenue_per_KM'] < thresholds['revenue_km_min']).sum() > 0:
        alerts.append(f"⚠️ { (df['Revenue_per_KM'] < thresholds['revenue_km_min']).sum() } trips below GHS {thresholds['revenue_km_min']:.2f}/KM revenue")
        
    if (df['Fuel_Eff_KM_L'] < thresholds['fuel_eff_min']).sum() > 0:
        alerts.append(f"⛽ { (df['Fuel_Eff_KM_L'] < thresholds['fuel_eff_min']).sum() } trips below {thresholds['fuel_eff_min']:.2f} KM/L")
        
    if (df['Idle_Pct'] > thresholds['idle_pct_max']).sum() > 0:
        alerts.append(f"🕒 { (df['Idle_Pct'] > thresholds['idle_pct_max']).sum() } trips with idle time > {thresholds['idle_pct_max']:.0%}")
        
    maint_count = (df['Maint_Cost_per_KM'] > thresholds['maint_km_max']).sum()
    if maint_count > 0:
        alerts.append(f"🔧 {maint_count} trips with maintenance > GHS {thresholds['maint_km_max']:.2f}/KM")
        
    if (df['On_Time_Flag'] == False).sum() > 0:
        on_time_pct = df['On_Time_Flag'].mean()
        if on_time_pct < thresholds['on_time_min']:
            alerts.append(f"⏱️ On-time delivery at {on_time_pct:.1%} (Target: {thresholds['on_time_min']:.0%})")

    if not alerts:
        return '<div class="alert-box alert-success">✅ All metrics within optimal thresholds</div>'
    else:
        html = '<div class="alert-box alert-danger"><strong>⚠️ Threshold Breaches Detected:</strong><ul>'
        for a in alerts:
            html += f'<li>{a}</li>'
        html += '</ul></div>'
        return html

# ========================
# MAIN DASHBOARD
# ========================
st.title("🚛 Fleet Operations & Financial Dashboard")

with st.sidebar:
    st.header("📂 Data Upload")
    uploaded_file = st.file_uploader("Upload Excel File (.xlsx)", type=["xlsx"], help="Replaces data instantly. Keeps filters intact.")
    
    st.divider()
    st.header("🎛️ Filters")
    
    # Threshold Config
    st.subheader("🎯 Alert Thresholds")
    th_rev_km = st.number_input("Min Revenue/KM (GHS)", value=0.85, min_value=0.0, step=0.05)
    th_fuel = st.number_input("Min Fuel Eff. (KM/L)", value=2.47, min_value=0.1, step=0.1, help="≈5.8 MPG")
    th_idle = st.slider("Max Idle Time (%)", 0.0, 0.5, 0.15, 0.01)
    th_maint = st.number_input("Max Maint Cost/KM (GHS)", value=0.075, min_value=0.0, step=0.005, help="≈GHS 0.12/mile")
    th_on_time = st.slider("Min On-Time %", 0.5, 1.0, 0.92, 0.01)
    st.session_state.target_transit_days = st.number_input("Target Transit Days (for On-Time)", 1, 10, 3)
    
    thresholds = {
        'revenue_km_min': th_rev_km,
        'fuel_eff_min': th_fuel,
        'idle_pct_max': th_idle,
        'maint_km_max': th_maint,
        'on_time_min': th_on_time
    }

# Process Data
df = process_data(uploaded_file)

if df is None or df.empty:
    st.info("📥 Upload your fleet Excel file in the sidebar to load the dashboard.")
    st.stop()

# Filter State Management
st.session_state.setdefault('filters', {})

with st.sidebar:
    st.subheader("🔍 Drill-Down Filters")
    month_vals = sorted(df['Month'].dropna().unique().tolist()) if 'Month' in df.columns else []
    year_vals = sorted(df['Year'].dropna().unique().tolist()) if 'Year' in df.columns else []
    manager_vals = sorted(df['Manager'].dropna().unique().tolist()) if 'Manager' in df.columns else []
    truck_vals = sorted(df['Truck ID'].dropna().unique().tolist()) if 'Truck ID' in df.columns else []
    cust_vals = sorted(df['Customer'].dropna().unique().tolist()) if 'Customer' in df.columns else []
    route_vals = sorted(df['Route for Rate'].dropna().unique().tolist()) if 'Route for Rate' in df.columns else []
    
    sel_month = st.multiselect("Month", options=month_vals, default=st.session_state.filters.get('month', []))
    sel_year = st.multiselect("Year", options=year_vals, default=st.session_state.filters.get('year', []))
    sel_manager = st.multiselect("Manager", options=manager_vals, default=st.session_state.filters.get('manager', []))
    sel_truck = st.multiselect("Truck ID", options=truck_vals, default=st.session_state.filters.get('truck', []))
    sel_cust = st.multiselect("Customer", options=cust_vals, default=st.session_state.filters.get('customer', []))
    sel_route = st.multiselect("Route", options=route_vals, default=st.session_state.filters.get('route', []))
    
    if st.button("🔄 Reset Filters"):
        st.session_state.filters = {}
        st.rerun()

    st.session_state.filters.update({
        'month': sel_month, 'year': sel_year, 'manager': sel_manager,
        'truck': sel_truck, 'customer': sel_cust, 'route': sel_route
    })

# Apply Filters
mask = pd.Series(True, index=df.index)
if sel_month: mask &= df['Month'].isin(sel_month)
if sel_year: mask &= df['Year'].isin(sel_year)
if sel_manager: mask &= df['Manager'].isin(sel_manager)
if sel_truck: mask &= df['Truck ID'].isin(sel_truck)
if sel_cust: mask &= df['Customer'].isin(sel_cust)
if sel_route: mask &= df['Route for Rate'].isin(sel_route)
filtered_df = df[mask].copy()

# ========================
# TOP: KPI CARDS
# ========================
total_rev = filtered_df['Net Revenue'].sum()
total_cont = filtered_df['Contribution'].sum()
avg_rev_km = filtered_df['Revenue_per_KM'].mean() if not filtered_df.empty else 0
avg_cont_km = filtered_df['Contribution_per_KM'].mean() if not filtered_df.empty else 0
avg_fuel_eff = filtered_df['Fuel_Eff_KM_L'].mean() if not filtered_df.empty else 0
avg_idle = filtered_df['Idle_Pct'].mean() if not filtered_df.empty else 0
on_time_pct = filtered_df['On_Time_Flag'].mean() if not filtered_df.empty else 0
avg_maint_km = filtered_df['Maint_Cost_per_KM'].mean() if not filtered_df.empty else 0

def kpi_card(title, value, subtext="", color="#58a6ff"):
    st.markdown(f"""
    <div class="kpi-card">
        <div class="kpi-label">{title}</div>
        <div class="kpi-value" style="color:{color}">{value}</div>
        <div class="kpi-delta">{subtext}</div>
    </div>
    """, unsafe_allow_html=True)

cols = st.columns(4)
with cols[0]: kpi_card("Total Net Revenue", f"GHS {total_rev:,.0f}", f"{filtered_df.shape[0]} trips")
with cols[1]: kpi_card("Total Contribution", f"GHS {total_cont:,.0f}", f"{(total_cont/total_rev*100 if total_rev else 0):.1f}% margin")
with cols[2]: kpi_card("Avg Revenue/KM", f"GHS {avg_rev_km:.2f}", "Target: ≥ GHS 0.85", color="#7ee787" if avg_rev_km >= th_rev_km else "#ff7b72")
with cols[3]: kpi_card("Avg Contribution/KM", f"GHS {avg_cont_km:.2f}", "Profitability metric", color="#7ee787" if avg_cont_km > 0 else "#ff7b72")

cols2 = st.columns(4)
with cols2[0]: kpi_card("Fuel Efficiency", f"{avg_fuel_eff:.2f} KM/L", f"Target: ≥ {th_fuel:.2f}", color="#7ee787" if avg_fuel_eff >= th_fuel else "#ff7b72")
with cols2[1]: kpi_card("Idle Time", f"{avg_idle:.1%}", f"Max: {th_idle:.0%}", color="#ff7b72" if avg_idle > th_idle else "#7ee787")
with cols2[2]: kpi_card("On-Time Delivery", f"{on_time_pct:.1%}", f"Min: {th_on_time:.0%}", color="#7ee787" if on_time_pct >= th_on_time else "#ff7b72")
with cols2[3]: kpi_card("Maint. Cost/KM", f"GHS {avg_maint_km:.3f}", f"Max: GHS {th_maint:.3f}", color="#7ee787" if avg_maint_km <= th_maint else "#ff7b72")

# ========================
# ALERTS PANEL
# ========================
st.markdown(generate_alerts(filtered_df, thresholds), unsafe_allow_html=True)

# ========================
# MIDDLE: CHARTS
# ========================
if 'Date of Trip Commencement' in filtered_df.columns:
    filtered_df = filtered_df.sort_values('Date of Trip Commencement')
    trend_data = filtered_df.groupby(filtered_df['Date of Trip Commencement'].dt.date).agg(
        Revenue=('Net Revenue', 'sum'),
        Contribution=('Contribution', 'sum')
    ).reset_index()
    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(x=trend_data.index, y=trend_data['Revenue'], mode='lines', name='Revenue', line=dict(color='#58a6ff', width=2)))
    fig_trend.add_trace(go.Scatter(x=trend_data.index, y=trend_data['Contribution'], mode='lines', name='Contribution', line=dict(color='#7ee787', width=2, dash='dash')))
    fig_trend.update_layout(title="Daily Revenue vs Contribution Trend", template="plotly_dark", margin=dict(t=40), xaxis_title="Date", yaxis_title="GHS")
else:
    fig_trend = px.bar(filtered_df, x='Month', y=['Revenue', 'Contribution'], barmode='group', title="Monthly Revenue vs Contribution", template="plotly_dark")

fig_fuel = px.scatter(filtered_df, x='Fuel_Eff_KM_L', y='Maint_Cost_per_KM', size='Total Distance', 
                      color='Manager', hover_data=['Truck ID', 'Customer', 'Route for Rate'],
                      title="Fuel Efficiency vs Maintenance Cost (Size = Distance)", template="plotly_dark")
fig_fuel.update_layout(xaxis_title="Fuel Efficiency (KM/L)", yaxis_title="Maint. Cost (GHS/KM)")

fig_truck = px.bar(filtered_df.groupby('Truck ID')['Contribution'].sum().nlargest(15).reset_index(),
                   x='Truck ID', y='Contribution', color='Contribution', color_continuous_scale='Viridis',
                   title="Top 15 Trucks by Contribution (GHS)", template="plotly_dark")
fig_truck.update_layout(xaxis_title="Truck ID", yaxis_title="Contribution (GHS)")

fig_route = px.box(filtered_df, x='Route for Rate', y='Revenue_per_KM', points="outliers", 
                   title="Revenue/KM Distribution by Route", template="plotly_dark")
fig_route.update_layout(xaxis_title="Route", yaxis_title="GHS/KM")

c1, c2 = st.columns(2)
c1.plotly_chart(fig_trend, use_container_width=True)
c2.plotly_chart(fig_fuel, use_container_width=True)

c3, c4 = st.columns(2)
c3.plotly_chart(fig_truck, use_container_width=True)
c4.plotly_chart(fig_route, use_container_width=True)

# ========================
# BOTTOM: DRILL-DOWN TABLE
# ========================
st.subheader("📊 Detailed Trip Log")
table_cols = [c for c in ['Date of Trip Commencement', 'Truck ID', 'Manager', 'Customer', 'Route for Rate', 
                          'Total Distance', 'Net Revenue', 'Contribution', 'Revenue_per_KM', 'Contribution_per_KM',
                          'Fuel_Eff_KM_L', 'Idle_Pct', 'Maint_Cost_per_KM', 'On_Time_Flag'] if c in filtered_df.columns]

st.dataframe(
    filtered_df[table_cols].style.format({
        'Net Revenue': "GHS {:,.0f}", 'Contribution': "GHS {:,.0f}",
        'Revenue_per_KM': "GHS {:,.2f}", 'Contribution_per_KM': "GHS {:,.2f}",
        'Maint_Cost_per_KM': "GHS {:,.3f}", 'Idle_Pct': "{:.1%}", 'Fuel_Eff_KM_L': "{:.2f}"
    }).background_gradient(subset=['Revenue_per_KM', 'Contribution_per_KM'], cmap='YlOrRd'),
    use_container_width=True,
    hide_index=True,
    column_config={"On_Time_Flag": st.column_config.CheckboxColumn("On-Time", help="Based on target transit days")}
)

# Footer
st.caption("🔹 Data refreshes instantly on upload | Thresholds adjustable in sidebar | Built for Fleet Management")
