import traceback  # para depuración
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import math
import statistics
import sqlite3
from datetime import datetime
import urllib.request
import os
import sys
from collections import deque
import time
import customtkinter as ctk
from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import win32api
import win32net
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

MODEL_PATH = os.path.join(os.path.dirname(__file__), "face_landmarker.task")
MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
KEY_PATH   = os.path.join(os.path.dirname(__file__), "secret.key")

# ==========================================
# 0. CIFRADO SIMÉTRICO (AES-GCM)
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
# 0.1 AUTENTICACIÓN CON CUENTA DE WINDOWS
# ==========================================
class GestorAutenticacionWindows:
    GRUPOS_ADMIN = ("administradores", "administrators")

    @staticmethod
    def usuario_actual():
        return win32api.GetUserName()

    @staticmethod
    def es_admin_windows(usuario):
        try:
            grupos = win32net.NetUserGetLocalGroups(None, usuario)
            return any(g.lower() in GestorAutenticacionWindows.GRUPOS_ADMIN for g in grupos)
        except Exception:
            return False

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
        try:
            self.cursor.execute("ALTER TABLE usuarios ADD COLUMN rol TEXT NOT NULL DEFAULT 'Usuario'")
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute("ALTER TABLE registro_parpadeos ADD COLUMN nivel_fatiga TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute("ALTER TABLE registro_parpadeos ADD COLUMN duracion_ms TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute("ALTER TABLE registro_parpadeos ADD COLUMN clasificacion_parpadeo TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute("ALTER TABLE registro_parpadeos ADD COLUMN perclos TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute("ALTER TABLE registro_parpadeos ADD COLUMN indice_fatiga TEXT")
        except sqlite3.OperationalError:
            pass
        self.conn.commit()

    def obtener_usuarios(self):
        self.cursor.execute("SELECT id, nombre, rol FROM usuarios ORDER BY nombre")
        return self.cursor.fetchall()

    def agregar_usuario(self, nombre, rol="Usuario"):
        try:
            self.cursor.execute("INSERT INTO usuarios (nombre, rol) VALUES (?, ?)", (nombre, rol))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            self.cursor.execute("SELECT id FROM usuarios WHERE nombre = ?", (nombre,))
            return self.cursor.fetchone()[0]

    def obtener_o_crear_usuario(self, nombre, rol_por_defecto="Usuario"):
        self.cursor.execute("SELECT id, rol FROM usuarios WHERE nombre = ?", (nombre,))
        fila = self.cursor.fetchone()
        if fila:
            return fila[0], fila[1]
        usuario_id = self.agregar_usuario(nombre, rol_por_defecto)
        return usuario_id, rol_por_defecto

    def actualizar_rol(self, usuario_id, nuevo_rol):
        self.cursor.execute("UPDATE usuarios SET rol = ? WHERE id = ?", (nuevo_rol, usuario_id))
        self.conn.commit()

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

    def registrar_parpadeo(self, ear_value, usuario_id=None, nivel_fatiga=None,
                            duracion_ms=None, clasificacion_parpadeo=None,
                            perclos=None, indice_fatiga=None):
        ahora      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fecha_c    = self.cifrado.cifrar(ahora)
        ear_c      = self.cifrado.cifrar(str(round(ear_value, 3)))
        nivel_c    = self.cifrado.cifrar(nivel_fatiga) if nivel_fatiga else None
        duracion_c = self.cifrado.cifrar(str(round(duracion_ms, 1))) if duracion_ms is not None else None
        clasif_c   = self.cifrado.cifrar(clasificacion_parpadeo) if clasificacion_parpadeo else None
        perclos_c  = self.cifrado.cifrar(str(round(perclos, 1))) if perclos is not None else None
        indice_c   = self.cifrado.cifrar(str(round(indice_fatiga, 1))) if indice_fatiga is not None else None
        self.cursor.execute(
            """INSERT INTO registro_parpadeos
               (fecha_hora, ear_registrado, usuario_id, nivel_fatiga,
                duracion_ms, clasificacion_parpadeo, perclos, indice_fatiga)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (fecha_c, ear_c, usuario_id, nivel_c, duracion_c, clasif_c, perclos_c, indice_c)
        )
        self.conn.commit()

    def obtener_estadisticas(self, usuario_id=None):
        filas = self.obtener_historial(usuario_id, limit=999999)
        if not filas:
            return (0, None, None, None, None, None)
        fechas = [f[0] for f in filas]
        ears, perclos_vals, indice_vals = [], [], []
        for f in filas:
            try:
                ears.append(float(f[1]))
            except ValueError:
                pass
            try:
                perclos_vals.append(float(f[6]))
            except ValueError:
                pass
            try:
                indice_vals.append(float(f[7]))
            except ValueError:
                pass
        total       = len(filas)
        avg_ear     = round(sum(ears) / len(ears), 3) if ears else None
        avg_perclos = round(sum(perclos_vals) / len(perclos_vals), 1) if perclos_vals else None
        avg_indice  = round(sum(indice_vals) / len(indice_vals), 1) if indice_vals else None
        primera     = min(fechas) if fechas else None
        ultima      = max(fechas) if fechas else None
        return (total, avg_ear, primera, ultima, avg_perclos, avg_indice)

    def obtener_historial(self, usuario_id=None, limit=50):
        columnas = """r.fecha_hora, r.ear_registrado, COALESCE(u.nombre,'Sin usuario'), r.nivel_fatiga,
                      r.duracion_ms, r.clasificacion_parpadeo, r.perclos, r.indice_fatiga"""
        if usuario_id:
            self.cursor.execute(f'''
                SELECT {columnas}
                FROM registro_parpadeos r
                LEFT JOIN usuarios u ON r.usuario_id = u.id
                WHERE r.usuario_id = ? ORDER BY r.id DESC LIMIT ?
            ''', (usuario_id, limit))
        else:
            self.cursor.execute(f'''
                SELECT {columnas}
                FROM registro_parpadeos r
                LEFT JOIN usuarios u ON r.usuario_id = u.id
                ORDER BY r.id DESC LIMIT ?
            ''', (limit,))
        return [
            (self.cifrado.descifrar(str(f)), self.cifrado.descifrar(str(e)), n,
             self.cifrado.descifrar(str(nv)) if nv else "—",
             self.cifrado.descifrar(str(dur)) if dur else "—",
             self.cifrado.descifrar(str(clasif)) if clasif else "—",
             self.cifrado.descifrar(str(perc)) if perc else "—",
             self.cifrado.descifrar(str(idx)) if idx else "—")
            for f, e, n, nv, dur, clasif, perc, idx in self.cursor.fetchall()
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
        self.geometry("980x560")
        self.resizable(False, False)
        self.lift()
        self.focus()

        stats = bd.obtener_estadisticas(usuario_id)
        total, avg_ear, primera, ultima, avg_perclos, avg_indice = stats if stats else (0, 0, "-", "-", 0, 0)

        frame_res = ctk.CTkFrame(self)
        frame_res.pack(fill="x", padx=20, pady=(20, 10))
        cards = [
            ("Total Parpadeos", str(total or 0)),
            ("EAR Promedio",    str(avg_ear or 0)),
            ("PERCLOS Prom.",   f"{avg_perclos or 0} %"),
            ("Índice Fatiga",   str(avg_indice or 0)),
            ("Primera sesión",  str(primera or "-")[:10]),
            ("Última sesión",   str(ultima  or "-")[:10]),
        ]
        for i, (lbl, val) in enumerate(cards):
            frame_res.grid_columnconfigure(i, weight=1)
            f = ctk.CTkFrame(frame_res)
            f.grid(row=0, column=i, padx=6, pady=6, sticky="ew")
            ctk.CTkLabel(f, text=val, font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10, 2))
            ctk.CTkLabel(f, text=lbl, text_color="gray").pack(pady=(0, 10))

        tabla = ctk.CTkScrollableFrame(self, label_text="Últimos 50 registros")
        tabla.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        headers = ["Fecha / Hora", "EAR", "Duración", "Clasif.", "Usuario", "Nivel", "PERCLOS", "Índice"]
        widths  = [155, 55, 75, 85, 110, 80, 70, 60]
        for col, (h_txt, w) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(tabla, text=h_txt, font=ctk.CTkFont(weight="bold"),
                         width=w, anchor="w").grid(row=0, column=col, padx=4, pady=(4, 8), sticky="w")

        for ri, (fecha, ear, nombre, nivel, dur, clasif, perc, idx) in enumerate(
                bd.obtener_historial(usuario_id, 50), start=1):
            bg = "#2b2b2b" if ri % 2 == 0 else "#1e1e1e"
            dur_txt  = f"{dur} ms" if dur != "—" else "—"
            perc_txt = f"{perc} %" if perc != "—" else "—"
            valores  = [fecha, f"{ear:.3f}", dur_txt, clasif, nombre, nivel, perc_txt, idx]
            for col, (val, w) in enumerate(zip(valores, widths)):
                ctk.CTkLabel(tabla, text=val, width=w, anchor="w",
                             fg_color=bg, corner_radius=0).grid(
                    row=ri, column=col, padx=4, pady=1, sticky="ew")

# ==========================================
# 3.1 VENTANA DE LOGIN (autenticación con Windows)
# ==========================================
class VentanaLogin(ctk.CTkToplevel):
    """Confirma la identidad reusando la sesión de Windows ya iniciada."""

    def __init__(self, parent, usuario_windows):
        super().__init__(parent)
        self.title("Iniciar sesión")
        self.geometry("380x220")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancelar)

        self.resultado_ok = False

        ctk.CTkLabel(self, text="Fatiga Ocular EAR",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(28, 8))
        ctk.CTkLabel(self, text="Sesión de Windows detectada:",
                     text_color="gray").pack(pady=(0, 2))
        ctk.CTkLabel(self, text=usuario_windows,
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(0, 20))

        frame_btn = ctk.CTkFrame(self, fg_color="transparent")
        frame_btn.pack(pady=6)
        ctk.CTkButton(frame_btn, text="Continuar", command=self._continuar).pack(side="left", padx=6)
        ctk.CTkButton(frame_btn, text="Salir", fg_color="#555", hover_color="#666",
                      command=self._cancelar).pack(side="left", padx=6)

        self.lift()
        self.grab_set()

    def _continuar(self):
        self.resultado_ok = True
        self.grab_release()
        self.destroy()

    def _cancelar(self):
        self.resultado_ok = False
        self.grab_release()
        self.destroy()

# ==========================================
# 3.2 VENTANA DE GESTIÓN DE USUARIOS (solo Administrador)
# ==========================================
class VentanaGestionUsuarios(ctk.CTkToplevel):
    ROLES = ["Usuario", "Administrador"]

    def __init__(self, parent, bd):
        super().__init__(parent)
        self.title("Gestión de Usuarios")
        self.geometry("420x360")
        self.bd = bd
        self.lift()
        self.focus()

        ctk.CTkLabel(self, text="Roles de usuario", font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 8))

        self.lista = ctk.CTkScrollableFrame(self)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._refrescar()

    def _refrescar(self):
        for widget in self.lista.winfo_children():
            widget.destroy()

        for uid, nombre, rol in self.bd.obtener_usuarios():
            fila = ctk.CTkFrame(self.lista, fg_color="transparent")
            fila.pack(fill="x", pady=4)
            ctk.CTkLabel(fila, text=nombre, width=160, anchor="w").pack(side="left", padx=(0, 6))
            combo = ctk.CTkComboBox(fila, values=self.ROLES, width=140)
            combo.set(rol)
            combo.pack(side="left", padx=(0, 6))
            ctk.CTkButton(fila, text="Guardar", width=70,
                          command=lambda u=uid, c=combo: self._guardar(u, c.get())).pack(side="left")

    def _guardar(self, usuario_id, nuevo_rol):
        self.bd.actualizar_rol(usuario_id, nuevo_rol)
        self._refrescar()

# ==========================================
# 3.3 VENTANA DE GRÁFICA EAR EN TIEMPO REAL
# ==========================================
class VentanaGraficoEAR(ctk.CTkToplevel):
    """Grafica el EAR crudo reciente (self.app.historico_ear) y la línea de
    umbral actual. Útil para validar el algoritmo y para la defensa de tesis."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.title("EAR en tiempo real")
        self.geometry("640x420")
        self.app      = app
        self._cerrado = False
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

        self.figure = Figure(figsize=(6, 3.6), dpi=100)
        self.ax     = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        self.lift()
        self._refrescar()

    def _cerrar(self):
        self._cerrado = True
        self.destroy()

    def _refrescar(self):
        if self._cerrado:
            return
        datos = list(self.app.historico_ear)
        self.ax.clear()
        if datos:
            self.ax.plot(range(len(datos)), datos, color="#3ba7ff", linewidth=1.4, label="EAR")
            self.ax.axhline(self.app.p_umbral_ear, color="red", linestyle="--", linewidth=1,
                             label=f"Umbral {self.app.p_umbral_ear:.2f}")
            self.ax.legend(loc="upper right", fontsize=8)
        self.ax.set_ylim(0.0, 0.5)
        self.ax.set_xlabel("Cuadros recientes (~5 s)")
        self.ax.set_ylabel("EAR")
        self.ax.set_title("EAR en tiempo real")
        self.figure.tight_layout()
        self.canvas.draw()
        self.after(200, self._refrescar)

# ==========================================
# 3.4 VENTANA DE RESUMEN DE LA PRUEBA GUIADA (validación)
# ==========================================
class VentanaResumenPrueba(ctk.CTkToplevel):
    """Muestra, tras la prueba guiada, lo que el usuario debía hacer (esperado)
    contra lo que el sistema detectó (real) por fase. Evidencia de validación."""

    def __init__(self, parent, fases, conteos):
        super().__init__(parent)
        self.title("Resumen de la prueba guiada")
        self.geometry("580x430")
        self.resizable(False, False)
        self.lift()
        self.focus()

        ctk.CTkLabel(self, text="Validación: lo que hiciste vs lo que detectó",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(self, text="P = parpadeos    L = largos/prolongados    F = falsos descartados",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(pady=(0, 10))

        cont = ctk.CTkScrollableFrame(self)
        cont.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        headers = ["Fase", "Esperado", "Detectado", "Desglose", "Result."]
        widths  = [150, 75, 80, 150, 65]
        for c, (h, wd) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(cont, text=h, width=wd, anchor="w",
                         font=ctk.CTkFont(weight="bold")).grid(row=0, column=c, padx=4, pady=(4, 8), sticky="w")

        ri = 1
        for idx, (letra, titulo, instr, dur, esperado, cat) in enumerate(fases):
            if esperado is None:
                continue
            cnt      = conteos[idx] if idx < len(conteos) else {"parpadeo": 0, "prolongado": 0, "falso": 0}
            total    = sum(cnt.values())
            desglose = f"P:{cnt.get('parpadeo',0)}  L:{cnt.get('prolongado',0)}  F:{cnt.get('falso',0)}"

            diff = abs(total - esperado)
            if (esperado == 0 and total == 0) or (esperado > 0 and diff <= 1):
                marca, color = "OK", "#3a8b3a"
            elif diff <= 2:
                marca, color = "~", "#b58b00"
            else:
                marca, color = "X", "#b03030"

            valores = [f"{letra} · {titulo}", str(esperado), str(total), desglose, marca]
            for c, (v, wd) in enumerate(zip(valores, widths)):
                col = color if c == 4 else None
                ctk.CTkLabel(cont, text=v, width=wd, anchor="w",
                             text_color=col).grid(row=ri, column=c, padx=4, pady=2, sticky="w")
            ri += 1

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================

# Valores por defecto de calibración
DEFAULTS = {
    "umbral_ear":  0.22,
    "frames_cons": 2,
    "buffer_ear":  5,
    "brillo":      0,
    "contraste":   1.0,
    "clahe":       3.5,
}

class InterfazFatiga(ctk.CTk):
    # Pesos del índice de fatiga ponderado (PERCLOS/duración/frecuencia/
    # cierres prolongados/variabilidad EAR). Son valores ilustrativos, no
    # validados empíricamente: ajustar con datos reales antes de citarlos
    # como resultado científico en la tesis.
    PESOS_INDICE = {
        "perclos":      0.30,
        "duracion":     0.30,
        "frecuencia":   0.20,
        "prolongados":  0.10,
        "variabilidad": 0.10,
    }

    # Prueba guiada de validación (tutorial fase por fase, estilo asistente).
    # Cada fase: (letra, título, instrucción, duración_s, esperado, categoría_objetivo)
    # esperado/categoría = None → fase de calibración (no se valida).
    GUIA_FASES = [
        ("•", "Calibración", "Mirá la cámara con los ojos MUY ABIERTOS y quieto",        3,  None, None),
        ("A", "Parpadeos normales", "Parpadeá NORMAL (rápido y natural) — 5 veces",      12, 5,    "parpadeo"),
        ("B", "Parpadeos lentos", "Parpadeá LENTO (cerrá ~1 s y abrí) — 5 veces",        15, 5,    "parpadeo"),
        ("C", "Cierres largos", "Cerrá los ojos 3 SEGUNDOS y abrí — 3 veces",            18, 3,    "prolongado"),
        ("D", "Reposo", "Quieto, ojos ABIERTOS, tratá de NO parpadear",                  10, 0,    "falso"),
    ]

    def __init__(self, usuario_windows):
        super().__init__()
        print("DEBUG: InterfazFatiga.__init__ iniciado")
        self.title("Sistema Inteligente - Fatiga Ocular (EAR)")
        self.geometry("1050x660")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Estado detección
        self.cierre_inicio     = None  # timestamp real de inicio de cierre de ojos (None = ojos abiertos)
        self.FPS_REFERENCIA    = 30.0  # referencia para interpretar p_frames_cons/p_frames_max como segundos
        self.total_parpadeos   = 0
        self.historial_tiempos = []
        self.sistema_activo    = False
        self.camara_visible    = False
        self.cap               = None
        self.usuario_id        = None
        self.usuario_nombre    = usuario_windows
        self.rol_actual        = "Usuario"
        self.nariz_previa      = None

        # Auto-calibración (auto-ajustar todo)
        # fases: 0=idle 1=ajuste de imagen 2=ojos abiertos 3=parpadeando 4=done
        self.calib_fase            = 0
        self.calib_muestras        = []
        self.calib_muestras_brillo = []
        self.calib_muestras_std    = []
        self.calib_muestras_alta   = []
        self.calib_muestras_baja   = []
        self.calib_ear_open        = None
        self.calib_inicio          = None
        self.CALIB_DURACION        = 3.0
        self.CALIB_DURACION_IMAGEN = 1.5

        # Baseline de ojo abierto (EAR de referencia). Se fija por calibración
        # implícita al iniciar la detección o por la auto-calibración manual.
        self._baseline_abierto = None

        # Anti-falsos-positivos
        self.cooldown_hasta    = 0.0  # timestamp real hasta el que se ignoran nuevos cierres
        self.p_frames_max      = 15
        self.p_cooldown        = 4    # "cuadros" @ FPS_REFERENCIA (~0.13 s) — evita doble conteo por temblor del párpado al reabrir
        self.umbral_movimiento = 18  # px entre cuadros (nariz) para descartar giro de cabeza

        # Máquina de estados de parpadeo (histéresis + clasificación por duración)
        # Umbrales de clasificación temporal en ms (estándar de literatura EAR/PERCLOS).
        self.ojo_cerrado          = False  # estado persistente para aplicar histéresis
        self.cierre_fin           = None   # último instante con EAR bajo umbral_cerrar (fase profunda)
        self.asimetria_max_cierre = 0.0    # máx |ear_izq-ear_der| observado durante el cierre en curso
        # Umbrales relativos al baseline de ojo abierto (histéresis: cerrar < abrir).
        self.K_CERRAR             = 0.72   # umbral_cerrar = baseline * K_CERRAR
        self.K_ABRIR              = 0.82   # umbral_abrir  = baseline * K_ABRIR (banda muerta anti-chattering)
        self.ASIMETRIA_MAX        = 0.08   # asimetría mayor durante el cierre = un solo ojo (reflejo) → falso
        self.RUIDO_MIN_MS         = 70     # cierre más corto que esto = ruido, no parpadeo humano real
        self.NORMAL_MAX_MS        = 300    # 70-300 ms  → parpadeo normal
        self.LENTO_MAX_MS         = 500    # 300-500 ms → parpadeo lento
        self.PROLONGADO_MAX_MS    = 2000   # 500-2000 ms → prolongado; > 2000 ms → microsueño
        self.EMERGENCIA_MS        = 15000  # red de seguridad para tracking perdido real (con baseline estable, un cierre largo genuino se deja correr completo)
        self.total_prolongados    = 0
        self.total_falsos         = 0

        # Baseline de ojo abierto: EAR típico con ojos abiertos del que cuelga el
        # umbral. Se fija en los primeros BASELINE_CALIB_S segundos (calibración
        # implícita) y luego se adapta MUY lento y SOLO con ojo abierto confiable,
        # así nunca se contamina con cierres (era la causa del umbral inestable).
        self.baseline_calibrado    = False
        self.baseline_calib_inicio = None
        self.baseline_muestras     = []
        self.BASELINE_CALIB_S      = 2.0   # segundos iniciales para fijar el baseline
        self.BASELINE_EMA          = 0.02  # peso de adaptación lenta en operación

        # FPS real (diagnóstico: resolución temporal de la medición de duración)
        self._fps    = 0.0
        self._fps_n  = 0
        self._fps_t0 = None

        # Prueba guiada de validación
        self.guia_activa      = False
        self.guia_fase_idx    = 0
        self.guia_fase_inicio = None
        self.guia_conteos     = []  # paralelo a GUIA_FASES: {"parpadeo","prolongado","falso"} por fase

        # PERCLOS + índice de fatiga ponderado
        self.PERCLOS_VENTANA       = 60.0  # segundos de ventana móvil para PERCLOS
        self._ultimo_ts_perclos    = None
        self.perclos_buffer        = deque()  # (timestamp, dt, cerrado) recortado por tiempo
        self.perclos_actual        = 0.0
        self.duraciones_parpadeo   = deque(maxlen=20)  # segundos, últimos cierres (parpadeo o prolongado)
        self.prolongados_recientes = deque(maxlen=20)  # bool, últimos cierres: ¿fue prolongado?

        # Parámetros de calibración (vivos)
        self.p_umbral_ear  = DEFAULTS["umbral_ear"]
        self.p_frames_cons = int(DEFAULTS["frames_cons"])
        self.p_buffer_ear  = int(DEFAULTS["buffer_ear"])
        self.p_brillo      = int(DEFAULTS["brillo"])
        self.p_contraste   = DEFAULTS["contraste"]
        self.p_clahe       = DEFAULTS["clahe"]

        print("DEBUG: Creando GestorBD...")
        self.bd = GestorBD()
        print("DEBUG: GestorBD creado.")

        es_admin_win = GestorAutenticacionWindows.es_admin_windows(usuario_windows)
        print(f"DEBUG: ¿Es admin Windows? {es_admin_win}")
        self.usuario_id, self.rol_actual = self.bd.obtener_o_crear_usuario(
            usuario_windows, "Administrador" if es_admin_win else "Usuario")
        print(f"DEBUG: Usuario BD id={self.usuario_id}, rol={self.rol_actual}")

        self.ear_buffer    = deque(maxlen=self.p_buffer_ear)
        self.historico_ear = deque(maxlen=150)  # ~5s de EAR crudo (abierto + cerrado) para umbral por percentiles
        self._ema_izq      = None  # suavizado exponencial de puntos del ojo (reduce jitter)
        self._ema_der      = None

        print("DEBUG: Preparando MediaPipe...")
        self._preparar_mediapipe()
        print("DEBUG: MediaPipe listo.")

        print("DEBUG: Construyendo UI...")
        self._construir_ui()
        print("DEBUG: UI construida.")
        print("DEBUG: InterfazFatiga.__init__ completado.")

    # ── MediaPipe ────────────────────────────────────
    def _preparar_mediapipe(self):
        print("DEBUG: _preparar_mediapipe iniciado")
        if not os.path.exists(MODEL_PATH):
            print("Descargando modelo FaceLandmarker...")
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
            print("DEBUG: Modelo descargado.")
        else:
            print("DEBUG: Modelo ya existe.")
        options = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.7,
            min_face_presence_confidence=0.7,
            min_tracking_confidence=0.6
        )
        self.face_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        self.timestamp_ms    = 0
        print("DEBUG: FaceLandmarker creado.")

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
        self._tab_control(tabs.tab("Control"))

        if self.rol_actual == "Administrador":
            tabs.add("Calibración")
            self._tab_calibracion(tabs.tab("Calibración"))

        # Panel derecho (video) — oculto por defecto
        self.frame_derecho = ctk.CTkFrame(self)
        self.frame_derecho.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.label_video = ctk.CTkLabel(self.frame_derecho, text="")
        self.label_video.pack(expand=True, fill="both")
        self.frame_derecho.grid_remove()
        self.geometry("310x660")

    def _tab_control(self, tab):
        # Usuario (identidad = sesión de Windows autenticada al iniciar)
        ctk.CTkLabel(tab, text="Usuario:", anchor="w").pack(fill="x", padx=10)
        ctk.CTkLabel(tab, text=f"{self.usuario_nombre}  ({self.rol_actual})",
                     anchor="w", font=ctk.CTkFont(weight="bold")).pack(fill="x", padx=10, pady=(2, 8))

        if self.rol_actual == "Administrador":
            ctk.CTkButton(tab, text="Gestionar Usuarios", fg_color="#555", hover_color="#666",
                          command=self._abrir_gestion_usuarios).pack(padx=10, pady=(0, 8), fill="x")

        ctk.CTkFrame(tab, height=1, fg_color="#444").pack(fill="x", padx=8, pady=6)

        # Botones
        self.btn_iniciar = ctk.CTkButton(tab, text="Iniciar Detección", command=self.toggle_sistema)
        self.btn_iniciar.pack(padx=10, pady=4, fill="x")

        self.btn_auto = ctk.CTkButton(tab, text="Auto-ajustar Todo",
                                       fg_color="#5a3a9a", hover_color="#7a4abb",
                                       command=self._iniciar_auto_calibracion)
        self.btn_auto.pack(padx=10, pady=4, fill="x")

        self.label_calib_estado = ctk.CTkLabel(tab, text="", text_color="#ffcc00",
                                                font=ctk.CTkFont(size=11, weight="bold"),
                                                wraplength=260, justify="left")
        self.label_calib_estado.pack(padx=10, pady=(0, 4))

        self.btn_camara = ctk.CTkButton(tab, text="Mostrar Cámara", command=self.toggle_camara,
                                         fg_color="#555", hover_color="#666")
        self.btn_camara.pack(padx=10, pady=4, fill="x")

        self.btn_guia = ctk.CTkButton(tab, text="Prueba Guiada", command=self._iniciar_prueba_guiada,
                                       fg_color="#2a5b8a", hover_color="#3a7bba")
        self.btn_guia.pack(padx=10, pady=4, fill="x")

        ctk.CTkButton(tab, text="Ver Estadísticas", command=self.abrir_estadisticas,
                      fg_color="#2a6b2a", hover_color="#3a8b3a").pack(padx=10, pady=4, fill="x")

        if self.rol_actual == "Administrador":
            ctk.CTkButton(tab, text="Ver Estadísticas (Todos)", command=self.abrir_estadisticas_todos,
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

        self.label_prolongados = ctk.CTkLabel(tab, text="Prolongados:      0", anchor="w",
                                              text_color="#ff9040")
        self.label_prolongados.pack(padx=10, pady=1, fill="x")

        self.label_falsos = ctk.CTkLabel(tab, text="Falsos descart.:  0", anchor="w",
                                         text_color="#888")
        self.label_falsos.pack(padx=10, pady=1, fill="x")

        self.label_bpm = ctk.CTkLabel(tab, text="Frecuencia:       0 / min",
                                       text_color="cyan", anchor="w")
        self.label_bpm.pack(padx=10, pady=1, fill="x")

        self.label_perclos = ctk.CTkLabel(tab, text="PERCLOS:          0.0 %",
                                           text_color="orange", anchor="w")
        self.label_perclos.pack(padx=10, pady=1, fill="x")

        self.label_indice = ctk.CTkLabel(tab, text="Índice Fatiga:    0.0 (Normal)",
                                          anchor="w", font=ctk.CTkFont(weight="bold"))
        self.label_indice.pack(padx=10, pady=1, fill="x")

        self.label_estado_ojo = ctk.CTkLabel(tab, text="Ojo:              —",
                                              anchor="w", text_color="#aaa")
        self.label_estado_ojo.pack(padx=10, pady=1, fill="x")

        self.label_fps = ctk.CTkLabel(tab, text="FPS:              0",
                                      anchor="w", text_color="#888")
        self.label_fps.pack(padx=10, pady=1, fill="x")

        self.label_alerta = ctk.CTkLabel(tab, text="", text_color="red",
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.label_alerta.pack(padx=10, pady=8)

        ctk.CTkButton(tab, text="Ver Gráfica EAR", command=self._abrir_grafico_ear,
                      fg_color="#555", hover_color="#666").pack(padx=10, pady=(0, 4), fill="x")

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

        ctk.CTkButton(scroll, text="Fijar Cámara (bloquear auto-ajuste)",
                      fg_color="#555", hover_color="#666",
                      command=self._fijar_camara).pack(padx=10, pady=(4, 0), fill="x")

        ctk.CTkFrame(scroll, height=1, fg_color="#444").pack(fill="x", padx=8, pady=8)

        ctk.CTkButton(scroll, text="Restablecer valores",
                      fg_color="#555", hover_color="#666",
                      command=self._restablecer_calibracion).pack(padx=10, pady=(0, 10), fill="x")

    # ── Auto-calibración (auto-ajustar todo) ─────────
    def _iniciar_auto_calibracion(self):
        if not self.sistema_activo:
            self.label_calib_estado.configure(text="Iniciá la detección primero.")
            return
        self.calib_fase            = 1
        self.calib_muestras        = []
        self.calib_muestras_brillo = []
        self.calib_muestras_std    = []
        self.calib_muestras_alta   = []
        self.calib_muestras_baja   = []
        self.calib_ear_open        = None
        self.calib_inicio          = time.time()
        self.calib_blink_frames    = 0
        self.calib_duraciones      = []
        self.btn_auto.configure(state="disabled")
        self.label_calib_estado.configure(text="Fase 1/3: Ajustando imagen (mirá a cámara)...")

    def _aplicar_ajuste_imagen(self):
        if not self.calib_muestras_brillo:
            return
        brillo_prom = sum(self.calib_muestras_brillo) / len(self.calib_muestras_brillo)
        std_prom    = sum(self.calib_muestras_std) / len(self.calib_muestras_std)
        alta_prom   = sum(self.calib_muestras_alta) / len(self.calib_muestras_alta)
        baja_prom   = sum(self.calib_muestras_baja) / len(self.calib_muestras_baja)

        nuevo_brillo    = int(max(-100, min(100, round(128 - brillo_prom))))
        nuevo_contraste = 1.3 if std_prom < 35 else 1.0
        nuevo_clahe     = 5.5 if (alta_prom > 0.05 or baja_prom > 0.15) else 3.0

        self.p_brillo     = nuevo_brillo
        self.p_contraste  = nuevo_contraste
        self.p_clahe      = nuevo_clahe
        self._set_slider("sl_brillo", nuevo_brillo)
        self._set_slider("sl_contraste", nuevo_contraste)
        self._set_slider("sl_clahe", nuevo_clahe)

        self._fijar_camara()

    def _fijar_camara(self):
        """Congela exposición/foco/balance de blancos de la cámara para que
        deje de reajustarse sola (fuente extra de ruido → parpadeos falsos).
        Best-effort: depende del driver de cada cámara, puede no tener efecto."""
        if not self.cap:
            return
        try:
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        except Exception:
            pass
        try:
            exposicion_actual = self.cap.get(cv2.CAP_PROP_EXPOSURE)
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75)  # DSHOW: 0.75 = manual
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exposicion_actual)
        except Exception:
            pass
        try:
            self.cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        except Exception:
            pass

    def _procesar_auto_calibracion(self, ear, frame=None, recorte_cara=None):
        if self.calib_fase == 0:
            return

        if self.calib_fase == 1:
            elapsed  = time.time() - self.calib_inicio
            restante = max(0, self.CALIB_DURACION_IMAGEN - elapsed)
            if frame is not None and recorte_cara is not None:
                x1, y1, x2, y2 = recorte_cara
                gris = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                self.calib_muestras_brillo.append(float(gris.mean()))
                self.calib_muestras_std.append(float(gris.std()))
                self.calib_muestras_alta.append(float((gris > 240).mean()))
                self.calib_muestras_baja.append(float((gris < 15).mean()))
            self.label_calib_estado.configure(
                text=f"Fase 1/3: Ajustando imagen\n({restante:.1f}s restantes)")
            if elapsed >= self.CALIB_DURACION_IMAGEN:
                self._aplicar_ajuste_imagen()
                self.calib_fase   = 2
                self.calib_inicio = time.time()
                self.label_calib_estado.configure(text="Fase 2/3: Mantené los ojos MUY ABIERTOS...")
            return

        elapsed  = time.time() - self.calib_inicio
        restante = max(0, self.CALIB_DURACION - elapsed)

        if self.calib_fase == 2:
            self.calib_muestras.append(ear)
            self.label_calib_estado.configure(
                text=f"Fase 2/3: Ojos ABIERTOS\n({restante:.1f}s restantes)")
            if elapsed >= self.CALIB_DURACION:
                self.calib_ear_open = sum(self.calib_muestras) / len(self.calib_muestras)
                self.calib_muestras = []
                self.calib_fase     = 3
                self.calib_inicio   = time.time()
                self.label_calib_estado.configure(
                    text="Fase 3/3: Ahora PARPADEÁ normalmente...")

        elif self.calib_fase == 3:
            self.calib_muestras.append(ear)

            if ear < self.p_umbral_ear:
                self.calib_blink_frames += 1
            else:
                if self.calib_blink_frames >= self.p_frames_cons:
                    self.calib_duraciones.append(self.calib_blink_frames)
                self.calib_blink_frames = 0

            self.label_calib_estado.configure(
                text=f"Fase 3/3: Parpadeá normalmente\n({restante:.1f}s restantes)")
            if elapsed >= self.CALIB_DURACION:
                ear_min = min(self.calib_muestras)
                umbral  = round((self.calib_ear_open + ear_min) / 2.0, 3)
                umbral  = max(0.10, min(0.40, umbral))

                if self.calib_duraciones:
                    max_dur    = max(self.calib_duraciones)
                    frames_max = min(40, max(8, int(max_dur * 2 + 3)))
                else:
                    frames_max = 15

                self.p_umbral_ear = umbral
                self.p_frames_max = frames_max
                self._set_slider("sl_umbral", umbral)
                self._set_slider("sl_frames_max", frames_max)

                # La calibración manual siembra directamente el baseline de ojo
                # abierto (equivale y reemplaza a la calibración implícita inicial).
                if self.calib_ear_open:
                    self._baseline_abierto  = self.calib_ear_open
                    self.baseline_calibrado = True
                    self._aplicar_umbral_desde_baseline()

                self.calib_fase = 4

                duraciones_txt = (f"Duración parpadeos: {self.calib_duraciones} frames\n"
                                  if self.calib_duraciones else "Sin parpadeos detectados\n")
                self.label_calib_estado.configure(
                    text=f"Listo. Imagen y umbral ajustados.\nEAR abierto: {self.calib_ear_open:.3f}\n"
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
        # Forzar re-calibración del baseline de ojo abierto
        self._baseline_abierto     = None
        self.baseline_calibrado    = False
        self.baseline_calib_inicio = None
        self.baseline_muestras     = []

    # ── Usuarios ─────────────────────────────────────
    def _abrir_gestion_usuarios(self):
        VentanaGestionUsuarios(self, self.bd)

    # ── Control sistema ──────────────────────────────
    def toggle_sistema(self):
        if not self.sistema_activo:
            self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.sistema_activo    = True
            self.total_parpadeos   = 0
            self.total_prolongados = 0
            self.total_falsos      = 0
            self.historial_tiempos = []
            self.ear_buffer.clear()
            self.historico_ear.clear()
            self.perclos_buffer.clear()
            self.perclos_actual     = 0.0
            self._ultimo_ts_perclos = None
            self.duraciones_parpadeo.clear()
            self.prolongados_recientes.clear()
            self.ojo_cerrado          = False
            self.asimetria_max_cierre = 0.0
            self.cierre_inicio        = None
            self.cierre_fin           = None
            self.cooldown_hasta       = 0.0
            self._fps = 0.0; self._fps_n = 0; self._fps_t0 = None
            # Re-calibrar baseline al iniciar (salvo que ya venga de auto-calibración)
            if not self.baseline_calibrado:
                self._baseline_abierto     = None
                self.baseline_calib_inicio = None
                self.baseline_muestras     = []
            self.btn_iniciar.configure(text="Detener Detección",
                                        fg_color="red", hover_color="darkred")
            self.label_estado.configure(text="Estado: ACTIVO", text_color="green")
            self.actualizar_video()
        else:
            self.sistema_activo = False
            self._cancelar_prueba_guiada()  # si estaba en curso, abortarla
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

    def abrir_estadisticas_todos(self):
        VentanaEstadisticas(self, self.bd, None, "Todos")

    def _abrir_grafico_ear(self):
        VentanaGraficoEAR(self, self)

    # ── Prueba guiada de validación ──────────────────
    def _iniciar_prueba_guiada(self):
        if not self.sistema_activo:
            self.toggle_sistema()          # arranca la detección
        if not self.camara_visible:
            self.toggle_camara()           # asegura que se vea la guía
        # Recalibrar baseline desde cero (la fase 0 de la guía lo calibra)
        self._baseline_abierto     = None
        self.baseline_calibrado    = False
        self.baseline_calib_inicio = None
        self.baseline_muestras     = []
        # Empezar contadores limpios
        self.total_parpadeos   = 0
        self.total_prolongados = 0
        self.total_falsos      = 0
        self.historial_tiempos = []
        self.guia_conteos     = [{"parpadeo": 0, "prolongado": 0, "falso": 0}
                                 for _ in self.GUIA_FASES]
        self.guia_fase_idx    = 0
        self.guia_fase_inicio = time.time()
        self.guia_activa      = True
        self.btn_guia.configure(state="disabled")
        print("\n########## PRUEBA GUIADA INICIADA ##########")
        self._imprimir_inicio_fase()

    def _imprimir_inicio_fase(self):
        letra, titulo, instr, dur, esperado, cat = self.GUIA_FASES[self.guia_fase_idx]
        esp = f"esperado {esperado}" if esperado is not None else "calibración"
        print(f"\n=== FASE {letra}: {titulo} ({esp}, {dur}s) ===")
        print(f"    -> {instr}")

    def _procesar_prueba_guiada(self):
        """Avanza automáticamente de fase según el tiempo transcurrido."""
        if not self.guia_activa:
            return
        _, _, _, dur, _, _ = self.GUIA_FASES[self.guia_fase_idx]
        if time.time() - self.guia_fase_inicio >= dur:
            self.guia_fase_idx    += 1
            self.guia_fase_inicio  = time.time()
            if self.guia_fase_idx >= len(self.GUIA_FASES):
                self._finalizar_prueba_guiada()
            else:
                self._imprimir_inicio_fase()

    def _cancelar_prueba_guiada(self):
        self.guia_activa = False
        if hasattr(self, "btn_guia"):
            self.btn_guia.configure(state="normal")

    def _finalizar_prueba_guiada(self):
        self.guia_activa = False
        self.btn_guia.configure(state="normal")
        # Resumen también por consola (además de la ventana)
        print("\n########## RESUMEN PRUEBA GUIADA ##########")
        print(f"{'Fase':<24}{'Esper.':<8}{'Detect.':<9}{'Desglose':<20}{'Result.'}")
        print("-" * 68)
        for idx, (letra, titulo, instr, dur, esperado, cat) in enumerate(self.GUIA_FASES):
            if esperado is None:
                continue
            cnt      = self.guia_conteos[idx]
            total    = sum(cnt.values())
            desglose = f"P:{cnt.get('parpadeo',0)} L:{cnt.get('prolongado',0)} F:{cnt.get('falso',0)}"
            diff     = abs(total - esperado)
            if (esperado == 0 and total == 0) or (esperado > 0 and diff <= 1):
                marca = "OK"
            elif diff <= 2:
                marca = "~"
            else:
                marca = "X"
            print(f"{letra + ' ' + titulo:<24}{esperado:<8}{total:<9}{desglose:<20}{marca}")
        print("=" * 68 + "\n")
        VentanaResumenPrueba(self, self.GUIA_FASES, self.guia_conteos)

    def _dibujar_overlay_guia(self, frame_mostrar):
        letra, titulo, instr, dur, esperado, cat = self.GUIA_FASES[self.guia_fase_idx]
        elapsed  = time.time() - self.guia_fase_inicio
        restante = max(0, int(round(dur - elapsed)))

        # Banda superior: letra de fase + título
        cv2.rectangle(frame_mostrar, (0, 0), (640, 62), (90, 40, 20), -1)
        cv2.putText(frame_mostrar, letra, (14, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 0), 3)
        cv2.putText(frame_mostrar, f"Fase {self.guia_fase_idx}/{len(self.GUIA_FASES) - 1}: {titulo}",
                    (70, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        if esperado is not None:
            hechos = sum(self.guia_conteos[self.guia_fase_idx].values())
            cv2.putText(frame_mostrar, f"detectados: {hechos} / esperado {esperado}",
                        (70, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 230, 180), 1)

        # Barra de progreso de la fase
        prog = int(640 * min(1.0, elapsed / dur)) if dur else 640
        cv2.rectangle(frame_mostrar, (0, 62), (prog, 68), (0, 255, 0), -1)

        # Banda inferior: instrucción + cuenta regresiva
        cv2.rectangle(frame_mostrar, (0, 430), (640, 480), (30, 30, 30), -1)
        cv2.putText(frame_mostrar, instr, (12, 452),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(frame_mostrar, f"{restante}s", (560, 470),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    # ── Loop de video ────────────────────────────────
    def _actualizar_perclos(self, cerrado):
        """PERCLOS = % de tiempo real con ojos cerrados en los últimos
        PERCLOS_VENTANA segundos. Medido con time.time() (no cuenta de
        cuadros), igual que la duración de cierre."""
        ahora = time.time()
        if self._ultimo_ts_perclos is None:
            self._ultimo_ts_perclos = ahora
            return
        dt = ahora - self._ultimo_ts_perclos
        self._ultimo_ts_perclos = ahora
        self.perclos_buffer.append((ahora, dt, cerrado))

        limite = ahora - self.PERCLOS_VENTANA
        while self.perclos_buffer and self.perclos_buffer[0][0] < limite:
            self.perclos_buffer.popleft()

        tiempo_total = sum(d for _, d, _ in self.perclos_buffer)
        if tiempo_total > 0:
            tiempo_cerrado = sum(d for _, d, c in self.perclos_buffer if c)
            self.perclos_actual = round((tiempo_cerrado / tiempo_total) * 100.0, 1)
        else:
            self.perclos_actual = 0.0

    def _clasificar_cierre(self, duracion_ms, asimetria_max):
        """Clasifica un cierre terminado. Devuelve (etiqueta, categoria).
        categoria ∈ {"parpadeo", "prolongado", "falso"} gobierna el conteo:
          - parpadeo   → suma a total_parpadeos y a la frecuencia (bpm)
          - prolongado → señal de fatiga, cuenta aparte
          - falso      → se registra para auditoría pero no cuenta"""
        if asimetria_max > self.ASIMETRIA_MAX:
            return "Falso-reflejo", "falso"     # un ojo cerró y el otro no → destello/lente
        if duracion_ms < self.RUIDO_MIN_MS:
            return "Falso-ruido", "falso"        # demasiado corto para ser humano
        if duracion_ms <= self.NORMAL_MAX_MS:
            return "Normal", "parpadeo"
        if duracion_ms <= self.LENTO_MAX_MS:
            return "Lento", "parpadeo"
        if duracion_ms <= self.PROLONGADO_MAX_MS:
            return "Prolongado", "prolongado"
        return "Microsueño", "prolongado"        # >2000 ms: con baseline estable es ojo cerrado real

    def _registrar_cierre(self, duracion_ms, etiqueta, categoria, ear_suavizado, frame):
        print(f"DEBUG cierre: {duracion_ms:.0f} ms | {etiqueta} ({categoria}) | "
              f"umbral={self.p_umbral_ear:.3f} | asim={self.asimetria_max_cierre:.3f} | "
              f"fps={self._fps:.0f}")
        if categoria == "parpadeo":
            self.total_parpadeos += 1
            self.historial_tiempos.append(time.time())
            self.duraciones_parpadeo.append(duracion_ms / 1000.0)
            self.prolongados_recientes.append(False)
            cv2.putText(frame, "PARPADEO!", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        elif categoria == "prolongado":
            self.total_prolongados += 1
            self.duraciones_parpadeo.append(duracion_ms / 1000.0)
            self.prolongados_recientes.append(True)
            cv2.putText(frame, "CIERRE PROLONGADO", (20, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 140, 255), 2)
        else:  # falso: se guarda para auditoría pero no alimenta el índice de fatiga
            self.total_falsos += 1
            cv2.putText(frame, f"{etiqueta} (descartado)", (20, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (150, 150, 150), 2)

        # Validación: contar el evento en la fase activa de la prueba guiada
        if self.guia_activa and 0 <= self.guia_fase_idx < len(self.guia_conteos):
            conteo = self.guia_conteos[self.guia_fase_idx]
            conteo[categoria] = conteo.get(categoria, 0) + 1

        indice_score, indice_clasif = self._calcular_indice_fatiga()
        self.bd.registrar_parpadeo(
            ear_suavizado, self.usuario_id,
            nivel_fatiga=indice_clasif, duracion_ms=duracion_ms,
            clasificacion_parpadeo=etiqueta,
            perclos=self.perclos_actual, indice_fatiga=indice_score)

    def _resolver_cierre_anomalo(self, ear_actual, dur_ms, ear_suavizado, frame):
        """Cierre en vivo > EMERGENCIA_MS. Con el baseline estable esto casi
        siempre es un cierre genuinamente largo (microsueño): se registra como
        prolongado SIN tocar el baseline. Solo si el EAR actual está cerca del
        baseline (el ojo en realidad está abierto y el baseline quedó bajo) se
        fuerza una recalibración. Distinguir por comparación con el baseline
        evita el bug anterior de tomar un EAR de ojo cerrado como 'abierto'."""
        ref = self._baseline_abierto if self._baseline_abierto else ear_actual
        if ear_actual >= 0.85 * ref:
            print(f"DEBUG emergencia BASELINE-BAJO: EAR={ear_actual:.3f} ref={ref:.3f} → recalibrar")
            self._baseline_abierto = ear_actual
            self._aplicar_umbral_desde_baseline()
            self.total_falsos += 1
            return "Recalibrando baseline"
        print(f"DEBUG emergencia CIERRE-REAL: EAR={ear_actual:.3f} ref={ref:.3f} dur={dur_ms:.0f}ms")
        if time.time() >= self.cooldown_hasta:
            self._registrar_cierre(dur_ms, "Cierre-largo", "prolongado", ear_suavizado, frame)
            self.cooldown_hasta = time.time() + (self.p_cooldown / self.FPS_REFERENCIA)
        return "Cierre prolongado real"

    def _calcular_indice_fatiga(self):
        """Índice 0-100 combinando PERCLOS, duración de cierre, frecuencia de
        parpadeo, proporción de cierres prolongados y variabilidad del EAR.
        Pesos en PESOS_INDICE (ilustrativos, ver comentario en la clase)."""
        ahora = time.time()

        score_perclos = min(100.0, self.perclos_actual)

        techo_duracion_ms = max(1.0, (self.p_frames_max / self.FPS_REFERENCIA) * 1000)
        if self.duraciones_parpadeo:
            dur_prom_ms = (sum(self.duraciones_parpadeo) / len(self.duraciones_parpadeo)) * 1000
        else:
            dur_prom_ms = 0.0
        score_duracion = max(0.0, min(100.0, (dur_prom_ms / techo_duracion_ms) * 100.0))

        recientes = [t for t in self.historial_tiempos if ahora - t <= 60]
        bpm       = len(recientes)
        score_frecuencia = max(0.0, min(100.0, (15 - bpm) / 15 * 100.0))

        if self.prolongados_recientes:
            score_prolongados = (sum(self.prolongados_recientes) / len(self.prolongados_recientes)) * 100.0
        else:
            score_prolongados = 0.0

        if len(self.historico_ear) >= 10:
            variabilidad       = statistics.pstdev(self.historico_ear)
            score_variabilidad = max(0.0, min(100.0, (variabilidad / 0.10) * 100.0))
        else:
            score_variabilidad = 0.0

        score = (
            score_perclos      * self.PESOS_INDICE["perclos"] +
            score_duracion     * self.PESOS_INDICE["duracion"] +
            score_frecuencia   * self.PESOS_INDICE["frecuencia"] +
            score_prolongados  * self.PESOS_INDICE["prolongados"] +
            score_variabilidad * self.PESOS_INDICE["variabilidad"]
        )
        score = round(max(0.0, min(100.0, score)), 1)

        if score <= 30:
            clasificacion = "Normal"
        elif score <= 60:
            clasificacion = "Leve"
        elif score <= 80:
            clasificacion = "Moderada"
        else:
            clasificacion = "Alta"

        return score, clasificacion

    def actualizar_frecuencia(self):
        ahora = time.time()
        self.historial_tiempos = [t for t in self.historial_tiempos if ahora - t <= 60]
        bpm = len(self.historial_tiempos)
        self.label_bpm.configure(text=f"Frecuencia:       {bpm} / min")

        score, clasificacion = self._calcular_indice_fatiga()
        self.label_perclos.configure(text=f"PERCLOS:          {self.perclos_actual:.1f} %")
        colores = {"Normal": "gray", "Leve": "#ffcc00", "Moderada": "orange", "Alta": "red"}
        self.label_indice.configure(text=f"Índice Fatiga:    {score:.1f} ({clasificacion})",
                                     text_color=colores.get(clasificacion, "gray"))

        if clasificacion in ("Moderada", "Alta"):
            self.label_alerta.configure(
                text=f"¡ALERTA FATIGA!\nÍndice {clasificacion.upper()}\nPERCLOS {self.perclos_actual:.0f}%")
        elif 0 < bpm < 10:
            self.label_alerta.configure(text="¡ALERTA FATIGA!\nBaja frecuencia\nde parpadeo.")
        else:
            self.label_alerta.configure(text="")

    @staticmethod
    def _ajustar_a_marco(frame, ancho_marco, alto_marco):
        h, w = frame.shape[:2]
        escala = min(ancho_marco / w, alto_marco / h)
        nuevo_w, nuevo_h = int(w * escala), int(h * escala)
        redimensionado = cv2.resize(frame, (nuevo_w, nuevo_h))

        marco = cv2.copyMakeBorder(
            redimensionado,
            (alto_marco - nuevo_h) // 2, alto_marco - nuevo_h - (alto_marco - nuevo_h) // 2,
            (ancho_marco - nuevo_w) // 2, ancho_marco - nuevo_w - (ancho_marco - nuevo_w) // 2,
            cv2.BORDER_CONSTANT, value=(0, 0, 0)
        )
        return marco

    def _set_slider(self, atributo, valor):
        """Actualiza un slider de Calibración si existe (no existir para rol Usuario)."""
        slider = getattr(self, atributo, None)
        if slider is not None:
            slider.set(valor)

    def _aplicar_umbral_desde_baseline(self):
        """Deriva p_umbral_ear del baseline (para el slider/gráfica y el fallback)."""
        if self._baseline_abierto is None:
            return
        self.p_umbral_ear = max(0.08, min(0.40, round(self._baseline_abierto * self.K_CERRAR, 3)))
        self._set_slider("sl_umbral", self.p_umbral_ear)

    def _actualizar_baseline(self, ear, ojo_abierto_confiable):
        """Mantiene self._baseline_abierto = EAR típico de ojo abierto del usuario.
        Fase calibración: junta muestras BASELINE_CALIB_S s y toma el percentil 75
        (robusto a algún parpadeo). Fase operación: EMA lento y solo con ojo abierto
        confiable, para no contaminar el baseline con cierres."""
        if not self.baseline_calibrado:
            if self.baseline_calib_inicio is None:
                self.baseline_calib_inicio = time.time()
                self.baseline_muestras = []
            self.baseline_muestras.append(ear)
            if time.time() - self.baseline_calib_inicio >= self.BASELINE_CALIB_S and self.baseline_muestras:
                muestras = sorted(self.baseline_muestras)
                self._baseline_abierto  = muestras[int(len(muestras) * 0.75)]
                self.baseline_calibrado = True
                self._aplicar_umbral_desde_baseline()
                print(f"DEBUG baseline calibrado: {self._baseline_abierto:.3f} "
                      f"→ umbral {self.p_umbral_ear:.3f}")
            return

        if ojo_abierto_confiable and self._baseline_abierto is not None:
            self._baseline_abierto = ((1 - self.BASELINE_EMA) * self._baseline_abierto
                                      + self.BASELINE_EMA * ear)
            self._aplicar_umbral_desde_baseline()

    def _suavizar_puntos(self, puntos_nuevos, atributo, alpha=0.5):
        previos = getattr(self, atributo)
        if previos is None or len(previos) != len(puntos_nuevos):
            suavizados = [(float(x), float(y)) for x, y in puntos_nuevos]
        else:
            suavizados = [
                (alpha * nx + (1 - alpha) * px, alpha * ny + (1 - alpha) * py)
                for (nx, ny), (px, py) in zip(puntos_nuevos, previos)
            ]
        setattr(self, atributo, suavizados)
        return suavizados

    def dibujar_ojo(self, frame, puntos):
        puntos = [(int(x), int(y)) for x, y in puntos]
        for i in range(len(puntos)):
            cv2.line(frame, puntos[i], puntos[(i + 1) % len(puntos)], (0, 255, 0), 1)
        cv2.circle(frame, puntos[0], 3, (0, 255, 255), -1)
        cv2.circle(frame, puntos[3], 3, (0, 255, 255), -1)
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

            # FPS real: cuántos cuadros/segundo procesa realmente el loop. Importa
            # porque a FPS bajo un parpadeo rápido cae en pocos cuadros y su
            # duración medida pierde resolución.
            ahora_fps = time.time()
            if self._fps_t0 is None:
                self._fps_t0 = ahora_fps
            self._fps_n += 1
            if ahora_fps - self._fps_t0 >= 1.0:
                self._fps    = self._fps_n / (ahora_fps - self._fps_t0)
                self._fps_t0 = ahora_fps
                self._fps_n  = 0

            frame_adj = cv2.convertScaleAbs(frame, alpha=self.p_contraste, beta=self.p_brillo)

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
            recorte_cara  = None
            estado_ojo    = "—"

            if resultado.face_landmarks:
                for face_landmarks in resultado.face_landmarks:
                    p_izq = CalculadorEAR.obtener_coordenadas(
                        CalculadorEAR.OJO_IZQUIERDO, face_landmarks, w, h)
                    p_der = CalculadorEAR.obtener_coordenadas(
                        CalculadorEAR.OJO_DERECHO, face_landmarks, w, h)

                    p_izq = self._suavizar_puntos(p_izq, "_ema_izq", alpha=0.8)
                    p_der = self._suavizar_puntos(p_der, "_ema_der", alpha=0.8)

                    ear_izq = CalculadorEAR.calcular_ear_ojo(p_izq)
                    ear_der = CalculadorEAR.calcular_ear_ojo(p_der)
                    ear     = (ear_izq + ear_der) / 2.0
                    self.historico_ear.append(ear)  # memoria cruda, siempre, abierto y cerrado
                    self.ear_buffer.append(ear)
                    ear_suavizado = sum(self.ear_buffer) / len(self.ear_buffer)

                    self.dibujar_ojo(frame, p_izq)
                    self.dibujar_ojo(frame, p_der)

                    nariz_x = int(face_landmarks[1].x * w)
                    nariz_y = int(face_landmarks[1].y * h)
                    if self.nariz_previa is not None:
                        movimiento = math.dist((nariz_x, nariz_y), self.nariz_previa)
                    else:
                        movimiento = 0
                    self.nariz_previa = (nariz_x, nariz_y)

                    # ── Máquina de estados de parpadeo con histéresis ──
                    # Umbrales derivados del baseline de ojo abierto (estable): cerrar
                    # (bajo) y abrir (alto). La banda muerta entre ambos evita el
                    # "chattering" (un mismo parpadeo partido en dos). La duración se
                    # mide en tiempo real (time.time()), no en cuadros, porque el loop
                    # no corre a FPS fijo.
                    asimetria = abs(ear_izq - ear_der)

                    if not self.baseline_calibrado:
                        # Calibración implícita: fijar el baseline con ojos abiertos.
                        self._actualizar_baseline(ear, False)
                        self._actualizar_perclos(False)
                        estado_ojo = "Calibrando... (mantené ojos abiertos)"
                    else:
                        umbral_cerrar = self._baseline_abierto * self.K_CERRAR
                        umbral_abrir  = self._baseline_abierto * self.K_ABRIR
                        # Adaptar baseline solo con ojo abierto confiable (no en cierre).
                        ojo_abierto_confiable = (not self.ojo_cerrado) and (ear > umbral_abrir)
                        self._actualizar_baseline(ear, ojo_abierto_confiable)

                        if not self.ojo_cerrado:
                            self._actualizar_perclos(False)
                            if movimiento > self.umbral_movimiento:
                                estado_ojo = "Moviendo cabeza (ignorado)"
                            elif ear < umbral_cerrar:
                                self.ojo_cerrado          = True
                                self.cierre_inicio        = time.time()
                                self.cierre_fin           = self.cierre_inicio
                                self.asimetria_max_cierre = asimetria
                                estado_ojo = "Cerrando..."
                            else:
                                estado_ojo = "Abierto"
                        else:
                            self._actualizar_perclos(True)
                            self.asimetria_max_cierre = max(self.asimetria_max_cierre, asimetria)
                            # Duración = tiempo de FASE PROFUNDA (EAR bajo umbral_cerrar),
                            # no hasta umbral_abrir: la cola de reapertura inflaba ~2x.
                            if ear < umbral_cerrar:
                                self.cierre_fin = time.time()
                            dur_ms      = (self.cierre_fin - self.cierre_inicio) * 1000 if self.cierre_inicio else 0.0
                            dur_vivo_ms = (time.time() - self.cierre_inicio) * 1000 if self.cierre_inicio else 0.0

                            if dur_vivo_ms > self.EMERGENCIA_MS:
                                estado_ojo = self._resolver_cierre_anomalo(ear, dur_ms, ear_suavizado, frame)
                                self.ojo_cerrado   = False
                                self.cierre_inicio = None
                            elif ear > umbral_abrir:
                                # Reabrió → fin del cierre: clasificar y (si pasó cooldown) registrar.
                                etiqueta, categoria = self._clasificar_cierre(dur_ms, self.asimetria_max_cierre)
                                if time.time() >= self.cooldown_hasta:
                                    self._registrar_cierre(dur_ms, etiqueta, categoria, ear_suavizado, frame)
                                    self.cooldown_hasta = time.time() + (self.p_cooldown / self.FPS_REFERENCIA)
                                else:
                                    print(f"DEBUG bloqueado por cooldown: {dur_ms:.0f} ms")
                                self.ojo_cerrado   = False
                                self.cierre_inicio = None
                                estado_ojo = "Abierto"
                            else:
                                estado_ojo = "Cerrado..."

                    self.label_estado_ojo.configure(text=f"Ojo:              {estado_ojo}")

                    # Recorte a la cara (para mostrar en pantalla y para medir
                    # brillo/contraste en el auto-ajuste de imagen; no afecta detección)
                    xs = [int(lm.x * w) for lm in face_landmarks]
                    ys = [int(lm.y * h) for lm in face_landmarks]
                    x1 = max(0, min(xs) - 80);  y1 = max(0, min(ys) - 120)
                    x2 = min(w, max(xs) + 80);  y2 = min(h, max(ys) + 120)
                    if x2 > x1 and y2 > y1:
                        recorte_cara = (x1, y1, x2, y2)

                    self._procesar_auto_calibracion(ear, frame, recorte_cara)
            else:
                self.label_estado_ojo.configure(text="Ojo:              sin rostro")
                self._ema_izq = None
                self._ema_der = None
                self.nariz_previa = None
                self.ojo_cerrado = False
                self.cierre_inicio = None
                self.cierre_fin = None
                self._ultimo_ts_perclos = None

            # Marco verde + etiqueta sobre la cara (frame completo, con contexto).
            if recorte_cara:
                x1, y1, x2, y2 = recorte_cara
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                if self.guia_activa:
                    etiqueta = self.GUIA_FASES[self.guia_fase_idx][0]  # letra de fase
                else:
                    etiqueta = estado_ojo.split()[0]
                cv2.putText(frame, etiqueta, (x1, max(24, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            frame_mostrar = self._ajustar_a_marco(frame, 640, 480)

            self.label_ear.configure(text=f"EAR:              {ear_suavizado:.3f}")
            self.label_parpadeos.configure(text=f"Parpadeos:        {self.total_parpadeos}")
            self.label_prolongados.configure(text=f"Prolongados:      {self.total_prolongados}")
            self.label_falsos.configure(text=f"Falsos descart.:  {self.total_falsos}")
            self.label_fps.configure(text=f"FPS:              {self._fps:.0f}")
            self.actualizar_frecuencia()

            if self.guia_activa:
                self._procesar_prueba_guiada()
            if self.guia_activa:  # sigue activa (no finalizó recién)
                self._dibujar_overlay_guia(frame_mostrar)
            elif self.calib_fase in (1, 2, 3):
                msgs = {1: "AJUSTANDO IMAGEN", 2: "OJOS ABIERTOS", 3: "PARPADEA NORMAL"}
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
# EJECUCIÓN (con depuración)
# ==========================================
if __name__ == "__main__":
    print("DEBUG: Inicio de la aplicación.")
    try:
        # --- 1. Obtener usuario de Windows ---
        usuario_windows = GestorAutenticacionWindows.usuario_actual()
        print(f"DEBUG: Usuario Windows detectado: {usuario_windows}")

        # --- 2. Mostrar ventana de login como raíz ---
        print("DEBUG: Creando ventana de login...")
        login_root = ctk.CTk()  # ventana temporal oculta
        login_root.withdraw()   # la ocultamos inmediatamente
        login = VentanaLogin(login_root, usuario_windows)
        login_root.wait_window(login)

        if not login.resultado_ok:
            print("DEBUG: Login cancelado, saliendo.")
            login_root.destroy()
            sys.exit(0)

        login_root.destroy()  # destruir la ventana oculta
        print("DEBUG: Login aceptado, lanzando InterfazFatiga...")

        # --- 3. Crear la aplicación principal ---
        app = InterfazFatiga(usuario_windows)
        print("DEBUG: Instancia creada, configurando protocolo de cierre...")
        app.protocol("WM_DELETE_WINDOW", app.on_closing)
        print("DEBUG: Entrando en mainloop...")
        app.mainloop()
        print("DEBUG: mainloop finalizado.")
    except Exception as e:
        print("ERROR CAPTURADO:")
        traceback.print_exc()
        with open("error_log.txt", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print("Se ha guardado el error en 'error_log.txt'.")
        sys.exit(1)