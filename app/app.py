import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import math
import time
from pathlib import Path

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="AgroTag: Playlist de Operações")

# --- FUNÇÕES MATEMÁTICAS ---
def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dLon = lon2 - lon1
    x = math.sin(dLon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(dLon))
    return (math.degrees(math.atan2(x, y)) + 360) % 360

# --- CARREGAMENTO DE DADOS ---
@st.cache_data
def load_data_initial():
    app_dir = Path(__file__).parent
    project_root = app_dir.parent
    file_path = project_root / "data" / "processed" / "telemetry_app.parquet"
    
    if not file_path.exists():
        st.error(f"Arquivo não encontrado: {file_path}")
        return None

    # Carrega colunas essenciais
    cols = ['timestamp', 'tractor', 'latitude', 'longitude', 'speed', 'engine_speed', 'liters_consumed', 'activity', 'state']
    df = pd.read_parquet(file_path, columns=cols)
    
    # Ordena estritamente pela sequência de gravação
    # Se o timestamp for numérico ou datetime, vai funcionar igual para ordenação
    df = df.sort_values(['tractor', 'timestamp']).reset_index(drop=True)
    return df

# --- FUNÇÕES DE PLOTAGEM ---
def get_gauge_plot(speed, rpm, fuel, state, activity):
    fig = go.Figure()
    
    # Velocidade
    fig.add_trace(go.Indicator(
        mode = "gauge+number", value = speed,
        title = {'text': "Velocidade (km/h)"},
        domain = {'x': [0, 0.3], 'y': [0, 1]},
        gauge = {'axis': {'range': [0, 40]}, 'bar': {'color': "darkblue"}}
    ))

    # RPM
    fig.add_trace(go.Indicator(
        mode = "gauge+number", value = rpm,
        title = {'text': "Motor (RPM)"},
        domain = {'x': [0.35, 0.65], 'y': [0, 1]},
        gauge = {
            'axis': {'range': [0, 2500]}, 
            'bar': {'color': "green" if 700 < rpm < 1000 else "red"}, 
            'steps': [{'range': [0, 700], 'color': "lightgray"}, {'range': [700, 1000], 'color': "lightgreen"}]
        }
    ))
    
    # Status
    color_state = "red" if state == "Idle" else "green"
    fig.add_trace(go.Indicator(
        mode = "number+delta", value = fuel,
        title = {'text': f"Consumo (L/h)<br><span style='color:{color_state}'>{state}</span>"},
        domain = {'x': [0.7, 1], 'y': [0, 1]},
    ))

    fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10))
    return fig

def get_map_plot(df_segment, current_idx):
    row = df_segment.iloc[current_idx]
    lat, lon = row['latitude'], row['longitude']
    
    # Seta de Direção
    prev_idx = max(0, current_idx - 1)
    prev_row = df_segment.iloc[prev_idx]
    dist = ((lat - prev_row['latitude'])**2 + (lon - prev_row['longitude'])**2)**0.5
    
    fig = go.Figure()

    # 1. Trajeto (Fundo)
    fig.add_trace(go.Scattermapbox(
        mode = "lines",
        lat = df_segment['latitude'], lon = df_segment['longitude'],
        opacity = 0.4,
        line = {'width': 4, 'color': 'blue'},
        hoverinfo='none'
    ))

    # 2. Seta Vermelha
    if current_idx > 0 and dist > 0:
        fig.add_trace(go.Scattermapbox(
            mode = "lines",
            lat = [prev_row['latitude'], lat], lon = [prev_row['longitude'], lon],
            line = {'width': 6, 'color': 'red'}, name='Direção'
        ))

    # 3. Ponto Atual
    fig.add_trace(go.Scattermapbox(
        mode = "markers",
        lat = [lat], lon = [lon],
        marker = go.scattermapbox.Marker(size=15, color='red', symbol='circle'),
        name = 'Trator'
    ))
    
    fig.update_layout(
        mapbox = {'style': "open-street-map", 'center': {'lat': lat, 'lon': lon}, 'zoom': 16},
        margin={"r":0,"t":0,"l":0,"b":0}, height=450, showlegend=False
    )
    return fig

