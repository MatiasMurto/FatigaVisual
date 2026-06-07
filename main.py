import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import math
import sqlite3
from datetime import datetime
import urllib.request
import os
from collections import deque
import time
import customtkinter as ctk
from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64

MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
KEY_PATH   = os.path.join(os.path.dirname(__file__), "secret.key")

# ==========================================
# 0. CIFRADO SIMÉTRICO (Fernet / AES-128-CBC)
# ==========================================
class GestorCifrado:
    def __init__(self, key_path=KEY_PATH):
        if os.path.exists(key_path):
            with open(key_path, "rb") as f:
                self._key = f.read()
        else:
            self._key = AESGCM.generate_key(bit_length=256)
            with open(key_path, "wb") as f:
                f.write(self._key)
        self._aesgcm = AESGCM(self._key)

    def cifrar(self, valor: str) -> str:
        nonce = os.urandom(12)
        ct    = self._aesgcm.encrypt(nonce, valor.encode(), None)
        return base64.urlsafe_b64encode(nonce + ct).decode()

    def descifrar(self, token: str) -> str:
        try:
            data        = base64.urlsafe_b64decode(token.encode())
            nonce, ct   = data[:12], data[12:]
            return self._aesgcm.decrypt(nonce, ct, None).decode()
        except Exception:
            return token  # dato legado sin cifrar

# ==========================================
# 1. GESTOR DE BASE DE DATOS
# ==========================================
class GestorBD:
    def __init__(self, db_name="fatiga_ocular.db"):
        self.conn    = sqlite3.connect(db_name)
        self.cursor  = self.conn.cursor()
        self.cifrado = GestorCifrado()
        self.crear_tablas()
        self._migrar_datos_existentes()

    def crear_tablas(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT UNIQUE NOT NULL
            )
        ''')
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS registro_parpadeos (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_hora     TEXT,
                ear_registrado REAL,
                usuario_id     INTEGER,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        ''')
        try:
            self.cursor.execute("ALTER TABLE registro_parpadeos ADD COLUMN usuario_id INTEGER")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def obtener_usuarios(self):
        self.cursor.execute("SELECT id, nombre FROM usuarios ORDER BY nombre")
        return self.cursor.fetchall()

    def agregar_usuario(self, nombre):
        try:
            self.cursor.execute("INSERT INTO usuarios (nombre) VALUES (?)", (nombre,))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute("SELECT id FROM usuarios WHERE nombre = ?", (nombre,))
            return self.cursor.fetchone()[0]

    def _migrar_datos_existentes(self):
        self.cursor.execute("SELECT id, fecha_hora, ear_registrado FROM registro_parpadeos")
        rows = self.cursor.fetchall()
        for id_, fecha, ear in rows:
            if not str(fecha).startswith("gAAAAA"):
                self.cursor.execute(
                    "UPDATE registro_parpadeos SET fecha_hora=?, ear_registrado=? WHERE id=?",
                    (self.cifrado.cifrar(str(fecha)), self.cifrado.cifrar(str(ear)), id_)
                )
        self.conn.commit()

    def registrar_parpadeo(self, ear_value, usuario_id=None):
        ahora       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fecha_c     = self.cifrado.cifrar(ahora)
        ear_c       = self.cifrado.cifrar(str(round(ear_value, 3)))
        self.cursor.execute(
            "INSERT INTO registro_parpadeos (fecha_hora, ear_registrado, usuario_id) VALUES (?, ?, ?)",
            (fecha_c, ear_c, usuario_id)
        )
        self.conn.commit()

    def obtener_estadisticas(self, usuario_id=None):
        filas = self.obtener_historial(usuario_id, limit=999999)
        if not filas:
            return (0, None, None, None)
        fechas = [f[0] for f in filas]
        ears   = []
        for f in filas:
            try:
                ears.append(float(f[1]))
            except ValueError:
                pass
        total   = len(filas)
        avg_ear = round(sum(ears) / len(ears), 3) if ears else None
        primera = min(fechas) if fechas else None
        ultima  = max(fechas) if fechas else None
        return (total, avg_ear, primera, ultima)

    def obtener_historial(self, usuario_id=None, limit=50):
        if usuario_id:
            self.cursor.execute('''
                SELECT r.fecha_hora, r.ear_registrado, COALESCE(u.nombre,'Sin usuario')
                FROM registro_parpadeos r
                LEFT JOIN usuarios u ON r.usuario_id = u.id
                WHERE r.usuario_id = ? ORDER BY r.id DESC LIMIT ?
            ''', (usuario_id, limit))
        else:
            self.cursor.execute('''
                SELECT r.fecha_hora, r.ear_registrado, COALESCE(u.nombre,'Sin usuario')
                FROM registro_parpadeos r
                LEFT JOIN usuarios u ON r.usuario_id = u.id
                ORDER BY r.id DESC LIMIT ?
            ''', (limit,))
        return [
            (self.cifrado.descifrar(str(f)), self.cifrado.descifrar(str(e)), n)
            for f, e, n in self.cursor.fetchall()
        ]

    def cerrar(self):
        self.conn.close()

