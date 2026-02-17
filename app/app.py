# --- app.py: Fendt Fleet — Idle Time Analytics ---

import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import folium
from streamlit_folium import st_folium
from pathlib import Path
from datetime import timedelta

st.set_page_config(layout="wide", page_title="Fendt Fleet: Idle Time Analytics", page_icon="🚜")

DIESEL_PRICE_EUR = 1.588
EMISSION_FACTOR = 2.64
DELTA_T_CUTOFF = 300
DEV_FAST_MODE = False


@st.cache_data(show_spinner="Loading data...")
def load_data():
    """Load parquet → rebuild delta_t → compute fuel & KPIs."""
    path = Path(__file__).parent.parent / "data" / "processed" / "telemetry_app.parquet"
    if not path.exists():
        return None, None, None

    cols = ['timestamp', 'tractor', 'latitude', 'longitude',
            'speed', 'activity', 'state', 'liters_consumed']

    if DEV_FAST_MODE:
        import pyarrow.parquet as pq
        batch = next(pq.ParquetFile(path).iter_batches(batch_size=500_000, columns=cols))
        df = batch.to_pandas()
    else:
        df = pd.read_parquet(path, columns=cols)

    df['latitude'] = df['latitude'].astype('float32')
    df['longitude'] = df['longitude'].astype('float32')
    df['speed'] = pd.to_numeric(df['speed'], errors='coerce').fillna(0).astype('float32')
    df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')

    df.rename(columns={'liters_consumed': 'fuel_rate_lh'}, inplace=True)
    df['fuel_rate_lh'] = pd.to_numeric(df['fuel_rate_lh'], errors='coerce').fillna(0).astype('float32')
    df.dropna(subset=['latitude', 'longitude', 'timestamp'], inplace=True)

    # Delta-t & instantaneous fuel
    df.sort_values(['tractor', 'timestamp'], inplace=True)
    dt = df.groupby('tractor')['timestamp'].diff().fillna(0).values
    dt[dt > DELTA_T_CUTOFF] = 0
    dt[dt < 0] = 0
    df['delta_t'] = dt.astype('float32')
    df['liters'] = (df['fuel_rate_lh'].values * dt / 3600.0).astype('float32')

    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', origin='2024-01-01')

    df.reset_index(drop=True, inplace=True)

    # KPIs per tractor
    is_idle = df['state'] == 'Idle'
    per_tractor = df.groupby('tractor').agg(total_dt=('delta_t', 'sum'), total_fuel=('liters', 'sum'))
    idle_agg = df[is_idle].groupby('tractor').agg(idle_dt=('delta_t', 'sum'), idle_fuel=('liters', 'sum'))
    kpi_tractor = per_tractor.join(idle_agg, how='left').fillna(0)
    kpi_tractor['total_hours'] = kpi_tractor['total_dt'] / 3600
    kpi_tractor['idle_hours'] = kpi_tractor['idle_dt'] / 3600
    kpi_tractor['idle_pct'] = np.where(
        kpi_tractor['total_hours'] > 0, kpi_tractor['idle_hours'] / kpi_tractor['total_hours'] * 100, 0)
    kpi_tractor['fuel_waste_pct'] = np.where(
        kpi_tractor['total_fuel'] > 0, kpi_tractor['idle_fuel'] / kpi_tractor['total_fuel'] * 100, 0)

    # Global KPIs
    kpi_global = {
        'total_hours': kpi_tractor['total_hours'].sum(),
        'idle_hours': kpi_tractor['idle_hours'].sum(),
        'total_fuel': kpi_tractor['total_fuel'].sum(),
        'idle_fuel': kpi_tractor['idle_fuel'].sum(),
    }
    kpi_global['idle_pct'] = (
        kpi_global['idle_hours'] / kpi_global['total_hours'] * 100
        if kpi_global['total_hours'] > 0 else 0)
    kpi_global['fuel_waste_pct'] = (
        kpi_global['idle_fuel'] / kpi_global['total_fuel'] * 100
        if kpi_global['total_fuel'] > 0 else 0)

    return df, kpi_tractor, kpi_global


# =============================================================================
# HELPER: Pre-aggregate idle data server-side
# =============================================================================
@st.cache_data(show_spinner="Aggregating spatial data...")
def preaggregate_idle(df_idle, precision=4):
    """
    Round lat/lon to `precision` decimals and sum liters per grid cell.
    Reduces millions of rows to thousands — safe for any viz layer.
    """
    df = df_idle[['latitude', 'longitude', 'liters', 'tractor']].copy()
    df['lat_round'] = df['latitude'].round(precision).astype(float)
    df['lon_round'] = df['longitude'].round(precision).astype(float)
    agg = df.groupby(['lat_round', 'lon_round', 'tractor'], as_index=False)['liters'].sum()
    agg = agg[agg['liters'] > 0.01]
    agg['liters'] = agg['liters'].round(2).astype(float)
    return agg


