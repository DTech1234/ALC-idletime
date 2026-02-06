import streamlit as st
import pandas as pd
import pydeck as pdk
from pathlib import Path

# --- PAGE CONFIG ---
st.set_page_config(layout="wide", page_title="Fendt Fleet: GPU Efficiency Map")

# --- DATA LOADING (Optimized) ---
@st.cache_data
def load_data():
    # 1. Path Resolution (Tenta relativo, depois absoluto)
    path = Path(__file__).parent.parent / "data" / "processed" / "telemetry_app.parquet"
    if not path.exists():
        path = Path(r"E:/Tese/idletime/data/processed/telemetry_app.parquet")
    
    if not path.exists():
        st.error("❌ Data file not found!")
        return None
        
    # 2. Load only necessary columns for map & KPIs
    cols = ['timestamp', 'tractor', 'latitude', 'longitude', 'speed', 'activity', 'state', 'liters_consumed']
    df = pd.read_parquet(path, columns=cols)
    
    # 3. Ensure numeric types for PyDeck (previne erros de visualização)
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    df['liters_consumed'] = pd.to_numeric(df['liters_consumed'], errors='coerce').fillna(0)
    
    # 4. Color Mapping for Map (R, G, B, Alpha)
    # Pré-calculamos as cores para o PyDeck não ter que pensar na hora de renderizar
    color_map = {
        'Idle': [214, 39, 40, 200],    # Vermelho
        'Working': [44, 160, 44, 150], # Verde
        'Off': [128, 128, 128, 50],    # Cinza
        'Transport': [31, 119, 180, 150] # Azul
    }
    
    # Aplica o mapa (Default para Cinza se o estado for desconhecido)
    # O uso de fillna com uma lista fixa evita erros
    df['color'] = df['state'].map(color_map)
    
    # Preenchimento de segurança para cores nulas (caso existam estados novos)
    mask_nan = df['color'].isna()
    if mask_nan.any():
        df.loc[mask_nan, 'color'] = pd.Series([[128, 128, 128, 100]] * mask_nan.sum(), index=df[mask_nan].index)
    
    return df

# --- APP PRINCIPAL ---
def main():
    st.title("🚜 Fendt Fleet: GPU Kinetic Map")
    st.markdown("Use os **Filtros** à esquerda. O mapa atualiza automaticamente sobre imagem de satélite.")

    df_full = load_data()
    if df_full is None: return

    # --- SIDEBAR ---
    st.sidebar.header("⚙️ Configuração")
    
    # 1. Filtros
    tractors = df_full['tractor'].unique()
    sel_tractors = st.sidebar.multiselect("Tratores:", tractors, default=tractors[:1]) 
    
    # Filtra Dados
    df_filtered = df_full[df_full['tractor'].isin(sel_tractors)]
    
    if df_filtered.empty:
        st.warning("Nenhum dado selecionado.")
        return

    # 2. Performance Tuner (Slider de Fluidez)
    total_points = len(df_filtered)
    st.sidebar.markdown("---")
    st.sidebar.subheader("🚀 Performance Tuner")
    
    # Define padrão inteligente para não travar
    default_step = 1
    if total_points > 100000: default_step = 10
    elif total_points > 50000: default_step = 5
    
    step = st.sidebar.slider(f"Amostragem do Mapa (1 = Todos os pontos)", 1, 50, default_step)
    
    # Cria o dataframe de visualização (mais leve)
    df_map = df_filtered.iloc[::step].copy()
    
    st.sidebar.caption(f"Visualizando **{len(df_map):,}** de **{total_points:,}** pontos.")

    # --- CONFIGURAÇÃO DAS CAMADAS (LAYERS) ---
    
    # VIEW STATE (Centraliza automático)
    mid_lat = df_map['latitude'].mean()
    mid_lon = df_map['longitude'].mean()
    
    view_state = pdk.ViewState(
        latitude=mid_lat,
        longitude=mid_lon,
        zoom=14,
        pitch=45, # Inclinação 3D para ver os hexágonos subindo
        bearing=0
    )

    # CAMADA 0: SATÉLITE (Fundo)
    # Usamos o servidor público da Esri World Imagery (ArcGIS)
    layer_satellite = pdk.Layer(
        "TileLayer",
        data="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        id="satellite-layer",
        opacity=1.0 # 100% visível
    )

    # CAMADA 1: RASTRO (Movimento)
    # Pontos coloridos indicando onde o trator passou e o estado dele
    layer_scatter = pdk.Layer(
        "ScatterplotLayer",
        df_map,
        get_position=['longitude', 'latitude'],
        get_color='color',
        get_radius=3, 
        pickable=True,
        opacity=0.8,
        stroked=False
    )

    # CAMADA 2: HEXÁGONOS 3D (Desperdício)
    # Mostra onde o consumo é mais alto (Hotspots de Ocio)
    df_idle_map = df_map[df_map['state'] == 'Idle']
    
    layer_hex = pdk.Layer(
        "HexagonLayer",
        df_idle_map,
        get_position=['longitude', 'latitude'],
        auto_highlight=True,
        elevation_scale=4,
        pickable=True,
        elevation_range=[0, 100],
        extruded=True,
        coverage=1,
        radius=15, 
        upper_percentile=98,
        material=True,
        get_fill_color=[255, 69, 0, 200] # Laranja-Avermelhado
    )

    # --- RENDERIZAÇÃO DO MAPA ---
    st.write(f"### 🗺️ Mapa Operacional ({', '.join(sel_tractors)})")
    
    # Controle de camadas na interface
    show_waste = st.checkbox("Mostrar Pilhas de Desperdício 3D (Ocio)", value=True)
    
    # A ORDEM IMPORTA: O que vem por último fica por cima
    layers_list = [layer_satellite, layer_scatter] 
    
    if show_waste:
        layers_list.append(layer_hex)

    # Tooltip (o que aparece ao passar o mouse)
    tooltip = {
        "html": "<b>Atividade:</b> {activity}<br><b>Estado:</b> {state}<br><b>Velocidade:</b> {speed} km/h",
        "style": {"backgroundColor": "steelblue", "color": "white"}
    }

    # Renderiza o Deck
    r = pdk.Deck(
        layers=layers_list,
        initial_view_state=view_state,
        tooltip=tooltip,
        # Importante: map_style=None para não carregar o mapa padrão do Mapbox por baixo do satélite
        map_style=None 
    )
    
    st.pydeck_chart(r)

    # --- KPIs (Abaixo do mapa) ---
    st.divider()
    c1, c2, c3 = st.columns(3)
    
    # Cálculos nos dados TOTAIS (não amostrados) para manter a precisão dos números
    total_recs = len(df_filtered)
    if total_recs > 0:
        idle_count = len(df_filtered[df_filtered['state'] == 'Idle'])
        idle_pct = (idle_count / total_recs) * 100
    else:
        idle_pct = 0
    
    c1.metric("Pontos Carregados", f"{total_recs:,}")
    c2.metric("Resolução do Mapa", f"1:{step}")
    c3.metric("Frequência de Ociosidade", f"{idle_pct:.1f}%")

if __name__ == "__main__":
    main()