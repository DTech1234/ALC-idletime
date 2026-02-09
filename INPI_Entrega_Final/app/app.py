import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import folium
from folium.plugins import TimestampedGeoJson
from streamlit_folium import st_folium
from pathlib import Path
from datetime import timedelta


st.set_page_config(layout="wide", page_title="Analítico de tempo ocioso em tratores agrícolas", page_icon="🚜")

DIESEL_PRICE_EUR = 1.588
EMISSION_FACTOR  = 2.64
DELTA_T_CUTOFF   = 300
DEV_FAST_MODE = True  

@st.cache_data(show_spinner="Carregando dados...")
def load_data():
    """
    Carrega parquet → reconstrói delta_t → calcula litros reais → pré-calcula KPIs.
    """
    path = Path(__file__).parent.parent / "data" / "processed" / "telemetry_app.parquet"
    if not path.exists():
        path = Path(r"E:/Tese/idletime/data/processed/telemetry_app.parquet")
    if not path.exists():
        return None, None, None

    
    cols = ['timestamp', 'tractor', 'latitude', 'longitude',
            'speed', 'activity', 'state', 'liters_consumed']

    
    if DEV_FAST_MODE:
        
        import pyarrow.parquet as pq
        parquet_file = pq.ParquetFile(path)
        
        batch = next(parquet_file.iter_batches(batch_size=500000, columns=cols))
        df = batch.to_pandas()
    else:
    
        df = pd.read_parquet(path, columns=cols)
    
    df['latitude']  = df['latitude'].astype('float32')
    df['longitude'] = df['longitude'].astype('float32')
    df['speed']     = pd.to_numeric(df['speed'], errors='coerce').fillna(0).astype('float32')
    df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')

    df.rename(columns={'liters_consumed': 'fuel_rate_lh'}, inplace=True)
    df['fuel_rate_lh'] = pd.to_numeric(df['fuel_rate_lh'], errors='coerce').fillna(0).astype('float32')

    df.dropna(subset=['latitude', 'longitude', 'timestamp'], inplace=True)

    df.sort_values(['tractor', 'timestamp'], inplace=True)
    dt = df.groupby('tractor')['timestamp'].diff().fillna(0).values
    dt[dt > DELTA_T_CUTOFF] = 0
    dt[dt < 0] = 0
    df['delta_t'] = dt.astype('float32')
    df['liters'] = (df['fuel_rate_lh'].values * dt / 3600.0).astype('float32')
   
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s', origin='2024-01-01')
    
    r = np.where(df['state'] == 'Idle', 214, np.where(df['state'] == 'Working', 44, 128)).astype('uint8')
    g = np.where(df['state'] == 'Idle',  39, np.where(df['state'] == 'Working', 160, 128)).astype('uint8')
    b = np.where(df['state'] == 'Idle',  40, np.where(df['state'] == 'Working',  44, 128)).astype('uint8')
    a = np.where(df['state'] == 'Idle', 200, np.where(df['state'] == 'Working', 150,  50)).astype('uint8')
    df['color_r'] = r; df['color_g'] = g; df['color_b'] = b; df['color_a'] = a

    df.reset_index(drop=True, inplace=True)

    
    is_idle = (df['state'] == 'Idle')
    
    per_tractor = df.groupby('tractor').agg(
        total_dt   = ('delta_t', 'sum'),
        total_fuel = ('liters', 'sum'),
    )
    idle_agg = df[is_idle].groupby('tractor').agg(
        idle_dt   = ('delta_t', 'sum'),
        idle_fuel = ('liters', 'sum'),
    )
    kpi_tractor = per_tractor.join(idle_agg, how='left').fillna(0)
    kpi_tractor['total_hours'] = kpi_tractor['total_dt'] / 3600
    kpi_tractor['idle_hours']  = kpi_tractor['idle_dt'] / 3600
    kpi_tractor['idle_pct']    = np.where(kpi_tractor['total_hours'] > 0,
                                          kpi_tractor['idle_hours'] / kpi_tractor['total_hours'] * 100, 0)
    kpi_tractor['fuel_waste_pct'] = np.where(kpi_tractor['total_fuel'] > 0,
                                             kpi_tractor['idle_fuel'] / kpi_tractor['total_fuel'] * 100, 0)

    kpi_global = {
        'total_hours': kpi_tractor['total_hours'].sum(),
        'idle_hours':  kpi_tractor['idle_hours'].sum(),
        'total_fuel':  kpi_tractor['total_fuel'].sum(),
        'idle_fuel':   kpi_tractor['idle_fuel'].sum(),
    }
    kpi_global['idle_pct'] = (kpi_global['idle_hours'] / kpi_global['total_hours'] * 100
                              if kpi_global['total_hours'] > 0 else 0)
    kpi_global['fuel_waste_pct'] = (kpi_global['idle_fuel'] / kpi_global['total_fuel'] * 100
                                    if kpi_global['total_fuel'] > 0 else 0)

    return df, kpi_tractor, kpi_global