# =============================================================================
# TAB 1: Waste Analysis
# =============================================================================
def render_tab_waste(df_full, kpi_tractor, kpi_global):
    st.markdown("#### Operational Efficiency Map")

    view_mode = st.radio(
        "Visualization Mode:",
        ["🔥 Waste Heatmap", "📊 3D Hexagons", "🚜 Operational Trail (2D)"],
        horizontal=True,
    )

    captions = {
        "🔥 Waste Heatmap": "Intensity = **fuel wasted while idle**. Bright zones = waste hotspots.",
        "📊 3D Hexagons": "Height & color = **fuel wasted per zone**. Hover for details.",
        "🚜 Operational Trail (2D)": "Points show the **path traveled**. Color = state (Green = Working, Red = Idle).",
    }
    st.caption(captions[view_mode])

    all_tractors = sorted(df_full['tractor'].unique())

    # Default to smallest tractor to avoid memory issues on first load
    default_tractor = ["Fendt 211"] if "Fendt 211" in all_tractors else [all_tractors[0]]
    sel_tractors = st.sidebar.multiselect(
        "🚜 Tractors:", all_tractors, default=default_tractor, key="t1_tractors")

    if not sel_tractors:
        st.warning("Select at least one tractor.")
        return

    # Sampling slider only for 2D trail (heatmap and hexagons use pre-aggregation)
    if view_mode == "🚜 Operational Trail (2D)":
        step = st.sidebar.slider(
            "Sampling (skip every N points)", 1, 200, 100, key="t1_step",
            help="Increase if the map is slow or you get memory errors. 1 = all points.")
    else:
        step = None

    # Heatmap/Hexagon specific controls
    if view_mode == "🔥 Waste Heatmap":
        heat_radius = st.sidebar.slider("Heatmap Radius (px)", 20, 150, 60, key="t1_heat_radius")
        heat_intensity = st.sidebar.slider("Intensity", 0.5, 5.0, 1.5, step=0.5, key="t1_heat_intensity")
    elif view_mode == "📊 3D Hexagons":
        hex_radius = st.sidebar.slider("Hexagon Radius (m)", 5, 100, 25, key="t1_hex_radius")
        hex_elev_scale = st.sidebar.slider("Elevation Scale", 100, 3000, 800, step=100, key="t1_hex_elev")

    st.markdown("---")

    # --- KPIs ---
    kpi_sel = kpi_tractor.loc[kpi_tractor.index.isin(sel_tractors)]
    if len(sel_tractors) == len(all_tractors):
        g = kpi_global
    else:
        ks = kpi_sel
        g = {
            'total_hours': ks['total_hours'].sum(),
            'idle_hours': ks['idle_hours'].sum(),
            'total_fuel': ks['total_fuel'].sum(),
            'idle_fuel': ks['idle_fuel'].sum(),
        }
        g['idle_pct'] = g['idle_hours'] / g['total_hours'] * 100 if g['total_hours'] > 0 else 0
        g['fuel_waste_pct'] = g['idle_fuel'] / g['total_fuel'] * 100 if g['total_fuel'] > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Engine-On Hours", f"{g['total_hours']:,.1f} h")
    with c2:
        st.metric("Idle Rate", f"{g['idle_pct']:.1f}%")
        st.markdown(
            f"<div style='margin-top:-15px;font-size:14px;color:#808080;'>"
            f"{g['idle_hours']:.1f} h idle</div>", unsafe_allow_html=True)
    c3.metric("Total Diesel", f"{g['total_fuel']:,.1f} L")
    with c4:
        st.metric("Wasted Diesel", f"{g['idle_fuel']:,.1f} L")
        st.markdown(
            f"<div style='margin-top:-15px;font-size:14px;color:#808080;'>"
            f"{g['fuel_waste_pct']:.1f}% of total</div>", unsafe_allow_html=True)

    st.markdown("---")

    # --- Map rendering with memory safety ---
    try:
        mask = df_full['tractor'].isin(sel_tractors)

        # Base satellite tile layer
        layers = [
            pdk.Layer("TileLayer",
                      data="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
                      id="satellite-layer", tileSize=256, min_zoom=0, max_zoom=19, opacity=1.0)
        ]
        tooltip = {}
        pitch = 0

        # ---- VIEW: HEATMAP ----
        if view_mode == "🔥 Waste Heatmap":
            df_idle = df_full.loc[mask & (df_full['state'] == 'Idle')]

            if df_idle.empty:
                st.info("No idle data to display."); return

            df_agg = preaggregate_idle(df_idle)

            mid_lat = df_agg['lat_round'].mean()
            mid_lon = df_agg['lon_round'].mean()

            # Tractor legend
            unique_tractors = sorted(df_agg['tractor'].unique())
            if len(unique_tractors) > 1:
                cols_legend = st.columns(min(len(unique_tractors), 8))
                for i, t in enumerate(unique_tractors):
                    with cols_legend[i % 8]:
                        st.markdown(f"**◼ {t}**", unsafe_allow_html=True)

            layers.append(pdk.Layer(
                "HeatmapLayer",
                df_agg.to_dict(orient='records'),
                get_position=['lon_round', 'lat_round'],
                get_weight='liters',
                radiusPixels=heat_radius,
                intensity=heat_intensity,
                threshold=0.05,
                opacity=0.75,
            ))

            tooltip = {
                "html": "Waste Heatmap<br>Brighter = more fuel wasted",
                "style": {"backgroundColor": "black", "color": "white"},
            }
            pitch = 0

            st.pydeck_chart(pdk.Deck(
                layers=layers,
                initial_view_state=pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=14, pitch=pitch),
                tooltip=tooltip, map_style=None, map_provider="mapbox"))

            st.caption(f"Aggregated from {len(df_idle):,} idle records → {len(df_agg):,} grid cells.")

        # ---- VIEW: 3D HEXAGONS ----
        elif view_mode == "📊 3D Hexagons":
            df_idle = df_full.loc[mask & (df_full['state'] == 'Idle')]

            if df_idle.empty:
                st.info("No idle data to display."); return

            df_agg = preaggregate_idle(df_idle)

            mid_lat = df_agg['lat_round'].mean()
            mid_lon = df_agg['lon_round'].mean()

            # Tractor legend
            unique_tractors = sorted(df_agg['tractor'].unique())
            if len(unique_tractors) > 1:
                cols_legend = st.columns(min(len(unique_tractors), 8))
                for i, t in enumerate(unique_tractors):
                    with cols_legend[i % 8]:
                        st.markdown(f"**◼ {t}**", unsafe_allow_html=True)

            layers.append(pdk.Layer(
                "HexagonLayer",
                df_agg.to_dict(orient='records'),
                get_position=['lon_round', 'lat_round'],
                get_elevation_weight='liters',
                elevation_scale=hex_elev_scale,
                elevation_range=[0, 1000],
                radius=hex_radius,
                extruded=True,
                pickable=True,
                auto_highlight=True,
                color_range=[
                    [255, 255, 178],  # pale yellow
                    [254, 204, 92],   # yellow
                    [253, 141, 60],   # orange
                    [240, 59, 32],    # red-orange
                    [189, 0, 38],     # dark red
                ],
            ))

            tooltip = {
                "html": "<b>Hex Zone</b><br>Elevation = total idle fuel (L)",
                "style": {"backgroundColor": "black", "color": "white"},
            }
            pitch = 55

            st.pydeck_chart(pdk.Deck(
                layers=layers,
                initial_view_state=pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=14, pitch=pitch),
                tooltip=tooltip, map_style=None, map_provider="mapbox"))

            st.caption(f"Aggregated from {len(df_idle):,} idle records → {len(df_agg):,} grid cells → hexagonal binning.")

        # ---- VIEW: 2D TRAIL ----
        else:
            df_map = df_full.loc[mask].iloc[::step].copy()
            df_map['latitude'] = df_map['latitude'].astype(float)
            df_map['longitude'] = df_map['longitude'].astype(float)
            mid_lat = df_map['latitude'].mean()
            mid_lon = df_map['longitude'].mean()

            df_map.loc[df_map['state'] == 'Transport', 'state'] = 'Working'
            state_colors = {'Idle': [214, 39, 40, 200], 'Working': [44, 160, 44, 150], 'Off': [128, 128, 128, 50]}

            c1, c2 = st.columns(2)
            with c1: st.markdown("**<span style='color:green'>● Working</span>**", unsafe_allow_html=True)
            with c2: st.markdown("**<span style='color:red'>● Idle</span>**", unsafe_allow_html=True)

            df_map['color'] = df_map['state'].map(state_colors)
            mask_nan = df_map['color'].isna()
            if mask_nan.any():
                df_map.loc[mask_nan, 'color'] = pd.Series(
                    [[128, 128, 128, 100]] * mask_nan.sum(), index=df_map[mask_nan].index)

            layers.append(pdk.Layer(
                "ScatterplotLayer",
                df_map.to_dict(orient='records'),
                get_position=['longitude', 'latitude'],
                get_color='color',
                get_radius=3, pickable=True, opacity=0.8, stroked=False))

            tooltip = {"html": "<b>{tractor}</b><br>State: <b>{state}</b><br>Speed: {speed} m/s",
                       "style": {"backgroundColor": "steelblue", "color": "white"}}

            st.pydeck_chart(pdk.Deck(
                layers=layers,
                initial_view_state=pdk.ViewState(latitude=mid_lat, longitude=mid_lon, zoom=14, pitch=0),
                tooltip=tooltip, map_style=None, map_provider="mapbox"))

            st.caption(f"Displaying {len(df_map):,} records.")

    except MemoryError:
        st.error(
            "⚠️ **Out of memory.** Try one or more of these:\n"
            "- Select fewer tractors in the sidebar\n"
            "- Increase the sampling slider (skip more points)\n"
            "- Close other applications to free RAM"
        )
    except Exception as e:
        st.error(f"⚠️ **Rendering error:** {e}\n\nTry increasing the sampling slider or selecting fewer tractors.")