# --- APP PRINCIPAL ---
def main():
    st.sidebar.title("🚜 AgroTag: Playlist")
    
    # 1. Carregamento
    df_full = load_data_initial()
    if df_full is None: return

    # 2. SELEÇÃO DE TRATOR
    tratores = df_full['tractor'].unique()
    sel_trator = st.sidebar.selectbox("1. Selecione o Trator:", tratores)
    
    # Filtra pelo trator selecionado
    df_t = df_full[df_full['tractor'] == sel_trator].reset_index(drop=True)

    # 3. SEGMENTAÇÃO PURA (MUDANÇA DE ATIVIDADE)
    # Sempre que a atividade muda em relação à linha anterior, criamos um novo ID
    df_t['mudanca'] = df_t['activity'] != df_t['activity'].shift()
    df_t['segment_id'] = df_t['mudanca'].cumsum()

    # Cria o resumo (Playlist)
    playlist = df_t.groupby('segment_id').agg(
        atividade=('activity', 'first'),
        inicio_idx=('timestamp', 'first'), # Usamos o próprio valor para ordenar
        count=('timestamp', 'count')
    ).reset_index()

    # --- FILTRO DE RUÍDO ---
    # Permite esconder segmentos muito curtos (ex: < 1 minuto de dados)
    # Assumindo 1 ponto a cada 1-5 segs, 10 pontos é pouco.
    min_pontos = st.sidebar.slider("Ocultar eventos menores que (pontos):", 10, 500, 5000)
    playlist_filtrada = playlist[playlist['count'] >= min_pontos]

    if len(playlist_filtrada) == 0:
        st.warning("Nenhum segmento encontrado com esse tamanho mínimo.")
        return

    # Função para formatar o texto no Dropdown
    def format_track(idx):
        row = playlist_filtrada.loc[idx] # loc pelo índice original
        # Mostra o ID sequencial, a Atividade e quantos pontos (duração relativa)
        return f"Faixa #{row['segment_id']} | {row['atividade'].upper()} ({row['count']} pts)"

    # 4. SELEÇÃO DA FAIXA
    sel_idx = st.sidebar.selectbox(
        "2. Selecione a Operação (Faixa):",
        options=playlist_filtrada.index,
        format_func=format_track
    )
    
    # Pega o ID real
    seg_id_real = playlist_filtrada.loc[sel_idx, 'segment_id']
    
    # Carrega os dados daquela faixa específica
    df_mission = df_t[df_t['segment_id'] == seg_id_real].reset_index(drop=True)

    # --- INFO LATERAL ---
    st.sidebar.info(
        f"**Faixa #{seg_id_real}**\n\n"
        f"🚜 Atividade: **{df_mission['activity'].iloc[0]}**\n\n"
        f"📏 Duração: {len(df_mission)} registros"
    )

    # --- CONTROLES DO PLAYER ---
    st.sidebar.divider()
    if 'idx' not in st.session_state: st.session_state.idx = 0
    if 'playing' not in st.session_state: st.session_state.playing = False
    
    c1, c2 = st.sidebar.columns(2)
    if c1.button("▶️ PLAY"): st.session_state.playing = True
    if c2.button("⏹️ PAUSE"): st.session_state.playing = False
    
    speed = st.sidebar.select_slider("Velocidade:", [1, 2, 5, 10, 20, 50], value=5)
    st.session_state.idx = st.slider("Progresso", 0, len(df_mission)-1, st.session_state.idx)

    # --- ÁREA VISUAL ---
    col_map, col_inst = st.columns([2, 1])
    
    with col_map:
        st.subheader("📍 Rastreamento")
        map_placeholder = st.empty()
        
    with col_inst:
        st.subheader("📊 Telemetria")
        gauge_placeholder = st.empty()
        info_placeholder = st.empty()
        
        st.divider()
        st.markdown("### 📝 Validação")
        with st.form("validacao"):
            st.caption(f"Sistema diz: **{df_mission['activity'].iloc[0]}**")
            label = st.radio("Realidade:", ["✅ Correto", "🚜 Manobra", "⛽ Abastecimento", "🛑 Espera", "🛣️ Transporte"])
            st.form_submit_button("Salvar")

    # --- LOOP ---
    if st.session_state.playing:
        while st.session_state.idx < len(df_mission):
            i = st.session_state.idx
            row = df_mission.iloc[i]
            
            map_placeholder.plotly_chart(get_map_plot(df_mission, i), use_container_width=True)
            gauge_placeholder.plotly_chart(get_gauge_plot(row['speed'], row['engine_speed'], row['liters_consumed'], row['state'], row['activity']), use_container_width=True)
            
            # Mostra apenas o progresso relativo (Frame X de Y)
            info_placeholder.markdown(f"**Progresso:** {i}/{len(df_mission)} pontos")
            
            st.session_state.idx += 1
            time.sleep(0.5 / speed)
            
            if st.session_state.idx >= len(df_mission)-1:
                st.session_state.playing = False
                break
    else:
        i = st.session_state.idx
        if i >= len(df_mission): 
            st.session_state.idx = 0
            i = 0
        row = df_mission.iloc[i]
        map_placeholder.plotly_chart(get_map_plot(df_mission, i), use_container_width=True)
        gauge_placeholder.plotly_chart(get_gauge_plot(row['speed'], row['engine_speed'], row['liters_consumed'], row['state'], row['activity']), use_container_width=True)

if __name__ == "__main__":
    main()