# =============================================================================
# TAB 1: ANÁLISE DE DESPERDÍCIO
# =============================================================================
def render_tab_waste(df_full, kpi_tractor, kpi_global):
    st.markdown("#### Mapa de Eficiência Operacional")
   
    view_mode = st.radio(
        "Modo de Visualização:",
        ["💰 Concentração de Desperdício (3D)", "🚜 Rastro Operacional (2D)"],
        horizontal=True
    )

    if view_mode == "💰 Concentração de Desperdício (3D)":
        st.caption("Colunas indicam **volume de litros desperdiçados**. Cor = Identidade do Trator.")
    else:
        st.caption("Pontos indicam o **caminho percorrido**. Cor = Estado (Verde=Trabalhando/Transporte, Vermelho=Ocioso).")

    all_tractors = sorted(df_full['tractor'].unique())
    sel_tractors = st.sidebar.multiselect(
        "🚜 Tratores:", all_tractors, default=all_tractors, key="t1_tractors")

    if not sel_tractors:
        st.warning("Selecione ao menos um trator.")
        return

    step = st.sidebar.slider(
        "Amostragem (N pontos ignorados)", 1, 100, 95, key="t1_step",
        help="Aumente se o mapa estiver lento. 1 = todos.")
    
    st.markdown("---")
    kpi_sel = kpi_tractor.loc[kpi_tractor.index.isin(sel_tractors)]
    
    if len(sel_tractors) == len(all_tractors):
        g = kpi_global
    else:
        ks = kpi_sel
        g = {
            'total_hours': ks['total_hours'].sum(),
            'idle_hours':  ks['idle_hours'].sum(),
            'total_fuel':  ks['total_fuel'].sum(),
            'idle_fuel':   ks['idle_fuel'].sum(),
        }
        g['idle_pct'] = g['idle_hours'] / g['total_hours'] * 100 if g['total_hours'] > 0 else 0
        g['fuel_waste_pct'] = g['idle_fuel'] / g['total_fuel'] * 100 if g['total_fuel'] > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    
    c1.metric("Horas Motor Ativo", f"{g['total_hours']:,.1f} h")
       
    with c2:
        st.metric("Ociosidade", f"{g['idle_pct']:.1f}%")
        st.markdown(
            f"<div style='margin-top: -15px; font-size: 14px; color: #808080;'>"
            f"{g['idle_hours']:.1f} h paradas</div>", 
            unsafe_allow_html=True
        )
       
    c3.metric("Diesel Total", f"{g['total_fuel']:,.1f} L")
    with c4:
        st.metric("Diesel Desperdiçado", f"{g['idle_fuel']:,.1f} L")
        st.markdown(
            f"<div style='margin-top: -15px; font-size: 14px; color: #808080;'>"
            f"{g['fuel_waste_pct']:.1f}% do total</div>", 
            unsafe_allow_html=True
        )
    st.markdown("---")

    mask = df_full['tractor'].isin(sel_tractors)
    df_map = df_full.loc[mask].iloc[::step].copy()
    
    df_map['latitude'] = df_map['latitude'].astype(float)
    df_map['longitude'] = df_map['longitude'].astype(float)

    mid_lat = df_map['latitude'].mean()
    mid_lon = df_map['longitude'].mean()

    layers = [
        pdk.Layer(
            "TileLayer",
            data="https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            id="satellite-layer",
            tileSize=256, min_zoom=0, max_zoom=19, opacity=1.0
        )
    ]

    tooltip = {}
    pitch = 0

    if view_mode == "💰 Concentração de Desperdício (3D)":
        df_idle = df_map[df_map['state'] == 'Idle'].copy()
        
        if not df_idle.empty:
            unique_tractors = sorted(df_idle['tractor'].unique())
            base_palette = [
                [0, 255, 255], [0, 128, 255], [255, 0, 255], [255, 165, 0],
                [50, 205, 50], [255, 255, 0], [138, 43, 226], [255, 192, 203]
            ]
            tractor_colors = {t: base_palette[i % len(base_palette)] for i, t in enumerate(unique_tractors)}

            cols = st.columns(min(len(unique_tractors), 8))
            for i, t in enumerate(unique_tractors):
                c = tractor_colors[t]
                with cols[i % 8]:
                    st.markdown(f"**<span style='color:rgb({c[0]},{c[1]},{c[2]})'>◼ {t}</span>**", unsafe_allow_html=True)

            df_idle['lat_round'] = df_idle['latitude'].round(4)
            df_idle['lon_round'] = df_idle['longitude'].round(4)
            
            df_agg = df_idle.groupby(['lat_round', 'lon_round', 'tractor'], as_index=False)['liters'].sum()
            df_agg = df_agg[df_agg['liters'] > 0.01]
            df_agg['liters'] = df_agg['liters'].round(2) 
            df_agg['color'] = df_agg['tractor'].map(tractor_colors)

            layers.append(pdk.Layer(
                "ColumnLayer",
                df_agg,
                get_position=['lon_round', 'lat_round'],
                get_elevation='liters',
                get_fill_color='color',
                radius=5,
                elevation_scale=1000,
                pickable=True,
                auto_highlight=True,
                opacity=0.8,
            ))
            
            tooltip = {
                "html": "<b>{tractor}</b><br>Desperdício Local: <b>{liters} L</b>",
                "style": {"backgroundColor": "black", "color": "white"}
            }
            pitch = 60
        else:
            st.info("Sem dados de ociosidade para exibir.")

    else:
        df_map.loc[df_map['state'] == 'Transport', 'state'] = 'Working'

        state_colors = {
            'Idle': [214, 39, 40, 200],    
            'Working': [44, 160, 44, 150], 
            'Off': [128, 128, 128, 50],    
        }
        
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**<span style='color:green'>● Trabalhando </span>**", unsafe_allow_html=True)
        with c2:
            st.markdown("**<span style='color:red'>● Ocioso </span>**", unsafe_allow_html=True)

        df_map['color'] = df_map['state'].map(state_colors)
        
        mask_nan = df_map['color'].isna()
        if mask_nan.any():
            df_map.loc[mask_nan, 'color'] = pd.Series([[128, 128, 128, 100]] * mask_nan.sum(), index=df_map[mask_nan].index)

        layers.append(pdk.Layer(
            "ScatterplotLayer",
            df_map,
            get_position=['longitude', 'latitude'],
            get_color='color',
            get_radius=3, 
            pickable=True,
            opacity=0.8,
            stroked=False
        ))

        tooltip = {
            "html": "<b>{tractor}</b><br>Estado: <b>{state}</b><br>Vel: {speed} m/s",
            "style": {"backgroundColor": "steelblue", "color": "white"}
        }
        pitch = 0 
    
    st.pydeck_chart(pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(
            latitude=mid_lat, longitude=mid_lon, zoom=14, pitch=pitch
        ),
        tooltip=tooltip,
        map_style=None, 
        map_provider="mapbox"
    ))
    
    st.caption(f"Visualizando {len(df_map):,} registros.")

