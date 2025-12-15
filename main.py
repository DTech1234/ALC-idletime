import customtkinter as ctk
from tkintermapview import TkinterMapView
import pandas as pd
from pathlib import Path
import threading
import traceback

# --- CONFIGURAÇÕES VISUAIS ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class AgroTagApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # 1. Configuração da Janela
        self.title("AgroTag Desktop - Player de Telemetria v2.1")
        self.geometry("1280x800")
        self.minsize(1024, 768)

        # Layout Grid
        self.grid_columnconfigure(0, weight=3) # Mapa
        self.grid_columnconfigure(1, weight=1) # Sidebar
        self.grid_rowconfigure(0, weight=10)   # Principal
        self.grid_rowconfigure(1, weight=1)    # Timeline

        # ===================================================
        # ÁREA 1: O MAPA (Esquerda)
        # ===================================================
        self.map_frame = ctk.CTkFrame(self, corner_radius=0)
        self.map_frame.grid(row=0, column=0, sticky="nswe")

        self.map_widget = TkinterMapView(self.map_frame, corner_radius=0)
        self.map_widget.pack(fill="both", expand=True)
        # Satélite Google
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}", max_zoom=22)
        self.map_widget.set_position(51.1657, 10.4515) 
        self.map_widget.set_zoom(6)

        # ===================================================
        # ÁREA 2: PAINEL LATERAL (Direita)
        # ===================================================
        self.sidebar = ctk.CTkFrame(self, corner_radius=0, width=320)
        self.sidebar.grid(row=0, column=1, rowspan=2, sticky="nswe")
        
        ctk.CTkLabel(self.sidebar, text="🚜 Painel de Controle", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(20, 10))

        # --- Bloco A: Seleção ---
        self.info_frame = ctk.CTkFrame(self.sidebar)
        self.info_frame.pack(padx=10, pady=5, fill="x")
        
        ctk.CTkLabel(self.info_frame, text="1. Trator").pack(anchor="w", padx=10)
        self.trator_menu = ctk.CTkOptionMenu(self.info_frame, values=["Carregando..."], command=self.safe_change_tractor)
        self.trator_menu.pack(pady=2, fill="x", padx=10)

        ctk.CTkLabel(self.info_frame, text="2. Tamanho do Bloco (Min)").pack(anchor="w", padx=10)
        self.interval_var = ctk.StringVar(value="10")
        self.cmb_interval = ctk.CTkOptionMenu(self.info_frame, values=["10", "30", "60"], command=self.update_ops_list, variable=self.interval_var)
        self.cmb_interval.pack(pady=2, fill="x", padx=10)

        ctk.CTkLabel(self.info_frame, text="3. Operação (OPS)").pack(anchor="w", padx=10)
        self.ops_menu = ctk.CTkOptionMenu(self.info_frame, values=["---"], command=self.safe_change_ops)
        self.ops_menu.pack(pady=(2, 10), fill="x", padx=10)

        # --- Bloco B: Status Duplo (NOVO) ---
        self.status_frame = ctk.CTkFrame(self.sidebar)
        self.status_frame.pack(padx=10, pady=10, fill="x")
        
        # 1. Indicador do Algoritmo (Físico)
        ctk.CTkLabel(self.status_frame, text="Estado Detectado (Algoritmo):", font=("Arial", 11)).pack(anchor="w", padx=10, pady=(10,0))
        self.lbl_state = ctk.CTkLabel(self.status_frame, text="---", font=("Arial", 22, "bold"))
        self.lbl_state.pack(fill="x", pady=(0, 10))

        # Divisor
        ctk.CTkFrame(self.status_frame, height=2, fg_color="gray30").pack(fill="x", padx=10, pady=5)

        # 2. Indicador do Dataset (Tag)
        ctk.CTkLabel(self.status_frame, text="Atividade Rotulada (Tag):", font=("Arial", 11)).pack(anchor="w", padx=10, pady=(5,0))
        self.lbl_activity = ctk.CTkLabel(self.status_frame, text="---", font=("Arial", 18, "bold"), text_color="#FFD700") # Ouro
        self.lbl_activity.pack(fill="x", pady=(0, 10))
        
        # Relógio
        self.lbl_hora = ctk.CTkLabel(self.sidebar, text="00:00:00", font=("Arial", 12))
        self.lbl_hora.pack(pady=2)

        # --- Bloco C: Telemetria ---
        self.gauges_frame = ctk.CTkFrame(self.sidebar)
        self.gauges_frame.pack(padx=10, pady=10, fill="x")
        ctk.CTkLabel(self.gauges_frame, text="Instrumentos", font=("Arial", 12, "bold")).pack(pady=5)
        
        # Velocidade
        self.lbl_speed_val = ctk.CTkLabel(self.gauges_frame, text="0 km/h")
        self.lbl_speed_val.pack(anchor="e", padx=10)
        self.bar_speed = ctk.CTkProgressBar(self.gauges_frame)
        self.bar_speed.pack(fill="x", padx=10, pady=(0, 10))
        self.bar_speed.set(0)

        # RPM
        self.lbl_rpm_val = ctk.CTkLabel(self.gauges_frame, text="0 RPM")
        self.lbl_rpm_val.pack(anchor="e", padx=10)
        self.bar_rpm = ctk.CTkProgressBar(self.gauges_frame, progress_color="green")
        self.bar_rpm.pack(fill="x", padx=10, pady=(0, 10))
        self.bar_rpm.set(0)

        # Consumo Instantâneo
        self.lbl_fuel_val = ctk.CTkLabel(self.gauges_frame, text="0 L/h")
        self.lbl_fuel_val.pack(anchor="e", padx=10)
        self.bar_fuel = ctk.CTkProgressBar(self.gauges_frame, progress_color="red")
        self.bar_fuel.pack(fill="x", padx=10, pady=(0, 10))
        self.bar_fuel.set(0)

        # --- Bloco D: Validação ---
        self.valid_frame = ctk.CTkFrame(self.sidebar, fg_color="#2B2B2B")
        self.valid_frame.pack(padx=10, pady=10, fill="x")
        ctk.CTkLabel(self.valid_frame, text="📝 Classificação Humana", font=("Arial", 12, "bold")).pack(pady=5)
        
        self.radio_var = ctk.IntVar(value=0)
        opcoes = ["✅ Correto", "🚜 Manobra", "⛽ Abastecimento", "🛑 Espera/Ocio", "🛣️ Transporte"]
        for i, op in enumerate(opcoes):
            ctk.CTkRadioButton(self.valid_frame, text=op, variable=self.radio_var, value=i).pack(anchor="w", padx=20, pady=2)
            
        self.btn_save = ctk.CTkButton(self.valid_frame, text="SALVAR RÓTULO", fg_color="green", hover_color="darkgreen")
        self.btn_save.pack(pady=10, padx=20, fill="x")

        # ===================================================
        # ÁREA 3: PLAYER (Rodapé)
        # ===================================================
        self.player_frame = ctk.CTkFrame(self, height=100)
        self.player_frame.grid(row=1, column=0, sticky="nswe", padx=10, pady=10)
        
        # Slider
        self.slider = ctk.CTkSlider(self.player_frame, from_=0, to=100, command=self.on_slider_drag)
        self.slider.pack(fill="x", padx=20, pady=(15, 5))
        self.slider.set(0)

        # Controles
        self.ctrl_box = ctk.CTkFrame(self.player_frame, fg_color="transparent")
        self.ctrl_box.pack(fill="x", padx=20, pady=5)

        self.btn_play = ctk.CTkButton(self.ctrl_box, text="▶ PLAY", width=100, command=self.toggle_play)
        self.btn_play.pack(side="left", padx=10)

        ctk.CTkLabel(self.ctrl_box, text="Velocidade:").pack(side="left", padx=(20, 5))
        self.speed_var = ctk.StringVar(value="5x")
        self.seg_speed = ctk.CTkSegmentedButton(self.ctrl_box, values=["1x", "2x", "5x", "10x", "20x"], variable=self.speed_var)
        self.seg_speed.pack(side="left")

        # ---------------------------------------------------
        # DADOS & ESTADO
        # ---------------------------------------------------
        self.df_full = None
        self.df_tractor = None
        self.df_ops = None
        self.ops_chunks = []
        
        self.is_playing = False
        self.current_frame = 0
        self.marker_tractor = None

        # Carrega dados
        print("[DEBUG] Iniciando App...")
        self.after(100, self.load_data) 

    def load_data(self):
        try:
            file_path = Path("data/processed/telemetry_app.parquet")
            if not file_path.exists():
                print("❌ ERRO: Arquivo não encontrado.")
                return

            # ADICIONADO 'state' na leitura das colunas
            cols = ['timestamp', 'tractor', 'latitude', 'longitude', 'speed', 'engine_speed', 'activity', 'liters_consumed', 'state']
            self.df_full = pd.read_parquet(file_path, columns=cols)
            self.df_full['timestamp'] = pd.to_datetime(self.df_full['timestamp'])
            self.df_full.sort_values(by=['tractor', 'timestamp'], inplace=True)
            self.df_full.reset_index(drop=True, inplace=True)

            tratores = sorted(self.df_full['tractor'].unique().tolist())
            self.trator_menu.configure(values=tratores)
            self.trator_menu.set(tratores[0])
            self.safe_change_tractor(tratores[0])
            
        except Exception:
            traceback.print_exc()

    def safe_change_tractor(self, tractor_name):
        try:
            self.df_tractor = self.df_full[self.df_full['tractor'] == tractor_name].reset_index(drop=True)
            self.update_ops_list()
        except Exception:
            traceback.print_exc()

    def update_ops_list(self, _=None):
        if self.df_tractor is None: return
        
        try:
            intervalo_min = int(self.interval_var.get())
        except:
            intervalo_min = 10
        
        pontos_por_bloco = intervalo_min * 60 * 10
        total_pontos = len(self.df_tractor)
        
        self.ops_chunks = []
        opcoes_menu = []
        
        for i in range(0, total_pontos, pontos_por_bloco):
            fim = min(i + pontos_por_bloco, total_pontos)
            t_start = self.df_tractor.iloc[i]['timestamp']
            t_end = self.df_tractor.iloc[fim-1]['timestamp']
            label = f"OPS #{len(self.ops_chunks)+1} ({t_start.strftime('%H:%M')} - {t_end.strftime('%H:%M')})"
            self.ops_chunks.append((i, fim))
            opcoes_menu.append(label)
            
        self.ops_menu.configure(values=opcoes_menu)
        if opcoes_menu:
            self.ops_menu.set(opcoes_menu[0])
            self.safe_change_ops(opcoes_menu[0])

    def safe_change_ops(self, ops_label):
        try:
            self.is_playing = False
            self.btn_play.configure(text="▶ PLAY")
            
            idx = int(ops_label.split("#")[1].split(" ")[0]) - 1
            start, end = self.ops_chunks[idx]
            
            self.df_ops = self.df_tractor.iloc[start:end].reset_index(drop=True)
            self.df_ops = self.df_ops.dropna(subset=['latitude', 'longitude'])
            
            self.current_frame = 0
            self.slider.configure(to=len(self.df_ops)-1)
            self.slider.set(0)
            
            self.update_gui_elements(0)
            self.draw_static_route()
            
        except Exception:
            traceback.print_exc()

    def draw_static_route(self):
        if self.df_ops is None or self.df_ops.empty: return
        
        self.map_widget.delete_all_path()
        self.map_widget.delete_all_marker()
        
        MAX_POINTS = 3000 
        total = len(self.df_ops)
        step = max(1, total // MAX_POINTS)
        
        df_vis = self.df_ops.iloc[::step]
        path = list(zip(df_vis['latitude'], df_vis['longitude']))
        
        if path:
            self.map_widget.set_path(path, color="#00FFFF", width=2)
            self.map_widget.set_position(path[0][0], path[0][1])
            self.map_widget.set_zoom(15)
            self.marker_tractor = self.map_widget.set_marker(path[0][0], path[0][1], text="🚜")

    def update_gui_elements(self, idx):
        if self.df_ops is None or idx >= len(self.df_ops): return
        
        row = self.df_ops.iloc[idx]
        
        # --- ATUALIZAÇÃO DO MAPA ---
        self.map_widget.delete_all_marker()
        self.marker_tractor = self.map_widget.set_marker(row['latitude'], row['longitude'], text="🚜")
        
        # --- LÓGICA DE TEXTO E COR (AQUI ESTÁ A MUDANÇA) ---
        
        # 1. Estado (Algoritmo)
        state = row['state'] # Vem do Parquet ('Idle' ou 'Working')
        self.lbl_state.configure(text=state.upper())
        
        if state == "Idle":
            self.lbl_state.configure(text_color="#FF4444") # Vermelho
        else:
            self.lbl_state.configure(text_color="#00FF00") # Verde Neon

        # 2. Atividade (Dataset)
        activity = row['activity']
        if str(activity).lower() == "not working":
            display_activity = "GERAL"
        else:
            display_activity = str(activity).upper()
            
        self.lbl_activity.configure(text=display_activity)
        
        # 3. Hora
        self.lbl_hora.configure(text=row['timestamp'].strftime('%d/%m %H:%M:%S'))
        
        # --- GAUGES ---
        spd = row['speed']
        self.bar_speed.set(min(spd / 40, 1.0))
        self.lbl_speed_val.configure(text=f"{spd:.1f} km/h")
        
        rpm = row['engine_speed']
        self.bar_rpm.set(min(rpm / 2500, 1.0))
        self.lbl_rpm_val.configure(text=f"{int(rpm)} RPM")
        
        fuel = row['liters_consumed']
        self.bar_fuel.set(min(fuel / 50, 1.0))
        self.lbl_fuel_val.configure(text=f"{fuel:.1f} L/h")

    def on_slider_drag(self, value):
        self.current_frame = int(value)
        self.update_gui_elements(self.current_frame)

    def toggle_play(self):
        if self.is_playing:
            self.is_playing = False
            self.btn_play.configure(text="▶ PLAY")
        else:
            self.is_playing = True
            self.btn_play.configure(text="⏸ PAUSE")
            self.play_loop()

    def play_loop(self):
        if not self.is_playing or self.df_ops is None: return
        
        if self.current_frame >= len(self.df_ops) - 1:
            self.is_playing = False
            self.btn_play.configure(text="↺ REPLAY")
            self.current_frame = 0
            return

        try:
            speed_str = self.speed_var.get()
            step = int(speed_str.replace("x", ""))
        except:
            step = 1

        self.update_gui_elements(self.current_frame)
        self.slider.set(self.current_frame)
        
        self.current_frame += step
        if self.current_frame >= len(self.df_ops):
            self.current_frame = len(self.df_ops) - 1

        self.after(50, self.play_loop)

if __name__ == "__main__":
    app = AgroTagApp()
    app.mainloop()