# ==========================================
# 2. CALCULADOR EAR
# ==========================================
class CalculadorEAR:
    OJO_IZQUIERDO = [33, 160, 158, 133, 153, 144]
    OJO_DERECHO   = [362, 385, 387, 263, 373, 380]

    @staticmethod
    def distancia_euclidiana(p1, p2):
        return math.dist(p1, p2)

    @classmethod
    def obtener_coordenadas(cls, indices, landmarks, w, h):
        return [(int(landmarks[i].x * w), int(landmarks[i].y * h)) for i in indices]

    @classmethod
    def calcular_ear_ojo(cls, puntos):
        v1 = cls.distancia_euclidiana(puntos[1], puntos[5])
        v2 = cls.distancia_euclidiana(puntos[2], puntos[4])
        h  = cls.distancia_euclidiana(puntos[0], puntos[3])
        if h == 0:
            return 0.0
        return (v1 + v2) / (2.0 * h)

# ==========================================
# 3. VENTANA DE ESTADÍSTICAS
# ==========================================
class VentanaEstadisticas(ctk.CTkToplevel):
    def __init__(self, parent, bd, usuario_id=None, usuario_nombre="Todos"):
        super().__init__(parent)
        self.title(f"Estadísticas — {usuario_nombre}")
        self.geometry("700x520")
        self.resizable(False, False)
        self.lift()
        self.focus()

        stats = bd.obtener_estadisticas(usuario_id)
        total, avg_ear, primera, ultima = stats if stats else (0, 0, "-", "-")

        frame_res = ctk.CTkFrame(self)
        frame_res.pack(fill="x", padx=20, pady=(20, 10))
        cards = [
            ("Total Parpadeos", str(total or 0)),
            ("EAR Promedio",    str(avg_ear or 0)),
            ("Primera sesión",  str(primera or "-")[:10]),
            ("Última sesión",   str(ultima  or "-")[:10]),
        ]
        for i, (lbl, val) in enumerate(cards):
            frame_res.grid_columnconfigure(i, weight=1)
            f = ctk.CTkFrame(frame_res)
            f.grid(row=0, column=i, padx=6, pady=6, sticky="ew")
            ctk.CTkLabel(f, text=val, font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(10, 2))
            ctk.CTkLabel(f, text=lbl, text_color="gray").pack(pady=(0, 10))

        tabla = ctk.CTkScrollableFrame(self, label_text="Últimos 50 registros")
        tabla.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        headers = ["Fecha / Hora", "EAR", "Usuario"]
        widths  = [220, 80, 180]
        for col, (h_txt, w) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(tabla, text=h_txt, font=ctk.CTkFont(weight="bold"),
                         width=w, anchor="w").grid(row=0, column=col, padx=4, pady=(4, 8), sticky="w")

        for ri, (fecha, ear, nombre) in enumerate(bd.obtener_historial(usuario_id, 50), start=1):
            bg = "#2b2b2b" if ri % 2 == 0 else "#1e1e1e"
            for col, (val, w) in enumerate(zip([fecha, f"{ear:.3f}", nombre], widths)):
                ctk.CTkLabel(tabla, text=val, width=w, anchor="w",
                             fg_color=bg, corner_radius=0).grid(
                    row=ri, column=col, padx=4, pady=1, sticky="ew")

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================