def render_tab_replay(df_full):
    st.markdown("#### Auditoria de Ociosidade (Passo a Passo)")
    st.caption(
        "Navegue pelo dia em blocos de tempo fixos. "
        "Classifique o comportamento da máquina para cada bloco."
    )

    all_tractors = sorted(df_full['tractor'].unique())
    
    c1, c2 = st.columns(2)
    with c1:
        sel_tractor = st.selectbox("🚜 Trator:", all_tractors, key="t2_tractor")
    
    df_t = df_full[df_full['tractor'] == sel_tractor].copy() 
    if df_t.empty: st.warning("Sem dados."); return

    min_dt_avail, max_dt_avail = df_t['datetime'].min(), df_t['datetime'].max()

    with c2:
        def on_date_change():
            st.session_state['t2_current_start'] = None

        sel_date = st.date_input(
            "📅 Data:", 
            value=min_dt_avail.date(),
            min_value=min_dt_avail.date(), 
            max_value=max_dt_avail.date(), 
            key="t2_date",
            on_change=on_date_change
        )
    
    df_day = df_t[df_t['datetime'].dt.date == sel_date]
    if df_day.empty: st.info(f"Sem dados em {sel_date}."); return

    st.markdown("---")
    
    c_nav1, c_nav2, c_nav3 = st.columns([1, 2, 1])
    
    with c_nav1:
        slot_minutes = st.number_input(
            "⏱️ Tamanho do Bloco (min):", 
            min_value=1, max_value=120, value=15, step=5,
            key="t2_slot_size"
        )
    
    day_start_dt = df_day['datetime'].min().floor(f'{slot_minutes}min')
    day_end_dt = df_day['datetime'].max()

    if 't2_current_start' not in st.session_state or st.session_state['t2_current_start'] is None:
        st.session_state['t2_current_start'] = day_start_dt
    
    if st.session_state['t2_current_start'].date() != sel_date:
        st.session_state['t2_current_start'] = day_start_dt

    def prev_slot():
        new_time = st.session_state['t2_current_start'] - timedelta(minutes=slot_minutes)
        if new_time >= day_start_dt:
            st.session_state['t2_current_start'] = new_time
        else:
            st.toast("Início do dia alcançado!", icon="⏮️")

    def next_slot():
        new_time = st.session_state['t2_current_start'] + timedelta(minutes=slot_minutes)
        if new_time <= day_end_dt:
            st.session_state['t2_current_start'] = new_time
        else:
            st.toast("Fim dos dados do dia!", icon="⏭️")

    current_start = st.session_state['t2_current_start']
    current_end = current_start + timedelta(minutes=slot_minutes)

    with c_nav2:
        st.markdown(f"<div style='text-align: center; font-weight: bold; padding-top: 10px; font-size: 18px;'>"
                    f"{current_start.strftime('%H:%M')} ➝ {current_end.strftime('%H:%M')}"
                    f"</div>", unsafe_allow_html=True)
        
        b_col1, b_col2 = st.columns(2)
        b_col1.button("◀ Anterior", on_click=prev_slot, use_container_width=True)
        b_col2.button("Próximo ▶", on_click=next_slot, use_container_width=True)

    with c_nav3:
        st.markdown("**Classificar Ociosidade:**")
        classification = st.radio(
            "Tipo de Parada:",
            ["🔴 Desperdício", "🟠 Ócio Necessário"],
            label_visibility="collapsed",
            key="t2_class_decision"
        )

    df_win = df_day[(df_day['datetime'] >= current_start) & (df_day['datetime'] < current_end)].copy()
    
    if df_win.empty:
        st.warning(f"Sem movimentação registrada entre {current_start.strftime('%H:%M')} e {current_end.strftime('%H:%M')}.")
    else:
        MAX_POINTS = 800
        if len(df_win) > MAX_POINTS:
            step = len(df_win) // MAX_POINTS
            df_plot = df_win.iloc[::step].copy()
            msg_perf = f"Amostra de {len(df_plot)} pontos (de {len(df_win)})"
        else:
            df_plot = df_win.copy()
            msg_perf = f"Total de {len(df_win)} pontos"

        tile_providers = {
            "Google Híbrido": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
            "Google Satélite": "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        }
        sel_tile = st.sidebar.selectbox("🛰️ Mapa (Aba 2):", list(tile_providers.keys()), key="t2_tiles_sel")
        tile_url = tile_providers[sel_tile]

        mid_lat = df_plot['latitude'].mean()
        mid_lon = df_plot['longitude'].mean()

        m = folium.Map(
            location=[mid_lat, mid_lon], 
            zoom_start=16,
            tiles=tile_url, 
            attr="Google Maps"
        )

        for _, row in df_plot.iterrows():
            state = row['state']
            
            if state in ['Working', 'Transport']:
                color = '#2ca02c' 
                tooltip_txt = "Trabalhando"
            elif state == 'Idle':
                if classification == "🟠 Ócio Necessário":
                    color = '#ff7f0e' 
                    tooltip_txt = "Ócio Necessário (Classificado)"
                else:
                    color = '#d62728'
                    tooltip_txt = "Desperdício (Padrão)"
            else:
                color = '#7f7f7f' 
                tooltip_txt = "Desligado"

            folium.CircleMarker(
                location=[row['latitude'], row['longitude']],
                radius=4, 
                color=color, fill=True, fill_color=color, fill_opacity=0.9, weight=1,
                tooltip=f"{row['datetime'].strftime('%H:%M:%S')} | {tooltip_txt}"
            ).add_to(m)

        legend_html = f"""
        <div style="
            position: fixed; bottom: 30px; right: 30px; width: 160px;
            z-index:9999; font-size:13px; font-family: sans-serif;
            background-color: rgba(255, 255, 255, 0.9);
            border: 1px solid grey; border-radius: 6px; padding: 10px;
        ">
            <b>Legenda ({classification.split(' ')[1]})</b><br>
            <div style="margin-top:5px;">
                <i style="background:#2ca02c; width:10px; height:10px; display:inline-block; border-radius:50%"></i> Trabalhando<br>
                <i style="background:{'#ff7f0e' if 'Necessário' in classification else '#d62728'}; width:10px; height:10px; display:inline-block; border-radius:50%"></i> <b>{classification.split(' ')[1]}</b><br>
                <i style="background:#7f7f7f; width:10px; height:10px; display:inline-block; border-radius:50%"></i> Desligado
            </div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        st_folium(m, height=600, use_container_width=True, key=f"map_{current_start.strftime('%H%M')}")
        st.caption(msg_perf)

    if not df_win.empty:
        total_dt = df_win['delta_t'].sum()
        idle_dt = df_win.loc[df_win['state']=='Idle', 'delta_t'].sum()
        liters_idle = df_win.loc[df_win['state']=='Idle', 'liters'].sum()
        
        st.info(
            f"**Resumo do Bloco ({slot_minutes} min):** "
            f"Tempo Parado: **{idle_dt/60:.1f} min** ({idle_dt/total_dt*100:.0f}%) | "
            f"Consumo em Ocio: **{liters_idle:.2f} L** → "
            f"Classificado como: **{classification}**"
        )

def main():
    st.title("🚜 Fendt Fleet: Idle Time Analytics")
    st.markdown(
        "Produto técnico-tecnológico do MPPV/IFTM — Quantificação do tempo ocioso "
        "em tratores agrícolas via dados de telemetria de acesso público."
    )

    result = load_data()
    
    if result[0] is None:
        st.error("Dados não encontrados.")
        return
    
    df_full, kpi_tractor, kpi_global = result

    if 'DEV_FAST_MODE' in globals() and DEV_FAST_MODE:
        st.toast(f"⚡ MODO RÁPIDO ATIVO: Usando apenas {len(df_full):,} linhas para testes.", icon="🚀")

    st.sidebar.header("⚙️ Configuração")

    tab1, tab2 = st.tabs(["📊 Análise de Desperdício", "🛰️ Replay Operacional"])

    with tab1:
        render_tab_waste(df_full, kpi_tractor, kpi_global)
    with tab2:
        render_tab_replay(df_full)


if __name__ == "__main__":
    main()