# =============================================================================
# TAB 2: Operational Replay
# =============================================================================
def render_tab_replay(df_full):
    st.markdown("#### Idle Audit (Step-by-Step)")
    st.caption("Navigate the day in fixed time blocks. Classify machine behavior for each block.")

    all_tractors = sorted(df_full['tractor'].unique())

    c1, c2 = st.columns(2)
    with c1:
        sel_tractor = st.selectbox("🚜 Tractor:", all_tractors, key="t2_tractor")

    df_t = df_full[df_full['tractor'] == sel_tractor].copy()
    if df_t.empty:
        st.warning("No data."); return

    min_dt, max_dt = df_t['datetime'].min(), df_t['datetime'].max()

    with c2:
        def on_date_change():
            st.session_state['t2_current_start'] = None

        sel_date = st.date_input(
            "📅 Date:", value=min_dt.date(),
            min_value=min_dt.date(), max_value=max_dt.date(),
            key="t2_date", on_change=on_date_change)

    df_day = df_t[df_t['datetime'].dt.date == sel_date]
    if df_day.empty:
        st.info(f"No data on {sel_date}."); return

    st.markdown("---")

    c_nav1, c_nav2, c_nav3 = st.columns([1, 2, 1])

    with c_nav1:
        slot_minutes = st.number_input(
            "⏱️ Block Size (min):", min_value=1, max_value=120, value=15, step=5, key="t2_slot_size")

    day_start_dt = df_day['datetime'].min().floor(f'{slot_minutes}min')
    day_end_dt = df_day['datetime'].max()

    if 't2_current_start' not in st.session_state or st.session_state['t2_current_start'] is None:
        st.session_state['t2_current_start'] = day_start_dt
    if st.session_state['t2_current_start'].date() != sel_date:
        st.session_state['t2_current_start'] = day_start_dt

    def prev_slot():
        new = st.session_state['t2_current_start'] - timedelta(minutes=slot_minutes)
        if new >= day_start_dt:
            st.session_state['t2_current_start'] = new
        else:
            st.toast("Start of day reached!", icon="⏮️")

    def next_slot():
        new = st.session_state['t2_current_start'] + timedelta(minutes=slot_minutes)
        if new <= day_end_dt:
            st.session_state['t2_current_start'] = new
        else:
            st.toast("End of day data reached!", icon="⏭️")

    current_start = st.session_state['t2_current_start']
    current_end = current_start + timedelta(minutes=slot_minutes)

    with c_nav2:
        st.markdown(
            f"<div style='text-align:center;font-weight:bold;padding-top:10px;font-size:18px;'>"
            f"{current_start.strftime('%H:%M')} ➝ {current_end.strftime('%H:%M')}"
            f"</div>", unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        b1.button("◀ Previous", on_click=prev_slot, use_container_width=True)
        b2.button("Next ▶", on_click=next_slot, use_container_width=True)

    with c_nav3:
        st.markdown("**Classify Idle Type:**")
        classification = st.radio(
            "Stop type:",
            ["🔴 Waste", "🟠 Necessary Idle"],
            label_visibility="collapsed", key="t2_class_decision")

    df_win = df_day[(df_day['datetime'] >= current_start) & (df_day['datetime'] < current_end)].copy()

    if df_win.empty:
        st.warning(f"No records between {current_start.strftime('%H:%M')} and {current_end.strftime('%H:%M')}.")
    else:
        MAX_POINTS = 800
        if len(df_win) > MAX_POINTS:
            win_step = len(df_win) // MAX_POINTS
            df_plot = df_win.iloc[::win_step].copy()
            msg_perf = f"Sampled {len(df_plot)} of {len(df_win)} points"
        else:
            df_plot = df_win.copy()
            msg_perf = f"{len(df_win)} points"

        tile_providers = {
            "Google Hybrid": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            "Google Satellite": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        }
        sel_tile = st.sidebar.selectbox("🛰️ Map Tiles (Tab 2):", list(tile_providers.keys()), key="t2_tiles_sel")

        mid_lat = df_plot['latitude'].mean()
        mid_lon = df_plot['longitude'].mean()

        m = folium.Map(location=[mid_lat, mid_lon], zoom_start=16,
                       tiles=tile_providers[sel_tile], attr="Google Maps")

        for _, row in df_plot.iterrows():
            state = row['state']
            if state in ['Working', 'Transport']:
                color, tip = '#2ca02c', "Working"
            elif state == 'Idle':
                if classification == "🟠 Necessary Idle":
                    color, tip = '#ff7f0e', "Necessary Idle (classified)"
                else:
                    color, tip = '#d62728', "Waste (default)"
            else:
                color, tip = '#7f7f7f', "Off"

            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=4, color=color, fill=True, fill_color=color,
                fill_opacity=0.9, weight=1,
                tooltip=f"{row['datetime'].strftime('%H:%M:%S')} | {tip}"
            ).add_to(m)

        class_label = classification.split(' ', 1)[1]
        idle_color = '#ff7f0e' if 'Necessary' in classification else '#d62728'
        legend_html = f"""
        <div style="position:fixed;bottom:30px;right:30px;width:160px;z-index:9999;
             font-size:13px;font-family:sans-serif;background:rgba(255,255,255,0.9);
             border:1px solid grey;border-radius:6px;padding:10px;">
            <b>Legend ({class_label})</b><br>
            <div style="margin-top:5px;">
                <i style="background:#2ca02c;width:10px;height:10px;display:inline-block;border-radius:50%"></i> Working<br>
                <i style="background:{idle_color};width:10px;height:10px;display:inline-block;border-radius:50%"></i> <b>{class_label}</b><br>
                <i style="background:#7f7f7f;width:10px;height:10px;display:inline-block;border-radius:50%"></i> Off
            </div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        st_folium(m, height=600, use_container_width=True, key=f"map_{current_start.strftime('%H%M')}")
        st.caption(msg_perf)

    if not df_win.empty:
        total_dt = df_win['delta_t'].sum()
        idle_dt = df_win.loc[df_win['state'] == 'Idle', 'delta_t'].sum()
        liters_idle = df_win.loc[df_win['state'] == 'Idle', 'liters'].sum()

        st.info(
            f"**Block Summary ({slot_minutes} min):** "
            f"Idle time: **{idle_dt / 60:.1f} min** ({idle_dt / total_dt * 100:.0f}%) | "
            f"Idle fuel: **{liters_idle:.2f} L** → "
            f"Classified as: **{classification}**")


# =============================================================================
# Main
# =============================================================================
def main():
    st.title("🚜 Fendt Fleet: Idle Time Analytics")
    st.markdown(
        "Technical product from MPPV/IFTM — Quantifying idle time "
        "in agricultural tractors via publicly available telemetry data."
    )

    result = load_data()
    if result[0] is None:
        st.error("Data not found. Ensure 'telemetry_app.parquet' exists in data/processed/."); return

    df_full, kpi_tractor, kpi_global = result

    if DEV_FAST_MODE:
        st.toast(f"⚡ FAST MODE: Using only {len(df_full):,} rows.", icon="🚀")

    st.sidebar.header("⚙️ Settings")

    tab1, tab2 = st.tabs(["📊 Waste Analysis", "🛰️ Operational Replay"])
    with tab1:
        render_tab_waste(df_full, kpi_tractor, kpi_global)
    with tab2:
        render_tab_replay(df_full)


if __name__ == "__main__":
    main()