# Valores por defecto de calibración
DEFAULTS = {
    "umbral_ear":  0.22,
    "frames_cons": 3,
    "buffer_ear":  5,
    "brillo":      0,
    "contraste":   1.0,
    "clahe":       3.5,
}

class InterfazFatiga(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Sistema Inteligente - Fatiga Ocular (EAR)")
        self.geometry("1050x660")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Estado detección
        self.contador_cuadros  = 0
        self.total_parpadeos   = 0
        self.historial_tiempos = []
        self.sistema_activo    = False
        self.camara_visible    = False
        self.cap               = None
        self.usuario_id        = None
        self.usuario_nombre    = "Sin usuario"

        # Auto-calibración
        self.calib_fase      = 0   # 0=idle 1=ojos abiertos 2=parpadeando 3=done
        self.calib_muestras  = []
        self.calib_ear_open  = None
        self.calib_inicio    = None
        self.CALIB_DURACION  = 3.0  # segundos por fase

        # Anti-falsos-positivos
        self.cooldown_contador = 0
        self.p_frames_max      = 15   # frames máx cierre (>= = no es parpadeo)
        self.p_cooldown        = 0    # 0 = sin cooldown (frames_min ya protege)

        # Parámetros de calibración (vivos)
        self.p_umbral_ear  = DEFAULTS["umbral_ear"]
        self.p_frames_cons = int(DEFAULTS["frames_cons"])
        self.p_buffer_ear  = int(DEFAULTS["buffer_ear"])
        self.p_brillo      = int(DEFAULTS["brillo"])
        self.p_contraste   = DEFAULTS["contraste"]
        self.p_clahe       = DEFAULTS["clahe"]

        self.bd        = GestorBD()
        self.ear_buffer = deque(maxlen=self.p_buffer_ear)
        self._preparar_mediapipe()
        self._construir_ui()

    # ── MediaPipe ────────────────────────────────────
    def _preparar_mediapipe(self):
        if not os.path.exists(MODEL_PATH):
            print("Descargando modelo FaceLandmarker...")
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.face_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        self.timestamp_ms    = 0

    # ── Construcción UI ──────────────────────────────
    def _construir_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Panel izquierdo con tabs
        panel = ctk.CTkFrame(self, width=290, corner_radius=0)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_propagate(False)

        ctk.CTkLabel(panel, text="Fatiga Ocular EAR",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(16, 8))

        tabs = ctk.CTkTabview(panel)
        tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        tabs.add("Control")
        tabs.add("Calibración")

        self._tab_control(tabs.tab("Control"))
        self._tab_calibracion(tabs.tab("Calibración"))

        # Panel derecho (video) — oculto por defecto
        self.frame_derecho = ctk.CTkFrame(self)
        self.frame_derecho.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.label_video = ctk.CTkLabel(self.frame_derecho, text="")
        self.label_video.pack(expand=True, fill="both")
        self.frame_derecho.grid_remove()
        self.geometry("310x660")

    def _tab_control(self, tab):
        # Usuario
        ctk.CTkLabel(tab, text="Usuario:", anchor="w").pack(fill="x", padx=10)
        frame_usr = ctk.CTkFrame(tab, fg_color="transparent")
        frame_usr.pack(fill="x", padx=10, pady=(2, 8))

        usuarios = self.bd.obtener_usuarios()
        opciones = [u[1] for u in usuarios] if usuarios else ["(ninguno)"]
        self._map_usuarios = {u[1]: u[0] for u in usuarios}

        self.combo_usuario = ctk.CTkComboBox(frame_usr, values=opciones, width=160,
                                              command=self._seleccionar_usuario)
        self.combo_usuario.pack(side="left")
        if usuarios:
            self.combo_usuario.set(opciones[0])
            self._seleccionar_usuario(opciones[0])
        ctk.CTkButton(frame_usr, text="+", width=36,
                      command=self._agregar_usuario).pack(side="left", padx=(6, 0))

        ctk.CTkFrame(tab, height=1, fg_color="#444").pack(fill="x", padx=8, pady=6)

        # Botones
        self.btn_iniciar = ctk.CTkButton(tab, text="Iniciar Detección", command=self.toggle_sistema)
        self.btn_iniciar.pack(padx=10, pady=4, fill="x")

        self.btn_camara = ctk.CTkButton(tab, text="Mostrar Cámara", command=self.toggle_camara,
                                         fg_color="#555", hover_color="#666")
        self.btn_camara.pack(padx=10, pady=4, fill="x")

        ctk.CTkButton(tab, text="Ver Estadísticas", command=self.abrir_estadisticas,
                      fg_color="#2a6b2a", hover_color="#3a8b3a").pack(padx=10, pady=4, fill="x")

        ctk.CTkFrame(tab, height=1, fg_color="#444").pack(fill="x", padx=8, pady=6)

        # Métricas
        self.label_estado = ctk.CTkLabel(tab, text="Estado: INACTIVO", text_color="gray")
        self.label_estado.pack(padx=10, pady=2, anchor="w")

        ctk.CTkLabel(tab, text="Tiempo real:",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(padx=10, pady=(8, 2), anchor="w")

        self.label_ear       = ctk.CTkLabel(tab, text="EAR:              0.000", anchor="w")
        self.label_ear.pack(padx=10, pady=1, fill="x")

        self.label_parpadeos = ctk.CTkLabel(tab, text="Parpadeos:        0", anchor="w")
        self.label_parpadeos.pack(padx=10, pady=1, fill="x")

        self.label_bpm = ctk.CTkLabel(tab, text="Frecuencia:       0 / min",
                                       text_color="cyan", anchor="w")
        self.label_bpm.pack(padx=10, pady=1, fill="x")

        self.label_estado_ojo = ctk.CTkLabel(tab, text="Ojo:              —",
                                              anchor="w", text_color="#aaa")
        self.label_estado_ojo.pack(padx=10, pady=1, fill="x")

        self.label_alerta = ctk.CTkLabel(tab, text="", text_color="red",
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.label_alerta.pack(padx=10, pady=8)

    def _tab_calibracion(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        def slider_row(parent, texto, desde, hasta, valor_def, paso, fmt, callback):
            ctk.CTkLabel(parent, text=texto, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(fill="x", padx=8, pady=(10, 0))
            fila = ctk.CTkFrame(parent, fg_color="transparent")
            fila.pack(fill="x", padx=8)
            lbl_val = ctk.CTkLabel(fila, text=fmt.format(valor_def), width=46, anchor="e")
            lbl_val.pack(side="right")
            sl = ctk.CTkSlider(fila, from_=desde, to=hasta, number_of_steps=int((hasta - desde) / paso),
                                command=lambda v, l=lbl_val, f=fmt, cb=callback: (
                                    l.configure(text=f.format(int(v) if paso >= 1 else round(v, 2))),
                                    cb(v)
                                ))
            sl.set(valor_def)
            sl.pack(side="left", fill="x", expand=True, padx=(0, 6))
            return sl

        # ── Detección ──
        ctk.CTkLabel(scroll, text="— Detección —", text_color="#aaa").pack(pady=(6, 0))

        self.sl_umbral = slider_row(scroll, "Umbral EAR", 0.10, 0.40, self.p_umbral_ear,
                                     0.01, "{:.2f}", lambda v: setattr(self, 'p_umbral_ear', round(v, 2)))

        self.sl_frames = slider_row(scroll, "Frames consecutivos", 1, 10, self.p_frames_cons,
                                     1, "{}", lambda v: setattr(self, 'p_frames_cons', int(v)))

        self.sl_buffer = slider_row(scroll, "Suavizado EAR (frames)", 1, 15, self.p_buffer_ear,
                                     1, "{}", self._actualizar_buffer)

        self.sl_frames_max = slider_row(scroll, "Frames máx. cierre", 5, 40, self.p_frames_max,
                                         1, "{}", lambda v: setattr(self, 'p_frames_max', int(v)))

        self.sl_cooldown = slider_row(scroll, "Cooldown post-parpadeo", 0, 20, self.p_cooldown,
                                       1, "{}", lambda v: setattr(self, 'p_cooldown', int(v)))

        # ── Imagen ──
        ctk.CTkLabel(scroll, text="— Imagen —", text_color="#aaa").pack(pady=(12, 0))

        self.sl_brillo = slider_row(scroll, "Brillo", -100, 100, self.p_brillo,
                                     1, "{:+}", lambda v: setattr(self, 'p_brillo', int(v)))

        self.sl_contraste = slider_row(scroll, "Contraste", 0.5, 3.0, self.p_contraste,
                                        0.05, "{:.2f}", lambda v: setattr(self, 'p_contraste', round(v, 2)))

        self.sl_clahe = slider_row(scroll, "CLAHE (anti-reflejos)", 0.0, 8.0, self.p_clahe,
                                    0.1, "{:.1f}", lambda v: setattr(self, 'p_clahe', round(v, 1)))

        ctk.CTkFrame(scroll, height=1, fg_color="#444").pack(fill="x", padx=8, pady=12)

        # Auto-calibración
        ctk.CTkLabel(scroll, text="— Auto-calibración —", text_color="#aaa").pack(pady=(0, 4))

        self.btn_auto = ctk.CTkButton(scroll, text="Auto-calibrar",
                                       fg_color="#5a3a9a", hover_color="#7a4abb",
                                       command=self._iniciar_auto_calibracion)
        self.btn_auto.pack(padx=10, pady=4, fill="x")

        self.label_calib_estado = ctk.CTkLabel(scroll, text="", text_color="#ffcc00",
                                                font=ctk.CTkFont(size=12, weight="bold"),
                                                wraplength=230)
        self.label_calib_estado.pack(padx=10, pady=4)

        ctk.CTkFrame(scroll, height=1, fg_color="#444").pack(fill="x", padx=8, pady=8)

        ctk.CTkButton(scroll, text="Restablecer valores",
                      fg_color="#555", hover_color="#666",
                      command=self._restablecer_calibracion).pack(padx=10, pady=(0, 10), fill="x")

    # ── Auto-calibración ─────────────────────────────
    def _iniciar_auto_calibracion(self):
        if not self.sistema_activo:
            self.label_calib_estado.configure(text="Iniciá la detección primero.")
            return
        self.calib_fase          = 1
        self.calib_muestras      = []
        self.calib_ear_open      = None
        self.calib_inicio        = time.time()
        self.calib_blink_frames  = 0
        self.calib_duraciones    = []
        self.btn_auto.configure(state="disabled")
        self.label_calib_estado.configure(text="Fase 1/2: Mantené los ojos MUY ABIERTOS...")

    def _procesar_auto_calibracion(self, ear):
        if self.calib_fase == 0:
            return
        elapsed = time.time() - self.calib_inicio
        restante = max(0, self.CALIB_DURACION - elapsed)

        if self.calib_fase == 1:
            self.calib_muestras.append(ear)
            self.label_calib_estado.configure(
                text=f"Fase 1/2: Ojos ABIERTOS\n({restante:.1f}s restantes)")
            if elapsed >= self.CALIB_DURACION:
                self.calib_ear_open = sum(self.calib_muestras) / len(self.calib_muestras)
                self.calib_muestras = []
                self.calib_fase     = 2
                self.calib_inicio   = time.time()
                self.label_calib_estado.configure(
                    text="Fase 2/2: Ahora PARPADEÁ normalmente...")

        elif self.calib_fase == 2:
            self.calib_muestras.append(ear)

            # Medir duración real de cada parpadeo
            if ear < self.p_umbral_ear:
                self.calib_blink_frames += 1
            else:
                if self.calib_blink_frames >= self.p_frames_cons:
                    self.calib_duraciones.append(self.calib_blink_frames)
                self.calib_blink_frames = 0

            self.label_calib_estado.configure(
                text=f"Fase 2/2: Parpadeá normalmente\n({restante:.1f}s restantes)")
            if elapsed >= self.CALIB_DURACION:
                ear_min = min(self.calib_muestras)
                umbral  = round((self.calib_ear_open + ear_min) / 2.0, 3)
                umbral  = max(0.10, min(0.40, umbral))

                # Calcular frames_max desde duraciones reales
                if self.calib_duraciones:
                    max_dur    = max(self.calib_duraciones)
                    frames_max = min(40, max(8, int(max_dur * 2 + 3)))
                else:
                    frames_max = 15

                self.p_umbral_ear = umbral
                self.p_frames_max = frames_max
                self.sl_umbral.set(umbral)
                self.sl_frames_max.set(frames_max)
                self.calib_fase = 3

                duraciones_txt = (f"Duración parpadeos: {self.calib_duraciones} frames\n"
                                  if self.calib_duraciones else "Sin parpadeos detectados\n")
                self.label_calib_estado.configure(
                    text=f"Calibrado.\nEAR abierto: {self.calib_ear_open:.3f}\n"
                         f"EAR mín: {ear_min:.3f}  →  Umbral: {umbral:.3f}\n"
                         f"{duraciones_txt}Frames máx cierre: {frames_max}")
                self.btn_auto.configure(state="normal")

    # ── Callbacks calibración ────────────────────────
    def _actualizar_buffer(self, v):
        self.p_buffer_ear = int(v)
        self.ear_buffer   = deque(self.ear_buffer, maxlen=self.p_buffer_ear)

    def _restablecer_calibracion(self):
        self.p_umbral_ear  = DEFAULTS["umbral_ear"]
        self.p_frames_cons = int(DEFAULTS["frames_cons"])
        self.p_buffer_ear  = int(DEFAULTS["buffer_ear"])
        self.p_brillo      = int(DEFAULTS["brillo"])
        self.p_contraste   = DEFAULTS["contraste"]
        self.p_clahe       = DEFAULTS["clahe"]
        self.ear_buffer    = deque(maxlen=self.p_buffer_ear)
        self.sl_umbral.set(self.p_umbral_ear)
        self.sl_frames.set(self.p_frames_cons)
        self.sl_buffer.set(self.p_buffer_ear)
        self.sl_brillo.set(self.p_brillo)
        self.sl_contraste.set(self.p_contraste)
        self.sl_clahe.set(self.p_clahe)

    # ── Usuarios ─────────────────────────────────────
    def _seleccionar_usuario(self, nombre):
        self.usuario_id     = self._map_usuarios.get(nombre)
        self.usuario_nombre = nombre if self.usuario_id else "Sin usuario"

    def _agregar_usuario(self):
        dialogo = ctk.CTkInputDialog(text="Nombre del nuevo usuario:", title="Agregar Usuario")
        nombre  = dialogo.get_input()
        if nombre and nombre.strip():
            nombre = nombre.strip()
            uid    = self.bd.agregar_usuario(nombre)
            self._map_usuarios[nombre] = uid
            self.combo_usuario.configure(values=list(self._map_usuarios.keys()))
            self.combo_usuario.set(nombre)
            self._seleccionar_usuario(nombre)

    # ── Control sistema ──────────────────────────────
    def toggle_sistema(self):
        if not self.sistema_activo:
            self.cap = cv2.VideoCapture(0)
            self.sistema_activo    = True
            self.total_parpadeos   = 0
            self.historial_tiempos = []
            self.ear_buffer.clear()
            self.btn_iniciar.configure(text="Detener Detección",
                                        fg_color="red", hover_color="darkred")
            self.label_estado.configure(text="Estado: ACTIVO", text_color="green")
            self.actualizar_video()
        else:
            self.sistema_activo = False
            self.btn_iniciar.configure(text="Iniciar Detección",
                                        fg_color=["#3B8ED0", "#1F6AA5"],
                                        hover_color=["#36719F", "#144870"])
            self.label_estado.configure(text="Estado: INACTIVO", text_color="gray")
            if self.cap:
                self.cap.release()
            self.label_video.configure(image="", text="")

    def toggle_camara(self):
        self.camara_visible = not self.camara_visible
        if self.camara_visible:
            self.frame_derecho.grid()
            self.geometry("1050x660")
            self.btn_camara.configure(text="Ocultar Cámara")
        else:
            self.frame_derecho.grid_remove()
            self.geometry("310x660")
            self.btn_camara.configure(text="Mostrar Cámara")

    def abrir_estadisticas(self):
        VentanaEstadisticas(self, self.bd, self.usuario_id, self.usuario_nombre)

    # ── Loop de video ────────────────────────────────
    def actualizar_frecuencia(self):
        ahora = time.time()
        self.historial_tiempos = [t for t in self.historial_tiempos if ahora - t <= 60]
        bpm = len(self.historial_tiempos)
        self.label_bpm.configure(text=f"Frecuencia:       {bpm} / min")
        if 0 < bpm < 10:
            self.label_alerta.configure(text="¡ALERTA FATIGA!\nBaja frecuencia\nde parpadeo.")
        else:
            self.label_alerta.configure(text="")

    def dibujar_ojo(self, frame, puntos):
        for i in range(len(puntos)):
            cv2.line(frame, puntos[i], puntos[(i + 1) % len(puntos)], (0, 255, 0), 1)
        # Puntos laterales p1 (índice 0) y p4 (índice 3) en amarillo
        cv2.circle(frame, puntos[0], 3, (0, 255, 255), -1)
        cv2.circle(frame, puntos[3], 3, (0, 255, 255), -1)
        # Puntos verticales p2, p3, p5, p6 en verde
        for i in [1, 2, 4, 5]:
            cv2.circle(frame, puntos[i], 3, (0, 255, 0), -1)

    def actualizar_video(self):
        if self.sistema_activo and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
            except Exception:
                ret = False
            if not ret:
                self.label_estado_ojo.configure(text="Ojo:              sin señal")
                if self.sistema_activo:
                    self.after(500, self.actualizar_video)
                return

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape

            # 1. Brillo / Contraste
            frame_adj = cv2.convertScaleAbs(frame, alpha=self.p_contraste, beta=self.p_brillo)

            # 2. CLAHE en canal L
            if self.p_clahe > 0:
                lab = cv2.cvtColor(frame_adj, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=self.p_clahe, tileGridSize=(12, 12))
                l = clahe.apply(l)
                frame_adj = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

            frame_rgb = cv2.cvtColor(frame_adj, cv2.COLOR_BGR2RGB)
            mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
            resultado = self.face_landmarker.detect_for_video(mp_image, self.timestamp_ms)
            self.timestamp_ms += 33

            ear_suavizado = 0.0
            frame_mostrar = cv2.resize(frame, (640, 480))

            if resultado.face_landmarks:
                for face_landmarks in resultado.face_landmarks:
                    p_izq = CalculadorEAR.obtener_coordenadas(
                        CalculadorEAR.OJO_IZQUIERDO, face_landmarks, w, h)
                    p_der = CalculadorEAR.obtener_coordenadas(
                        CalculadorEAR.OJO_DERECHO, face_landmarks, w, h)

                    ear = (CalculadorEAR.calcular_ear_ojo(p_izq) +
                           CalculadorEAR.calcular_ear_ojo(p_der)) / 2.0
                    self.ear_buffer.append(ear)
                    ear_suavizado = sum(self.ear_buffer) / len(self.ear_buffer)

                    self.dibujar_ojo(frame, p_izq)
                    self.dibujar_ojo(frame, p_der)

                    # Detección con parámetros vivos
                    if ear_suavizado < self.p_umbral_ear:
                        self.contador_cuadros += 1
                        if self.contador_cuadros > self.p_frames_max:
                            estado_ojo = "Cierre largo (ignorado)"
                        else:
                            estado_ojo = "Cerrando..."
                    else:
                        cerrado_ok = self.p_frames_cons <= self.contador_cuadros <= self.p_frames_max
                        if cerrado_ok and self.cooldown_contador == 0:
                            self.total_parpadeos += 1
                            self.historial_tiempos.append(time.time())
                            self.bd.registrar_parpadeo(ear_suavizado, self.usuario_id)
                            self.cooldown_contador = self.p_cooldown
                            cv2.putText(frame, "PARPADEO!", (50, 50),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        self.contador_cuadros = 0
                        if self.cooldown_contador > 0:
                            self.cooldown_contador -= 1
                            estado_ojo = "Cooldown..."
                        else:
                            estado_ojo = "Abierto"

                    self.label_estado_ojo.configure(text=f"Ojo:              {estado_ojo}")
                    self._procesar_auto_calibracion(ear_suavizado)

                    # Zoom digital al rostro
                    xs = [int(lm.x * w) for lm in face_landmarks]
                    ys = [int(lm.y * h) for lm in face_landmarks]
                    x1 = max(0, min(xs) - 80);  y1 = max(0, min(ys) - 120)
                    x2 = min(w, max(xs) + 80);  y2 = min(h, max(ys) + 120)
                    if x2 > x1 and y2 > y1:
                        frame_mostrar = cv2.resize(frame[y1:y2, x1:x2], (640, 480))
            else:
                self.label_estado_ojo.configure(text="Ojo:              sin rostro")

            self.label_ear.configure(text=f"EAR:              {ear_suavizado:.3f}")
            self.label_parpadeos.configure(text=f"Parpadeos:        {self.total_parpadeos}")
            self.actualizar_frecuencia()

            # Overlay calibración
            if self.calib_fase in (1, 2):
                msgs = {1: "OJOS ABIERTOS", 2: "PARPADEA NORMAL"}
                cv2.rectangle(frame_mostrar, (0, 0), (640, 50), (80, 0, 120), -1)
                cv2.putText(frame_mostrar, f"CALIBRANDO: {msgs[self.calib_fase]}",
                            (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 220, 0), 2)

            if self.camara_visible:
                rgb   = cv2.cvtColor(frame_mostrar, cv2.COLOR_BGR2RGB)
                imgtk = ctk.CTkImage(light_image=Image.fromarray(rgb),
                                     dark_image=Image.fromarray(rgb), size=(640, 480))
                self.label_video.imgtk = imgtk
                self.label_video.configure(image=imgtk, text="")
            else:
                self.label_video.configure(image="", text="[ Cámara oculta ]")

        if self.sistema_activo:
            self.after(10, self.actualizar_video)

    def on_closing(self):
        if self.cap:
            self.cap.release()
        self.bd.cerrar()
        self.face_landmarker.close()
        self.destroy()

# ==========================================
# EJECUCIÓN
# ==========================================
if __name__ == "__main__":
    app = InterfazFatiga()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
