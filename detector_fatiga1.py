#from curses.panel import panel
import traceback  # para depuración
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import math
import statistics
import hashlib
import asyncio
import threading
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
import win32security
import winreg
from PIL import Image, ImageTk, ImageOps
import os
from datetime import datetime

# Windows Hello (pywinrt). Import opcional: si falta el paquete o falla,
# la app sigue funcionando con el flujo sin verificación biométrica.
try:
    import winrt.windows.security.credentials.ui as winrt_ui
    HELLO_IMPORTADO = True
except Exception:
    winrt_ui = None
    HELLO_IMPORTADO = False

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

def _dir_recursos():
    """Carpeta de recursos empaquetados de solo-lectura (modelo, assets).
    En el .exe de PyInstaller apunta al bundle; con `python`, a la del script."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _dir_datos():
    """Carpeta donde la app ESCRIBE (base de datos, clave). Junto al .exe
    cuando está compilado; junto al script cuando corre con `python`."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


MODEL_URL  = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
MODEL_PATH = os.path.join(_dir_recursos(), "face_landmarker.task")
KEY_PATH   = os.path.join(_dir_datos(), "secret.key")

# Recursos gráficos (logo Argos). Generados por generar_assets.py desde Ojo.svg.
ASSETS_DIR = os.path.join(_dir_recursos(), "assets")
ICON_PATH  = os.path.join(ASSETS_DIR, "logo_ojo.ico")
LOGO_PATH  = os.path.join(ASSETS_DIR, "logo_ojo.png")
SPLASH_LOGO_PATH = os.path.join(ASSETS_DIR, "argos_logo_transparente.png")
SPLASH_BG_PATH = os.path.join(ASSETS_DIR, "menu_inicial.png")


def aplicar_icono(ventana):
    """Aplica el ícono del ojo a una ventana. Reintenta con after() porque en
    los Toplevel de customtkinter el ícono a veces no toma en el primer intento."""
    if not os.path.exists(ICON_PATH):
        return
    def _set():
        try:
            ventana.iconbitmap(ICON_PATH)
        except Exception:
            pass
    _set()
    try:
        ventana.after(300, _set)
    except Exception:
        pass


def cargar_logo(size):
    """Devuelve un CTkImage del logo, o None si falta el archivo."""
    try:
        return ctk.CTkImage(Image.open(LOGO_PATH), size=size)
    except Exception:
        return None


def cargar_icono(nombre, size):
    """Devuelve un CTkImage de assets/<nombre>.png, o None si falta.
    Íconos dibujados (generar_assets.py), no emojis: evita el rendering
    roto de emoji en Tkinter/Windows (ej. 🚪 mostraba un glifo irreconocible)."""
    try:
        ruta = os.path.join(ASSETS_DIR, f"{nombre}.png")
        return ctk.CTkImage(Image.open(ruta), size=size)
    except Exception:
        return None

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

    # ── Windows Hello (PIN / huella / rostro) ────────
    # UserConsentVerifier solo puede verificar al usuario de la SESIÓN actual
    # de Windows; los demás perfiles de la app usan PIN propio hasheado.
    @staticmethod
    def hello_disponible():
        if not HELLO_IMPORTADO:
            return False
        try:
            avail = asyncio.run(winrt_ui.UserConsentVerifier.check_availability_async())
            return int(avail) == 0  # 0 = Available
        except Exception:
            return False

    @staticmethod
    def verificar_hello(mensaje="Confirmá tu identidad"):
        """Muestra el diálogo nativo de Windows Hello. True solo si Verified."""
        try:
            resultado = asyncio.run(asyncio.wait_for(
                winrt_ui.UserConsentVerifier.request_verification_async(mensaje),
                timeout=120))
            return int(resultado) == 0  # 0 = Verified
        except Exception:
            return False

    # ── Fallbacks cuando no hay Windows Hello ────────
    @staticmethod
    def es_cuenta_microsoft(usuario=None):
        """True si la sesión actual está vinculada a una cuenta Microsoft (MSA).
        Lee HKCU\\...\\IdentityCRL\\UserExtendedProperties (una subclave por MSA
        vinculada). Solo es válido para el usuario de la sesión actual, que es
        exactamente el único perfil 'windows' de la app. Si no se puede leer,
        se asume cuenta local clásica."""
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\IdentityCRL\UserExtendedProperties")
            subclaves = winreg.QueryInfoKey(k)[0]
            winreg.CloseKey(k)
            return subclaves > 0
        except OSError:
            return False

    @staticmethod
    def validar_password_local(usuario, password):
        """Valida la contraseña de Windows de una cuenta LOCAL con LogonUser.
        (Para cuentas Microsoft no funciona: Windows no expone hash validable.)"""
        for dominio in (".", win32api.GetComputerName()):
            try:
                token = win32security.LogonUser(
                    usuario, dominio, password,
                    win32security.LOGON32_LOGON_INTERACTIVE,
                    win32security.LOGON32_PROVIDER_DEFAULT)
                token.Close()
                return True
            except win32security.error:
                continue
        return False


# ==========================================
# 0.2 HASH DE PIN DE PERFILES (PBKDF2-SHA256)
# ==========================================
class GestorPin:
    ITERACIONES = 200_000

    @classmethod
    def hashear(cls, pin: str) -> str:
        salt = os.urandom(16)
        h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, cls.ITERACIONES)
        return f"{salt.hex()}${h.hex()}"

    @classmethod
    def verificar(cls, pin: str, almacenado: str) -> bool:
        try:
            salt_hex, hash_hex = almacenado.split("$")
            h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), cls.ITERACIONES)
            return h.hex() == hash_hex
        except Exception:
            return False

# ==========================================
# 1. GESTOR DE BASE DE DATOS
# ==========================================
class GestorBD:
    def __init__(self, db_name=None):
        if db_name is None:
            db_name = os.path.join(_dir_datos(), "fatiga_ocular.db")
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
        # Perfiles: 'windows' = cuenta de la sesión (entra con Windows Hello);
        # 'perfil' = perfil interno estilo Netflix (PIN propio opcional, hasheado)
        try:
            self.cursor.execute("ALTER TABLE usuarios ADD COLUMN tipo TEXT NOT NULL DEFAULT 'perfil'")
        except sqlite3.OperationalError:
            pass
        try:
            self.cursor.execute("ALTER TABLE usuarios ADD COLUMN pin_hash TEXT")
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

    # ── Perfiles (login) ─────────────────────────────
    def obtener_perfiles(self):
        self.cursor.execute(
            "SELECT id, nombre, rol, tipo, pin_hash FROM usuarios ORDER BY tipo DESC, nombre")
        return self.cursor.fetchall()

    def asegurar_usuario_windows(self, nombre):
        """El usuario de la sesión de Windows siempre existe, con tipo 'windows'
        y rol Administrador (primera cuenta = administrador)."""
        self.cursor.execute("SELECT id FROM usuarios WHERE nombre = ?", (nombre,))
        fila = self.cursor.fetchone()
        if fila:
            self.cursor.execute(
                "UPDATE usuarios SET tipo='windows', rol='Administrador' WHERE id = ?", (fila[0],))
            self.conn.commit()
            return fila[0]
        self.cursor.execute(
            "INSERT INTO usuarios (nombre, rol, tipo) VALUES (?, 'Administrador', 'windows')",
            (nombre,))
        self.conn.commit()
        return self.cursor.lastrowid

    def crear_perfil(self, nombre, pin=None):
        """Crea un perfil interno (estilo Netflix). PIN opcional, guardado hasheado.
        Devuelve el id, o None si el nombre ya existe."""
        pin_hash = GestorPin.hashear(pin) if pin else None
        try:
            self.cursor.execute(
                "INSERT INTO usuarios (nombre, rol, tipo, pin_hash) VALUES (?, 'Usuario', 'perfil', ?)",
                (nombre, pin_hash))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            return None

    def establecer_pin(self, usuario_id, pin):
        self.cursor.execute("UPDATE usuarios SET pin_hash = ? WHERE id = ?",
                            (GestorPin.hashear(pin), usuario_id))
        self.conn.commit()

    def verificar_pin_perfil(self, usuario_id, pin):
        self.cursor.execute("SELECT pin_hash FROM usuarios WHERE id = ?", (usuario_id,))
        fila = self.cursor.fetchone()
        if not fila or not fila[0]:
            return True  # perfil sin PIN: entra directo
        return GestorPin.verificar(pin or "", fila[0])

    def _migrar_datos_existentes(self):
        """Cifra registros heredados en texto plano. Corre UNA sola vez: una
        marca en la tabla meta evita re-escanear la BD en cada arranque.
        (El chequeo anterior por prefijo 'gAAAAA' era de tokens Fernet; con
        AES-GCM nunca coincidía y re-cifraba TODO en capas anidadas en cada
        arranque — así se infló la BD a GB y se colgaba el inicio.)"""
        self.cursor.execute(
            "CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT)")
        self.cursor.execute("SELECT valor FROM meta WHERE clave = 'migracion_cifrado'")
        if self.cursor.fetchone():
            return

        self.cursor.execute("SELECT id, fecha_hora, ear_registrado FROM registro_parpadeos")
        for id_, fecha, ear in self.cursor.fetchall():
            fecha_s, ear_s = str(fecha), str(ear)
            # Ya cifrado si descifrar() lo transforma (ante fallo devuelve el
            # valor intacto → valor intacto = texto plano heredado).
            if self.cifrado.descifrar(fecha_s) == fecha_s:
                self.cursor.execute(
                    "UPDATE registro_parpadeos SET fecha_hora=?, ear_registrado=? WHERE id=?",
                    (self.cifrado.cifrar(fecha_s), self.cifrado.cifrar(ear_s), id_)
                )
        self.cursor.execute(
            "INSERT INTO meta (clave, valor) VALUES ('migracion_cifrado', 'ok')")
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
# 2.5 PANTALLA DE CARGA (splash con ojo que parpadea)
# ==========================================
class VentanaCarga(ctk.CTkToplevel):
    """Splash inicial: el ojo de Argos parpadea mientras se prepara el sistema.
    Sin bordes, centrado, se cierra solo tras unos segundos."""

    DURACION_MS = 2800

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(fg_color="#050B12")

        w, h = 380, 340
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        try:
            self.attributes("-topmost", True)
        except Exception:
            pass

        # Fondo del Splash
        try:
            self.splash_bg = ctk.CTkImage(
                Image.open(SPLASH_BG_PATH),
                size=(w, h)
            )
        except Exception:
            self.splash_bg = None

        self.lbl_fondo = ctk.CTkLabel(
            self,
            text="",
            image=self.splash_bg
        )
        self.lbl_fondo.place(x=0, y=0, relwidth=1, relheight=1)
        self.lbl_fondo.lower()

  #===============================================================================================
  #===============================================================================================

        # Frames de parpadeo - Antiguo Splash
        """self._frames = []
        for nombre in ("ojo_abierto.png", "ojo_semi.png", "ojo_cerrado.png", "ojo_semi.png"):
            try:
                self._frames.append(
                    ctk.CTkImage(Image.open(os.path.join(ASSETS_DIR, nombre)), size=(120, 120)))
            except Exception:
                pass

        self.lbl_ojo = ctk.CTkLabel(self, text="", image=self._frames[0] if self._frames else None)
        self.lbl_ojo.pack(pady=(48, 14))"""
        
        try:
            self.logo_splash = ctk.CTkImage(
                Image.open(SPLASH_LOGO_PATH),
                size=(150, 150)
        )
        except Exception:
            self.logo_splash = None

        self.lbl_ojo = ctk.CTkLabel(
            self,
            text="",
            image=self.logo_splash
        )
        self.lbl_ojo.pack(pady=(10,8))
        
  #===============================================================================================
  #===============================================================================================

        
        ctk.CTkLabel(self, text="A R G O S",
                     font=ctk.CTkFont(family="Agency FB",size=38, weight="bold")).pack(pady=(0, 12))
        
        ctk.CTkLabel(self, 
                    text="Monitor de Fatiga Visual",
                    text_color="#8A93A8",
                    font=ctk.CTkFont(
                        family="Agency FB",
                        size=20,
                        weight="normal"
                    )
                ).pack(pady=(2, 18))
        

        self.lbl_log = ctk.CTkLabel(self, text="Iniciando…", text_color="#8A93A8",
                                    font=ctk.CTkFont(family="Consolas",
                                                            size=14,
                                                            weight="normal"))
        self.lbl_log.pack()

 
 #==================================================================
#==================================================================       
        """self._i = 0
        self._vivo = True
        if self._frames:
            self._animar()          -------------------> Del antiguo Splash
        self._paso_log(0)
        self.after(self.DURACION_MS, self._cerrar)
        self.lift()"""
        
        self._vivo = True
        self._paso_log(0)
        self.after(self.DURACION_MS, self._cerrar)
        self.lift()
        
#==================================================================
#==================================================================
    """def _animar(self):
        if not self._vivo:
            return
        self.lbl_ojo.configure(image=self._frames[self._i % len(self._frames)])
        self._i += 1
        self.after(240, self._animar)"""

    def _paso_log(self, k):
        msgs = ["Cargando modelo FaceLandmarker…", "Iniciando MediaPipe…",
                "Preparando base de datos…", "Listo."]
        if self._vivo and k < len(msgs):
            self.lbl_log.configure(text=msgs[k])
            self.after(650, lambda: self._paso_log(k + 1))

    def _cerrar(self):
        self._vivo = False
        self.destroy()

# ==========================================
# 3.0 DIÁLOGO DE SECRETO (PIN / contraseña, entrada enmascarada)
# ==========================================
class DialogoSecreto(ctk.CTkToplevel):
    """Pide un valor secreto con entrada enmascarada. Resultado en .valor
    (None si se cancela)."""

    def __init__(self, parent, titulo, mensaje):
        super().__init__(parent)
        self.configure(fg_color="#050B12")
        self.title(titulo)
        self.geometry("360x180")
        self.resizable(False, False)
        self.valor = None
        self.protocol("WM_DELETE_WINDOW", self._cancelar)

        ctk.CTkLabel(self, text=mensaje, wraplength=320).pack(pady=(20, 8))
        self.entry = ctk.CTkEntry(self, show="•", width=240)
        self.entry.pack(pady=4)
        self.entry.bind("<Return>", lambda e: self._aceptar())

        fr = ctk.CTkFrame(self, fg_color="transparent")
        fr.pack(pady=12)
        ctk.CTkButton(fr, text="Aceptar", width=100, command=self._aceptar).pack(side="left", padx=6)
        ctk.CTkButton(fr, text="Cancelar", width=100, fg_color="#555", hover_color="#666",
                      command=self._cancelar).pack(side="left", padx=6)

        self.lift()
        self.grab_set()
        self.entry.focus()

    def _aceptar(self):
        self.valor = self.entry.get()
        self.grab_release()
        self.destroy()

    def _cancelar(self):
        self.valor = None
        self.grab_release()
        self.destroy()

# ==========================================
# 3.1 VENTANA DE LOGIN (perfiles + Windows Hello)
# ==========================================
class VentanaLogin(ctk.CTkToplevel):
    """Selector de perfiles estilo Netflix.
    - Perfil 'windows' (cuenta de la sesión) = Administrador; entra verificando
      identidad con Windows Hello (PIN/huella/rostro del propio Windows).
    - Perfiles internos: PIN propio opcional (hasheado con PBKDF2)."""

    def __init__(self, parent, bd, usuario_windows):
        super().__init__(parent)
        self.configure(fg_color="#050B12")
        self.title("Iniciar sesión")
        #self.state("zoomed")
        self.geometry("480x560")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancelar)

        self.bd               = bd
        self.usuario_windows  = usuario_windows
        self.resultado_ok     = False
        self.perfil_id        = None
        self.perfil_nombre    = None
        self.perfil_rol       = "Usuario"
        self.hello_disponible = GestorAutenticacionWindows.hello_disponible()

        # La cuenta de la sesión de Windows siempre existe como Administrador
        self.bd.asegurar_usuario_windows(usuario_windows)
        aplicar_icono(self)


        self._logo = ctk.CTkImage(
            light_image=Image.open(
                os.path.join(ASSETS_DIR, "argos_logo_transparente.png")
            ),
            dark_image=Image.open(
                os.path.join(ASSETS_DIR, "argos_logo_transparente.png")
            ),
        size=(180, 180)
   )
        
        
        if self._logo:
            ctk.CTkLabel(self, text="", image=self._logo).pack(pady=(20, 2))
        
        self.titulo_argos = ctk.CTkLabel(
            self,
            text="A  R  G  O  S",
            font=ctk.CTkFont(
                family="Agency FB",
                size=38,
                weight="bold"
            ),
            text_color="#E8EDF2"
        )

        self.titulo_argos.pack(
            pady=(2 if self._logo else 20, 0)
        )

        self.linea_argos = ctk.CTkFrame(
            self,
            height=2,
            width=150,
            fg_color="#1B526F"
        )

        self.linea_argos.pack(
            pady=(3, 4)
        )
        
        

        ctk.CTkLabel(
                self,
                text="¿Quién está usando el sistema?",
                font=ctk.CTkFont(
                    family="Agency FB",
                    size=20,
                    weight="bold"
                )
            ).pack(pady=(8, 4))
        
        
        subtitulo = ("Cuenta de Windows protegida con Windows Hello"
                     if self.hello_disponible else
                     "Sin Windows Hello: contraseña de Windows (local) o PIN de app")
        
        ctk.CTkLabel(
            self,
            text=subtitulo,
            text_color="#8A93A8",
            font=ctk.CTkFont(
                family="Consolas",
                size=13
            )
        ).pack(pady=(0, 10))

        self.label_error = ctk.CTkLabel(
            self,
            text="",
            text_color="#ff6060",
            font=ctk.CTkFont(
                family="Agency FB",
                size=15,
                weight="bold"
            )
        )
        self.label_error.pack(pady=(0, 2))

        self.lista = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.lista.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.lista.grid_columnconfigure((0, 1), weight=1)
        self._armar_lista()

        ctk.CTkButton(
            self,
            text="Salir",
            fg_color="transparent",
            border_width=1,
            font=ctk.CTkFont(
                family="Agency FB",
                size=17
            ),
            command=self._cancelar
        ).pack(padx=18, pady=(0, 14), fill="x")
        self.lift()
        self.grab_set()

    # ── Lista de perfiles (tarjetas estilo Netflix) ──
    def _armar_lista(self):
        for w in self.lista.winfo_children():
            w.destroy()
        COLS = 2
        perfiles = self.bd.obtener_perfiles()
        for idx, (uid, nombre, rol, tipo, pin_hash) in enumerate(perfiles):
            if tipo == "windows":
                detalle = f"{rol} · Windows Hello" if self.hello_disponible else rol
                color_avatar = "#1f6a5f"
            else:
                detalle = f"{rol} · con PIN" if pin_hash else rol
                color_avatar = "#3a3a3a"
            iniciales = "".join(p[0] for p in nombre.split()[:2]).upper() or "?"

            card = ctk.CTkFrame(
                self.lista,
                corner_radius=10,
                fg_color="transparent"
            )
            card.grid(
                row=idx // COLS,
                column=idx % COLS,
                padx=6,
                pady=6,
                sticky="nsew"
            )

            avatar = ctk.CTkFrame(card, width=64, height=64, corner_radius=32,
                                   fg_color=color_avatar)
            avatar.pack(pady=(16, 8))
            avatar.pack_propagate(False)
            
            
            ctk.CTkLabel(
                avatar,
                text=iniciales,
                font=ctk.CTkFont(
                    family="Agency FB",
                    size=20,
                    weight="bold"
                )
            ).pack(expand=True)


            ctk.CTkLabel(
                card,   
                text=nombre,
                font=ctk.CTkFont(
                    family="Agency FB",
                    size=17,
                    weight="bold"
                ),
                wraplength=150
            ).pack(padx=10)
            
            
            ctk.CTkLabel(
                card,
                text=detalle,
                text_color="#8A93A8",
                font=ctk.CTkFont(
                    family="Agency FB",
                    size=16
                ),
                wraplength=150,
                justify="center"
            ).pack(padx=10, pady=(0, 10))
            
            ctk.CTkButton(
                card,
                text="Entrar",
                width=110,
                font=ctk.CTkFont(
                    family="Agency FB",
                    size=17
                ),
                command=lambda u=uid, n=nombre, r=rol, t=tipo, p=pin_hash:
                    self._entrar(u, n, r, t, p)
            ).pack(pady=(0, 14))

        # Tarjeta "+ Crear perfil" al final de la grilla
        idx_add = len(perfiles)
        card_add = ctk.CTkFrame(self.lista, corner_radius=10, border_width=1,
                                border_color="#444", fg_color="transparent")
        card_add.grid(row=idx_add // COLS, column=idx_add % COLS, padx=6, pady=6, sticky="nsew")
        avatar_add = ctk.CTkFrame(card_add, width=64, height=64, corner_radius=32,
                                   fg_color="transparent", border_width=1, border_color="#555")
        avatar_add.pack(pady=(16, 8))
        avatar_add.pack_propagate(False)
        ctk.CTkLabel(avatar_add, text="+", text_color="gray",
                     font=ctk.CTkFont(size=22)).pack(expand=True)
        
        
        ctk.CTkLabel(
            card_add,
            text="Crear perfil",
            text_color="#8A93A8",
            font=ctk.CTkFont(
                family="Agency FB",
                size=15
            )
        ).pack(padx=10, pady=(0, 14))
        
        card_add.bind("<Button-1>", lambda e: self._crear_perfil())
        avatar_add.bind("<Button-1>", lambda e: self._crear_perfil())
        for child in card_add.winfo_children():
            child.bind("<Button-1>", lambda e: self._crear_perfil())

    # ── Entradas ─────────────────────────────────────
    def _pedir_secreto(self, titulo, mensaje):
        d = DialogoSecreto(self, titulo, mensaje)
        self.wait_window(d)
        self.grab_set()  # recuperar el foco modal del login
        return d.valor

    def _entrar(self, uid, nombre, rol, tipo, pin_hash):
        if getattr(self, "_verificando_hello", False):
            return  # ya hay una verificación en curso
        self.label_error.configure(text="")
        if tipo == "windows":
            # Cadena de verificación de la cuenta de Windows:
            #   1) Windows Hello (PIN/huella/cara)   — si está configurado
            #   2) contraseña de Windows (LogonUser) — cuenta local sin Hello
            #   3) PIN de app (PBKDF2)               — cuenta Microsoft sin Hello
            if self.hello_disponible:
                # En un hilo aparte: asyncio.run() dentro del callback de Tk
                # congelaba el mainloop (y el diálogo de Hello no tomaba foco).
                self._verificando_hello = True
                self._hello_resultado   = None
                self.label_error.configure(text_color="#ffcc00",
                                           text="Verificando con Windows Hello...")
                threading.Thread(
                    target=self._hello_worker,
                    args=(f"Confirmá tu identidad para entrar como {nombre}",),
                    daemon=True).start()
                self._esperar_hello(uid, nombre, rol)
                return
            elif not GestorAutenticacionWindows.es_cuenta_microsoft(nombre):
                pwd = self._pedir_secreto("Contraseña de Windows",
                                          f"Contraseña de Windows de {nombre}:")
                if pwd is None:
                    return
                if not GestorAutenticacionWindows.validar_password_local(nombre, pwd):
                    self.label_error.configure(text="Contraseña de Windows incorrecta.")
                    return
            else:
                if pin_hash:
                    pin = self._pedir_secreto("PIN de la aplicación",
                                              f"PIN de la aplicación de {nombre}:")
                    if pin is None:
                        return
                    if not self.bd.verificar_pin_perfil(uid, pin):
                        self.label_error.configure(text="PIN incorrecto.")
                        return
                else:
                    # Primera vez: crear el PIN de app (cuenta Microsoft sin Hello)
                    pin = self._pedir_secreto("Crear PIN",
                                              "Sin Windows Hello disponible: creá un PIN "
                                              "para proteger esta cuenta (primera vez).")
                    if not pin:
                        self.label_error.configure(text="Se necesita un PIN para continuar.")
                        return
                    pin2 = self._pedir_secreto("Confirmar PIN", "Repetí el PIN:")
                    if pin != pin2:
                        self.label_error.configure(text="Los PIN no coinciden.")
                        return
                    self.bd.establecer_pin(uid, pin)
            self._aceptar(uid, nombre, rol)
        else:
            if pin_hash:
                pin = self._pedir_secreto("PIN del perfil", f"PIN del perfil {nombre}:")
                if pin is None:
                    return
                if not self.bd.verificar_pin_perfil(uid, pin):
                    self.label_error.configure(text="PIN incorrecto.")
                    return
            self._aceptar(uid, nombre, rol)

    def _hello_worker(self, mensaje):
        self._hello_resultado = GestorAutenticacionWindows.verificar_hello(mensaje)

    def _esperar_hello(self, uid, nombre, rol):
        """Espera el resultado del hilo de Hello sin bloquear el mainloop."""
        if self._hello_resultado is None:
            self.after(100, lambda: self._esperar_hello(uid, nombre, rol))
            return
        ok = self._hello_resultado
        self._verificando_hello = False
        self.label_error.configure(text_color="#ff6060", text="")
        if ok:
            self._aceptar(uid, nombre, rol)
        else:
            self.label_error.configure(text="Verificación de Windows Hello fallida.")

    def _crear_perfil(self):
        self.label_error.configure(text="")
        d = ctk.CTkInputDialog(text="Nombre del nuevo perfil:", title="Crear perfil")
        nombre = (d.get_input() or "").strip()
        self.grab_set()
        if not nombre:
            return
        pin = (self._pedir_secreto("PIN del perfil",
                                   "PIN para el perfil (vacío = sin PIN):") or "").strip()
        nuevo_id = self.bd.crear_perfil(nombre, pin if pin else None)
        if nuevo_id is None:
            self.label_error.configure(text=f"Ya existe un perfil llamado '{nombre}'.")
            return
        self._armar_lista()

    def _aceptar(self, uid, nombre, rol):
        self.resultado_ok  = True
        self.perfil_id     = uid
        self.perfil_nombre = nombre
        self.perfil_rol    = rol
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
        aplicar_icono(self)
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
# 3.4 VENTANA DE RESUMEN DE LA PRUEBA GUIADA (validación)
# ==========================================
class VentanaResumenPrueba(ctk.CTkToplevel):
    """Muestra, tras la prueba guiada, lo que el usuario debía hacer (esperado)
    contra lo que el sistema detectó (real) por fase. Evidencia de validación."""

    def __init__(self, parent, fases, conteos):
        super().__init__(parent)
        self.title("Resumen de la prueba guiada")
        aplicar_icono(self)
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

#=================================================
# ================================================
# Clase del Menu Principal
#=================================================
#===============================================
#=================================================

class MenuPrincipal(ctk.CTk):
    
    def __init__(self, perfil_nombre, perfil_id, perfil_rol, bd):
        super().__init__()
        
        self.configure(fg_color="#050B12")
        
        ruta_fondo = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "assets",
            "menu_inicial.png"
        )
#================================================================   
        self.imagen_fondo_original = Image.open(ruta_fondo)

        ancho = self.winfo_screenwidth()
        alto = self.winfo_screenheight()

        imagen_ajustada = ImageOps.fit(
            self.imagen_fondo_original,
            (ancho, alto),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5)
        )

        self.imagen_fondo = ctk.CTkImage(
            light_image=imagen_ajustada,
            dark_image=imagen_ajustada,
            size=(ancho, alto)  
        )
        
        # ================================================================
# Mostrar fondo
# ================================================================

        self.fondo_menu = ctk.CTkLabel(
            self,
            text="",
            image=self.imagen_fondo,
            fg_color="transparent"
        )

        self.fondo_menu.place(
            relx=0,
            rely=0,
            relwidth=1,
            relheight=1
        )

        self.fondo_menu.lower()

# ================================================================
        
        #===================================================================    
        self.perfil_nombre = perfil_nombre
        self.perfil_id = perfil_id
        self.perfil_rol = perfil_rol
        self.bd = bd
        
        self.cerrar_sesion_solicitado = False # Nuevo 

        self.title("ARGOS")
        self.after(100, self._maximizar)
        

        aplicar_icono(self)


        """# Zona de navegación izquierda
        self.panel_navegacion = ctk.CTkFrame(
            self, 
            fg_color ="transparent"
        )
        
        self.panel_navegacion.pack(
            side="left",
            fill="y",
            padx=30,
            pady=30
        )
        
        self.contenedor_botones = ctk.CTkFrame(
            self.panel_navegacion,
            fg_color="#D0D5DA"
        )                                                   # ANTIGUO FONDO DE BOTONES

        self.contenedor_botones.pack(
            expand=True
        )"""
        
    #=====================================================================
        # Zona - Botones ==================================================
    #=====================================================================
    
        self.titulo_argos = ctk.CTkLabel(
            self,
            text="A  R  G  O  S",
            font=("Agency FB", 52),
            text_color="#E8EDF2",
            fg_color="transparent"
        )
        self.titulo_argos.place(
            x=195,
            y=125,
            anchor="center"
        )

        self.titulo_argos.lift()
        
        self.linea_argos = ctk.CTkFrame(
            self,
            height=2,
            width=180,
            fg_color="#1B526F"
        )

        self.linea_argos.place(
            x=195,
            y=180,
            anchor="center"
        )
        
        self.linea_argos.lift()
# ========================================Fecha y Hora ==================================================================       
       
        self.lbl_fecha = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(
                family="Consolas",
                size=13,
                weight="normal"
            ),
            text_color="#AEB8C2",
            fg_color="transparent",
            justify="right"
        )

        self.lbl_fecha.place(
            relx=0.94,
            y=55,
            anchor="ne"
        )
        
        
        self.lbl_hora = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(
                family="Consolas",
                size=13,
                weight="normal"
            ),
            text_color="#AEB8C2",
            fg_color="transparent",
            justify="right"
        )

        self.lbl_hora.place(
            relx=0.94,
            y=78,
            anchor="ne"
        )
        
        self._actualizar_fecha_hora()
        
# Fin Fecha y Hora ==================================================================

        """self.titulo_argos.place(
            relx=70,
            y=45,
            anchor="center"
        )"""

        ctk.CTkButton(
            self,
            text="M O N I T O R E O",
            width=250,
            font=ctk.CTkFont(
                family="Agency FB",
                size=18,
                weight="normal"
            ),
            
            fg_color="transparent",
            hover_color="#10283A",
            text_color="#C8D0D8",
            corner_radius=0,
            command=self.abrir_monitoreo
        ).place(
            x=70,
            y=260
        )
        
       
       #=====================================================================
        
        ctk.CTkButton(
            self,
            text="E S T A D I S T I C A S",
            width=250,
            
            font=ctk.CTkFont(
                family="Agency FB",
                size=18,
                weight="normal"
            ),
            fg_color="transparent",
            hover_color="#10283A",
            text_color="#C8D0D8",
            corner_radius=0,
         ).place(
            x=70,
            y=310
        )
        

        ctk.CTkButton(
            self,
            text="E S T A D.  T O T A L E S",
            width=250,
            font=ctk.CTkFont(
                family="Agency FB",
                size=18,
                weight="normal"
            ),
            fg_color="transparent",
            hover_color="#10283A",
            text_color="#C8D0D8",
            corner_radius=0
        ).place(
            x=70,
            y=360
        )

        
        ctk.CTkButton(
            self,
            text="U S U A R I O S",
            width=250,
            font=ctk.CTkFont(
                family="Agency FB",
                size=18,
                weight="normal"
            ),
            fg_color="transparent",
            hover_color="#10283A",
            text_color="#C8D0D8",
            corner_radius=0,
        ).place(
            x=70,
            y=410
        )
        
        ctk.CTkButton(
            self,
            text="A C E R C A  D E",
            width=250,
            font=ctk.CTkFont(
                family="Agency FB",
                size=18,
                weight="normal"
            ),
            fg_color="transparent",
            hover_color="#10283A",
            text_color="#C8D0D8",
            corner_radius=0,
            command=self.mostrar_about
        ).place(
            x=70,
            y=460
        )
#================================================================================================================
#==========================================================
# Comtenido en pantalla
#===========================================================
#==========================================================
        """# Área principal de contenido
        self.area_contenido = ctk.CTkFrame(
            self,
            fg_color="#E1E5E8"
        )

        self.area_contenido.pack(                                       VIEJA AREA DE CONTENIDO
            side="left",
            fill="both",
            expand=True,
            padx=30,
            pady=30
        )"""
        
        self.vista_about = ctk.CTkFrame(
            self,
            fg_color="transparent"
        )
        
        self._construir_vista_about(self.vista_about)
        
    # Informacion del sitema 
            
        self.lbl_sistema = ctk.CTkLabel(
            self,
            text="●  ARGOS OS v1.0.0",
            font=ctk.CTkFont(
                family="Consolas",
                size=11,
                weight="normal"
            ),
            text_color="#5F7180",
            fg_color="transparent"
        )
    
        self.lbl_sistema.place( 
            relx=0.05,
            rely=0.95,
            anchor="sw"
        )
    #Fin Informacion del sistema
    
        self.lbl_fecha.lift()
        self.lbl_hora.lift()
#============================= Actualizar fecha y hora =============================================================================
    def _actualizar_fecha_hora(self):
        ahora = datetime.now()

        self.lbl_fecha.configure(
            text=ahora.strftime("%d / %m / %Y")
        )

        self.lbl_hora.configure(
            text=ahora.strftime("%H : %M : %S")
        )

        self.after(1000, self._actualizar_fecha_hora)   
    
#============================= Fin Actualizar fecha y hora =======================================================
    
    def _construir_vista_about(self, tab):
        ctk.CTkLabel(
            tab,
            text="ARGOS",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(0, 0))

        ctk.CTkLabel(
            tab,
            text="Argos Panoptes — El gigante que todo lo ve",
            text_color="gray",
            font=ctk.CTkFont(size=12)
        ).pack(pady=(0, 12))

        tabs = ctk.CTkTabview(tab)
        tabs.pack(fill="both", expand=True)

        tabs.add("¿Por qué Argos?")
        tabs.add("El sistema")
        tabs.add("Creadores")

        self._about_por_que(tabs.tab("¿Por qué Argos?"))
        self._about_sistema(tabs.tab("El sistema"))
        self._about_creadores(tabs.tab("Creadores"))


    def _about_por_que(self, tab):
        texto = (
            "En la mitología griega, Argos Panoptes era un gigante de cien ojos "
            "repartidos por todo el cuerpo. Su don no era solo ver: era no dejar de "
            "hacerlo. Cuando descansaba, cerraba apenas unos pocos ojos y mantenía el "
            "resto despiertos, de modo que su vigilancia nunca se interrumpía.\n\n"
            "«Panoptes», el que todo lo observa: el guardián al que nada se le escapa, "
            "ni siquiera durante el sueño.\n\n"
            "Ese centinela incansable da nombre al sistema. Argos observa los ojos del "
            "usuario en tiempo real para detectar el instante en que aparece la fatiga "
            "—cuando los párpados empiezan a vencer a la voluntad—, justo aquello que el "
            "Argos mitológico jamás se permitía. Donde el gigante vigilaba sin dormir, "
            "nuestro Argos vigila para avisar cuándo es momento de descansar."
        )

        ctk.CTkLabel(
            tab,
            text=texto,
            wraplength=560,
            justify="left",
            font=ctk.CTkFont(size=13)
        ).pack(padx=16, pady=16, anchor="w")


    def _about_sistema(self, tab):
        ctk.CTkLabel(
            tab,
            text="Argos combina visión por computadora y métricas validadas "
                "para estimar la fatiga visual de forma no invasiva, solo con la cámara.",
            wraplength=560,
            justify="left"
        ).pack(padx=16, pady=(16, 10), anchor="w")

        items = [
            ("Detección EAR", "Eye Aspect Ratio con MediaPipe FaceLandmarker y baseline adaptativo."),
            ("PERCLOS", "Porcentaje de tiempo con ojos cerrados, indicador validado de somnolencia."),
            ("Índice de fatiga", "Puntaje 0–100 que pondera duración, frecuencia y microsueños."),
            ("Prueba guiada", "Protocolo de validación por fases: verifica que la detección sea correcta."),
        ]

        for titulo, desc in items:
            f = ctk.CTkFrame(tab)
            f.pack(fill="x", padx=16, pady=4)

            ctk.CTkLabel(
                f,
                text=titulo,
                anchor="w",
                font=ctk.CTkFont(size=13, weight="bold")
            ).pack(fill="x", padx=12, pady=(8, 0))

            ctk.CTkLabel(
                f,
                text=desc,
                anchor="w",
                justify="left",
                wraplength=520,
                text_color="gray",
                font=ctk.CTkFont(size=11)
            ).pack(fill="x", padx=12, pady=(0, 8))


    def _about_creadores(self, tab):
        ctk.CTkLabel(
            tab,
            text="Proyecto de tesis desarrollado por:",
            anchor="w"
        ).pack(padx=16, pady=(16, 8), anchor="w")

        for iniciales, nombre in [
            ("TM", "Tobias Molinas"),
            ("MM", "Matias Murto")
        ]:
            f = ctk.CTkFrame(tab)
            f.pack(fill="x", padx=16, pady=6)

            ctk.CTkLabel(
                f,
                text=iniciales,
                width=48,
                height=48,
                font=ctk.CTkFont(size=16, weight="bold"),
                fg_color="#2a6b6b",
                corner_radius=12
            ).pack(side="left", padx=12, pady=12)

            caja = ctk.CTkFrame(
                f,
                fg_color="transparent"
            )
            caja.pack(side="left", padx=(4, 0))

            ctk.CTkLabel(
                caja,
                text=nombre,
                anchor="w",
                font=ctk.CTkFont(size=14, weight="bold")
            ).pack(anchor="w")

            ctk.CTkLabel(
                caja,
                text="Desarrollo · Investigación",
                anchor="w",
                text_color="gray",
                font=ctk.CTkFont(size=11)
            ).pack(anchor="w")

        #==============================================================================================================
#===========================================================
#==========================================================
    def _maximizar(self):
        self.state("zoomed")
        self.lift()
        self.focus_force()
        
    def on_closing(self):
        self.cerrar_sesion_solicitado = False
        self.destroy()
        
    def abrir_monitoreo(self):

        self.monitoreo = InterfazFatiga(
            self,
            self.perfil_nombre,
            self.perfil_id,
            self.perfil_rol,
            self.bd
    )

        self.monitoreo.protocol(
            "WM_DELETE_WINDOW",
            self.volver_desde_monitoreo
    )

        self.withdraw()
        
    def volver_desde_monitoreo(self):
        if self.monitoreo is not None:
            self.monitoreo.destroy()
            self.monitoreo = None

        self.deiconify()
        self.state("zoomed")
        self.lift()
        self.focus_force()
        
    def mostrar_about(self):
        for widget in self.vista_about.winfo_children():
            widget.pack_forget()

        # Mostrar Acerca de
        self.vista_about.pack(
            fill="both",
            expand=True
    )
        
        
        

#========================================
#========================================
# INTERFAZ FATIGA:
#========================================
#========================================

class InterfazFatiga(ctk.CTkToplevel):
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

    def __init__(self, parent, perfil_nombre, perfil_id, perfil_rol, bd):
        super().__init__(parent)
        self.configure(fg_color="#050B12")
        print("DEBUG: InterfazFatiga.__init__ iniciado")
        self.title("Monitoreo de fatiga visual")
        aplicar_icono(self)
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
        self.usuario_id        = perfil_id
        self.usuario_nombre    = perfil_nombre
        self.rol_actual        = perfil_rol
        self.nariz_previa      = None
        self.cerrar_sesion_solicitado = False
        
        # True → __main__ vuelve al login
        self.monitoreo = None
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

        # BD y perfil ya resueltos por VentanaLogin (perfil autenticado)
        self.bd = bd
        print(f"DEBUG: Perfil activo id={self.usuario_id}, nombre={self.usuario_nombre}, rol={self.rol_actual}")

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

    def _volver_al_menu(self):
        self.master.volver_desde_monitoreo()
    # ── Construcción UI ──────────────────────────────
    def _construir_ui(self):
        ancho = self.winfo_screenwidth()
        alto = self.winfo_screenheight()
        self.geometry(f"{ancho}x{alto}+0+0")
        #self.state("zoomed")
        #self.geometry("1150x700")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar: SOLO navegación (estilo taskbar/dock). El contenido de
        # cada sección vive en el panel principal ancho de la derecha.
        panel = ctk.CTkFrame(self, width=240, corner_radius=0, fg_color="#050B12")
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_propagate(False)
        
        # Botón para volver al menú principal
        ctk.CTkButton(
            panel,
            text="← Volver al menú",
            command=self._volver_al_menu
        ).pack(fill="x", padx=12, pady=(10, 5))

        self._logo_panel = cargar_logo((38, 38))
        if self._logo_panel:
            ctk.CTkLabel(panel, text="", image=self._logo_panel).pack(pady=(14, 2))
        ctk.CTkLabel(panel, text="ARGOS",
                     font=ctk.CTkFont(size=19, weight="bold")).pack(pady=(2 if self._logo_panel else 14, 0))
        ctk.CTkLabel(panel, text="Sistema de monitoreo de fatiga visual",
                     font=ctk.CTkFont(size=10), text_color="gray").pack(pady=(0, 10))

        # Perfil activo + cerrar sesión (persistente, no forma parte de la navegación)
        fila_usuario = ctk.CTkFrame(panel, fg_color="#242424", corner_radius=8)
        fila_usuario.pack(fill="x", padx=12, pady=(0, 8))
        caja_nombre = ctk.CTkFrame(fila_usuario, fg_color="transparent")
        caja_nombre.pack(side="left", fill="x", expand=True, padx=(10, 0), pady=8)
        ctk.CTkLabel(caja_nombre, text=self.usuario_nombre, anchor="w",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x")
        ctk.CTkLabel(caja_nombre, text=self.rol_actual, anchor="w",
                     font=ctk.CTkFont(size=10), text_color="gray").pack(fill="x")
        self._icon_logout = cargar_icono("icon_logout", (15, 15))
        ctk.CTkButton(fila_usuario, text="" if self._icon_logout else "Salir",
                      image=self._icon_logout, width=32, height=28,
                      fg_color="#8a2a2a", hover_color="#aa3a3a",
                      command=self._cerrar_sesion).pack(side="right", padx=8, pady=8)

        # Acciones principales
        self.btn_iniciar = ctk.CTkButton(panel, text="Iniciar Detección", command=self.toggle_sistema)
        self.btn_iniciar.pack(padx=12, pady=(0, 3), fill="x")

        self.btn_auto = ctk.CTkButton(panel, text="Auto-ajustar Todo",
                                       fg_color="#5a3a9a", hover_color="#7a4abb",
                                       command=self._iniciar_auto_calibracion)
        self.btn_auto.pack(padx=12, pady=3, fill="x")

        self.label_calib_estado = ctk.CTkLabel(panel, text="", text_color="#ffcc00",
                                                font=ctk.CTkFont(size=11, weight="bold"),
                                                wraplength=260, justify="left")
        self.label_calib_estado.pack(padx=12, pady=(0, 2))

        self.btn_guia = ctk.CTkButton(panel, text="Prueba Guiada", command=self._iniciar_prueba_guiada,
                                       fg_color="#2a5b8a", hover_color="#3a7bba")
        self.btn_guia.pack(padx=12, pady=3, fill="x")

        ctk.CTkFrame(panel, height=1, fg_color="#3a3a3a").pack(fill="x", padx=12, pady=8)

        # Navegación (rail vertical con íconos) — todo abre en el panel principal
        self._nav_buttons = {}
        self._nav_icons = []
        nav_frame = ctk.CTkFrame(panel, fg_color="transparent")
        nav_frame.pack(fill="x", padx=6)
        self._crear_nav_item(nav_frame, "control", "control", "Control",
                              lambda: self._mostrar_vista("control"))
        if self.rol_actual == "Administrador":
            self._crear_nav_item(nav_frame, "calib", "calib", "Calibración",
                                  lambda: self._mostrar_vista("calib"))
        self._crear_nav_item(nav_frame, "stats", "stats", "Estadísticas",
                              lambda: self._mostrar_vista("stats"))
        if self.rol_actual == "Administrador":
            self._crear_nav_item(nav_frame, "stats_todos", "stats", "Estadísticas (Todos)",
                                  lambda: self._mostrar_vista("stats_todos"))
        self._crear_nav_item(nav_frame, "chart", "chart", "Gráfica EAR",
                              lambda: self._mostrar_vista("chart"))

        # ── Panel principal (ancho): una vista a la vez ──
        self._grafico_activo = False
        principal = ctk.CTkFrame(self, corner_radius=0, fg_color="#050B12")
        principal.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)

        self.vista_control = ctk.CTkFrame(principal, fg_color="transparent")
        self._construir_vista_control(self.vista_control)

        self.vista_calib = None
        if self.rol_actual == "Administrador":
            self.vista_calib = ctk.CTkFrame(principal, fg_color="transparent")
            self._construir_vista_calibracion(self.vista_calib)

        self.vista_stats = ctk.CTkFrame(principal, fg_color="transparent")
        self.vista_stats_todos = None
        if self.rol_actual == "Administrador":
            self.vista_stats_todos = ctk.CTkFrame(principal, fg_color="transparent")

        self.vista_chart = ctk.CTkFrame(principal, fg_color="transparent")
        self._construir_vista_chart(self.vista_chart)

        self.vista_about = ctk.CTkFrame(principal, fg_color="transparent")
        self._construir_vista_about(self.vista_about)
        

        self._mostrar_vista("control")

#
# Volver al menú principal 
#
    def _volver_al_menu(self):
        self.sistema_activo = False

        if self.cap:
          self.cap.release()
          self.cap = None

        self.master.volver_desde_monitoreo()

    def _crear_nav_item(self, parent, key, icono_nombre, texto, command):
        """Botón de navegación estilo rail (ícono dibujado + texto, sin
        colores fuertes salvo cuando está activo)."""
        icono = cargar_icono(f"icon_nav_{icono_nombre}", (16, 16))
        self._nav_icons.append(icono)  # evitar garbage-collection de la imagen
        btn = ctk.CTkButton(parent, text="  " + texto, image=icono, anchor="w",
                             fg_color="transparent", hover_color="#2a2a2a",
                             text_color="#cccccc", font=ctk.CTkFont(size=12),
                             height=32, corner_radius=6, command=command)
        btn.pack(fill="x", pady=1)
        self._nav_buttons[key] = btn
        return btn

    def _mostrar_vista(self, nombre):
        """Intercambia qué vista se muestra en el panel principal y marca el
        ítem activo en el rail de navegación. Todas las secciones (Control,
        Calibración, Estadísticas, Gráfica EAR, Acerca de) viven acá — nada
        se abre en ventana aparte."""
        vistas = {
            "control":     self.vista_control,
            "calib":       self.vista_calib,
            "stats":       self.vista_stats,
            "stats_todos": self.vista_stats_todos,
            "chart":       self.vista_chart,
            "about":       self.vista_about,
        }
        vista = vistas.get(nombre)
        if vista is None:
            return

        self._grafico_activo = (nombre == "chart")
        if nombre == "stats":
            self._refrescar_vista_estadisticas(self.vista_stats, self.usuario_id, self.usuario_nombre)
        elif nombre == "stats_todos":
            self._refrescar_vista_estadisticas(self.vista_stats_todos, None, "Todos")
        elif nombre == "chart":
            self._refrescar_grafico()

        for v in vistas.values():
            if v is not None:
                v.pack_forget()
        vista.pack(fill="both", expand=True)

        for key, btn in self._nav_buttons.items():
            activo = key == nombre
            btn.configure(fg_color="#1f4a6b" if activo else "transparent",
                          text_color="white" if activo else "#cccccc")

    def _construir_vista_control(self, tab):
        ctk.CTkLabel(tab, text="Control", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").pack(fill="x", pady=(0, 10))

        cuerpo = ctk.CTkFrame(tab, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True)
        cuerpo.grid_columnconfigure(0, weight=0)
        cuerpo.grid_columnconfigure(1, weight=1)
        cuerpo.grid_rowconfigure(0, weight=1)

        # Columna izquierda: métricas (ancho fijo, con scroll si no entra todo)
        columna = ctk.CTkScrollableFrame(cuerpo, fg_color="transparent", width=300)
        columna.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        if self.rol_actual == "Administrador":
            ctk.CTkButton(columna, text="Gestionar Usuarios", fg_color="#555", hover_color="#666",
                          command=self._abrir_gestion_usuarios).pack(padx=2, pady=(0, 8), fill="x")

        # Card: interruptores de visualización
        card_sw = ctk.CTkFrame(columna, corner_radius=8)
        card_sw.pack(fill="x", padx=2, pady=(0, 8))
        ctk.CTkLabel(card_sw, text="MOSTRAR EN PANTALLA", anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="gray").pack(
            fill="x", padx=12, pady=(10, 4))
        self.sw_camara = ctk.CTkSwitch(card_sw, text="Cámara", command=self._sw_camara)
        self.sw_camara.pack(anchor="w", padx=12, pady=(0, 6))   # apagado por defecto
        self.sw_metricas = ctk.CTkSwitch(card_sw, text="Métricas en vivo", command=self._sw_metricas)
        self.sw_metricas.select()                                # encendido por defecto
        self.sw_metricas.pack(anchor="w", padx=12, pady=(0, 10))

        # Card: estado del sistema (siempre visible)
        self.card_estado = card_estado = ctk.CTkFrame(columna, corner_radius=8)
        card_estado.pack(fill="x", padx=2, pady=(0, 8))
        fila_estado = ctk.CTkFrame(card_estado, fg_color="transparent")
        fila_estado.pack(fill="x", padx=12, pady=10)
        self.label_estado = ctk.CTkLabel(fila_estado, text="Estado: INACTIVO", text_color="gray",
                                          font=ctk.CTkFont(size=13, weight="bold"), anchor="w")
        self.label_estado.pack(side="left")
        self.label_fps = ctk.CTkLabel(fila_estado, text="FPS: 0", text_color="#888",
                                       font=ctk.CTkFont(size=11), anchor="e")
        self.label_fps.pack(side="right")

        # Métricas en vivo (bloque ocultable con el interruptor "Métricas en vivo")
        self.frame_metricas = ctk.CTkFrame(columna, fg_color="transparent")
        self.frame_metricas.pack(fill="x")
        mf = self.frame_metricas

        card_ear = ctk.CTkFrame(mf, corner_radius=8)
        card_ear.pack(fill="x", pady=(0, 8))
        self.label_ear = ctk.CTkLabel(card_ear, text="EAR: 0.000", anchor="w",
                                       font=ctk.CTkFont(size=15, weight="bold"))
        self.label_ear.pack(padx=12, pady=(10, 2), anchor="w")
        self.label_estado_ojo = ctk.CTkLabel(card_ear, text="Ojo: —", anchor="w",
                                              text_color="#aaa", font=ctk.CTkFont(size=11))
        self.label_estado_ojo.pack(padx=12, pady=(0, 10), anchor="w")

        card_conteo = ctk.CTkFrame(mf, corner_radius=8)
        card_conteo.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card_conteo, text="PARPADEOS", anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="gray").pack(
            fill="x", padx=12, pady=(10, 2))
        self.label_parpadeos = ctk.CTkLabel(card_conteo, text="0", anchor="w",
                                             font=ctk.CTkFont(size=20, weight="bold"))
        self.label_parpadeos.pack(padx=12, anchor="w")
        fila_chips = ctk.CTkFrame(card_conteo, fg_color="transparent")
        fila_chips.pack(fill="x", padx=12, pady=(4, 10))
        self.label_prolongados = ctk.CTkLabel(fila_chips, text="Prolongados: 0", anchor="w",
                                              text_color="#ff9040", font=ctk.CTkFont(size=11))
        self.label_prolongados.pack(anchor="w")
        self.label_falsos = ctk.CTkLabel(fila_chips, text="Falsos descartados: 0", anchor="w",
                                         text_color="#888", font=ctk.CTkFont(size=11))
        self.label_falsos.pack(anchor="w")
        self.label_bpm = ctk.CTkLabel(fila_chips, text="Frecuencia: 0 / min",
                                       text_color="cyan", anchor="w", font=ctk.CTkFont(size=11))
        self.label_bpm.pack(anchor="w")

        card_perclos = ctk.CTkFrame(mf, corner_radius=8)
        card_perclos.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card_perclos, text="PERCLOS (60 s)", anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="gray").pack(
            fill="x", padx=12, pady=(10, 2))
        self.label_perclos = ctk.CTkLabel(card_perclos, text="0.0 %", anchor="w",
                                           font=ctk.CTkFont(size=18, weight="bold"), text_color="orange")
        self.label_perclos.pack(padx=12, anchor="w")
        self.bar_perclos = ctk.CTkProgressBar(card_perclos, progress_color="orange")
        self.bar_perclos.set(0)
        self.bar_perclos.pack(fill="x", padx=12, pady=(6, 10))

        card_indice = ctk.CTkFrame(mf, corner_radius=8)
        card_indice.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card_indice, text="ÍNDICE DE FATIGA", anchor="w",
                     font=ctk.CTkFont(size=10, weight="bold"), text_color="gray").pack(
            fill="x", padx=12, pady=(10, 2))
        self.label_indice = ctk.CTkLabel(card_indice, text="0.0 (Normal)", anchor="w",
                                          font=ctk.CTkFont(size=18, weight="bold"))
        self.label_indice.pack(padx=12, anchor="w")
        self.bar_indice = ctk.CTkProgressBar(card_indice)
        self.bar_indice.set(0)
        self.bar_indice.pack(fill="x", padx=12, pady=(6, 10))

        # Alerta (siempre visible, fuera del bloque ocultable)
        self.label_alerta = ctk.CTkLabel(columna, text="", text_color="red",
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.label_alerta.pack(pady=6)

        # Columna derecha: cámara (ocupa el espacio que sobra)
        self.frame_camara = ctk.CTkFrame(cuerpo, corner_radius=10)
        self.frame_camara.grid(row=0, column=1, sticky="nsew")
        self.label_video = ctk.CTkLabel(self.frame_camara, text="[ Cámara oculta ]",
                                         text_color="gray", font=ctk.CTkFont(size=13))
        self.label_video.pack(expand=True, fill="both")

    def _construir_vista_calibracion(self, tab):
        ctk.CTkLabel(tab, text="Calibración", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").pack(fill="x", pady=(0, 10))

        cuerpo = ctk.CTkFrame(tab, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True)
        cuerpo.grid_columnconfigure((0, 1), weight=1)
        cuerpo.grid_rowconfigure(0, weight=1)

        col_deteccion = ctk.CTkFrame(cuerpo, corner_radius=8)
        col_deteccion.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        col_imagen = ctk.CTkFrame(cuerpo, corner_radius=8)
        col_imagen.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        def slider_row(parent, texto, desde, hasta, valor_def, paso, fmt, callback):
            ctk.CTkLabel(parent, text=texto, anchor="w",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(fill="x", padx=12, pady=(12, 0))
            fila = ctk.CTkFrame(parent, fg_color="transparent")
            fila.pack(fill="x", padx=12)
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

        # ── Columna izquierda: Detección ──
        ctk.CTkLabel(col_deteccion, text="— Detección —", text_color="#aaa").pack(pady=(10, 0))

        self.sl_umbral = slider_row(col_deteccion, "Umbral EAR", 0.10, 0.40, self.p_umbral_ear,
                                     0.01, "{:.2f}", lambda v: setattr(self, 'p_umbral_ear', round(v, 2)))

        self.sl_frames = slider_row(col_deteccion, "Frames consecutivos", 1, 10, self.p_frames_cons,
                                     1, "{}", lambda v: setattr(self, 'p_frames_cons', int(v)))

        self.sl_buffer = slider_row(col_deteccion, "Suavizado EAR (frames)", 1, 15, self.p_buffer_ear,
                                     1, "{}", self._actualizar_buffer)

        self.sl_frames_max = slider_row(col_deteccion, "Frames máx. cierre", 5, 40, self.p_frames_max,
                                         1, "{}", lambda v: setattr(self, 'p_frames_max', int(v)))

        self.sl_cooldown = slider_row(col_deteccion, "Cooldown post-parpadeo", 0, 20, self.p_cooldown,
                                       1, "{}", lambda v: setattr(self, 'p_cooldown', int(v)))

        # ── Columna derecha: Imagen ──
        ctk.CTkLabel(col_imagen, text="— Imagen —", text_color="#aaa").pack(pady=(10, 0))

        self.sl_brillo = slider_row(col_imagen, "Brillo", -100, 100, self.p_brillo,
                                     1, "{:+}", lambda v: setattr(self, 'p_brillo', int(v)))

        self.sl_contraste = slider_row(col_imagen, "Contraste", 0.5, 3.0, self.p_contraste,
                                        0.05, "{:.2f}", lambda v: setattr(self, 'p_contraste', round(v, 2)))

        self.sl_clahe = slider_row(col_imagen, "CLAHE (anti-reflejos)", 0.0, 8.0, self.p_clahe,
                                    0.1, "{:.1f}", lambda v: setattr(self, 'p_clahe', round(v, 1)))

        ctk.CTkFrame(col_imagen, height=1, fg_color="#444").pack(fill="x", padx=12, pady=12)

        ctk.CTkButton(col_imagen, text="Fijar Cámara (bloquear auto-ajuste)",
                      fg_color="#555", hover_color="#666",
                      command=self._fijar_camara).pack(padx=12, pady=(4, 0), fill="x")

        ctk.CTkButton(col_imagen, text="Restablecer valores",
                      fg_color="#555", hover_color="#666",
                      command=self._restablecer_calibracion).pack(padx=12, pady=(8, 12), fill="x")

    def _refrescar_vista_estadisticas(self, contenedor, usuario_id, usuario_nombre):
        """Reconstruye la vista de Estadísticas con datos frescos de la BD.
        Se llama cada vez que se navega a esta sección (los datos cambian)."""
        for w in contenedor.winfo_children():
            w.destroy()

        ctk.CTkLabel(contenedor, text=f"Estadísticas — {usuario_nombre}",
                     font=ctk.CTkFont(size=18, weight="bold"), anchor="w").pack(fill="x", pady=(0, 10))

        stats = self.bd.obtener_estadisticas(usuario_id)
        total, avg_ear, primera, ultima, avg_perclos, avg_indice = stats if stats else (0, 0, "-", "-", 0, 0)

        frame_res = ctk.CTkFrame(contenedor, fg_color="transparent")
        frame_res.pack(fill="x", pady=(0, 12))
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
            f = ctk.CTkFrame(frame_res, corner_radius=8)
            f.grid(row=0, column=i, padx=6, pady=6, sticky="ew")
            ctk.CTkLabel(f, text=val, font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10, 2))
            ctk.CTkLabel(f, text=lbl, text_color="gray").pack(pady=(0, 10))

        tabla = ctk.CTkScrollableFrame(contenedor, label_text="Últimos 50 registros")
        tabla.pack(fill="both", expand=True)

        headers = ["Fecha / Hora", "EAR", "Duración", "Clasif.", "Usuario", "Nivel", "PERCLOS", "Índice"]
        widths  = [155, 55, 75, 85, 110, 80, 70, 60]
        for col, (h_txt, w) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(tabla, text=h_txt, font=ctk.CTkFont(weight="bold"),
                         width=w, anchor="w").grid(row=0, column=col, padx=4, pady=(4, 8), sticky="w")

        for ri, (fecha, ear, nombre, nivel, dur, clasif, perc, idx) in enumerate(
                self.bd.obtener_historial(usuario_id, 50), start=1):
            bg = "#2b2b2b" if ri % 2 == 0 else "#1e1e1e"
            dur_txt  = f"{dur} ms" if dur != "—" else "—"
            perc_txt = f"{perc} %" if perc != "—" else "—"
            valores  = [fecha, f"{ear:.3f}", dur_txt, clasif, nombre, nivel, perc_txt, idx]
            for col, (val, w) in enumerate(zip(valores, widths)):
                ctk.CTkLabel(tabla, text=val, width=w, anchor="w",
                             fg_color=bg, corner_radius=0).grid(
                    row=ri, column=col, padx=4, pady=1, sticky="ew")

    def _construir_vista_chart(self, tab):
        ctk.CTkLabel(tab, text="Gráfica EAR en tiempo real", font=ctk.CTkFont(size=18, weight="bold"),
                     anchor="w").pack(fill="x", pady=(0, 10))
        self._chart_figure = Figure(figsize=(7, 4), dpi=100)
        self._chart_ax     = self._chart_figure.add_subplot(111)
        self._chart_canvas = FigureCanvasTkAgg(self._chart_figure, master=tab)
        self._chart_canvas.get_tk_widget().pack(fill="both", expand=True)

    def _refrescar_grafico(self):
        """Redibuja la gráfica EAR mientras la vista 'Gráfica EAR' esté activa
        (self._grafico_activo la corta al navegar a otra sección)."""
        if not self._grafico_activo:
            return
        datos = list(self.historico_ear)
        self._chart_ax.clear()
        if datos:
            self._chart_ax.plot(range(len(datos)), datos, color="#3ba7ff", linewidth=1.4, label="EAR")
            self._chart_ax.axhline(self.p_umbral_ear, color="red", linestyle="--", linewidth=1,
                                   label=f"Umbral {self.p_umbral_ear:.2f}")
            self._chart_ax.legend(loc="upper right", fontsize=8)
        self._chart_ax.set_ylim(0.0, 0.5)
        self._chart_ax.set_xlabel("Cuadros recientes (~5 s)")
        self._chart_ax.set_ylabel("EAR")
        self._chart_figure.tight_layout()
        self._chart_canvas.draw()
        self.after(200, self._refrescar_grafico)
        
      #===========================================================================================    
    #===========================================================================================
    # Antigua vista de About (ahora movidaa menu principal)
     #===========================================================================================    
        #===========================================================================================

    def _construir_vista_about(self, tab):
        ctk.CTkLabel(tab, text="ARGOS", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(0, 0))
        ctk.CTkLabel(tab, text="Argos Panoptes — «el que todo lo ve»",
                     text_color="gray", font=ctk.CTkFont(size=12)).pack(pady=(0, 12))

        tabs = ctk.CTkTabview(tab)
        tabs.pack(fill="both", expand=True)
        tabs.add("¿Por qué Argos?")
        tabs.add("El sistema")
        tabs.add("Creadores")
        self._about_por_que(tabs.tab("¿Por qué Argos?"))
        self._about_sistema(tabs.tab("El sistema"))
        self._about_creadores(tabs.tab("Creadores"))

    def _about_por_que(self, tab):
        texto = (
            "En la mitología griega, Argos Panoptes era un gigante de cien ojos "
            "repartidos por todo el cuerpo. Su don no era solo ver: era no dejar de "
            "hacerlo. Cuando descansaba, cerraba apenas unos pocos ojos y mantenía el "
            "resto despiertos, de modo que su vigilancia nunca se interrumpía.\n\n"
            "«Panoptes», el que todo lo observa: el guardián al que nada se le escapa, "
            "ni siquiera durante el sueño.\n\n"
            "Ese centinela incansable da nombre al sistema. Argos observa los ojos del "
            "usuario en tiempo real para detectar el instante en que aparece la fatiga "
            "—cuando los párpados empiezan a vencer a la voluntad—, justo aquello que el "
            "Argos mitológico jamás se permitía. Donde el gigante vigilaba sin dormir, "
            "nuestro Argos vigila para avisar cuándo es momento de descansar."
        )
        ctk.CTkLabel(tab, text=texto, wraplength=560, justify="left",
                     font=ctk.CTkFont(size=13)).pack(padx=16, pady=16, anchor="w")

    def _about_sistema(self, tab):
        ctk.CTkLabel(tab, text="Argos combina visión por computadora y métricas validadas "
                     "para estimar la fatiga visual de forma no invasiva, solo con la cámara.",
                     wraplength=560, justify="left").pack(padx=16, pady=(16, 10), anchor="w")
        items = [
            ("Detección EAR", "Eye Aspect Ratio con MediaPipe FaceLandmarker y baseline adaptativo."),
            ("PERCLOS", "Porcentaje de tiempo con ojos cerrados, indicador validado de somnolencia."),
            ("Índice de fatiga", "Puntaje 0–100 que pondera duración, frecuencia y microsueños."),
            ("Prueba guiada", "Protocolo de validación por fases: verifica que la detección sea correcta."),
        ]
        for titulo, desc in items:
            f = ctk.CTkFrame(tab)
            f.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(f, text=titulo, anchor="w",
                         font=ctk.CTkFont(size=13, weight="bold")).pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(f, text=desc, anchor="w", justify="left", wraplength=520,
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(fill="x", padx=12, pady=(0, 8))

    def _about_creadores(self, tab):
        ctk.CTkLabel(tab, text="Proyecto de tesis desarrollado por:",
                     anchor="w").pack(padx=16, pady=(16, 8), anchor="w")
        for iniciales, nombre in [("TM", "Tobias Molinas"), ("MM", "Matias Murto")]:
            f = ctk.CTkFrame(tab)
            f.pack(fill="x", padx=16, pady=6)
            ctk.CTkLabel(f, text=iniciales, width=48, height=48,
                         font=ctk.CTkFont(size=16, weight="bold"),
                         fg_color="#2a6b6b", corner_radius=12).pack(side="left", padx=12, pady=12)
            caja = ctk.CTkFrame(f, fg_color="transparent")
            caja.pack(side="left", padx=(4, 0))
            ctk.CTkLabel(caja, text=nombre, anchor="w",
                         font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(caja, text="Desarrollo · Investigación", anchor="w",
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(anchor="w")
            
            
            
#===========================================================================================    
#===========================================================================================
    # Fin Acerca de
#===========================================================================================    
#===========================================================================================

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
        """Muestra u oculta el video (el widget vive siempre en la vista
        Control; acá solo cambia si actualizar_video le manda imagen o no)."""
        self.camara_visible = not self.camara_visible
        if self.camara_visible:
            self.sw_camara.select()
        else:
            self.sw_camara.deselect()

    def _sw_camara(self):
        """Interruptor de cámara: sincroniza el switch con la visibilidad real."""
        self.camara_visible = bool(self.sw_camara.get())
        if not self.camara_visible:
            self.label_video.configure(image="", text="[ Cámara oculta ]")

    def _sw_metricas(self):
        """Interruptor: muestra u oculta el bloque de métricas en vivo."""
        if self.sw_metricas.get():
            self.frame_metricas.pack(fill="x", after=self.card_estado)
        else:
            self.frame_metricas.pack_forget()

    # ── Prueba guiada de validación ──────────────────
    def _iniciar_prueba_guiada(self):
        self._mostrar_vista("control")     # la guía se ve en la cámara de Control
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
        self.label_bpm.configure(text=f"Frecuencia: {bpm} / min")

        score, clasificacion = self._calcular_indice_fatiga()
        self.label_perclos.configure(text=f"{self.perclos_actual:.1f} %")
        self.bar_perclos.set(min(1.0, self.perclos_actual / 100))

        colores = {"Normal": "gray", "Leve": "#ffcc00", "Moderada": "orange", "Alta": "red"}
        color_indice = colores.get(clasificacion, "gray")
        self.label_indice.configure(text=f"{score:.1f}  ({clasificacion})", text_color=color_indice)
        self.bar_indice.set(min(1.0, score / 100))
        self.bar_indice.configure(progress_color=color_indice)

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
                self.label_estado_ojo.configure(text="Ojo: sin señal")
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

                    self.label_estado_ojo.configure(text=f"Ojo: {estado_ojo}")

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
                self.label_estado_ojo.configure(text="Ojo: sin rostro")
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

            self.label_ear.configure(text=f"EAR: {ear_suavizado:.3f}")
            self.label_parpadeos.configure(text=str(self.total_parpadeos))
            self.label_prolongados.configure(text=f"Prolongados: {self.total_prolongados}")
            self.label_falsos.configure(text=f"Falsos descartados: {self.total_falsos}")
            self.label_fps.configure(text=f"FPS: {self._fps:.0f}")
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

    def _cerrar_sesion(self):
        """Cierra la ventana y vuelve al selector de perfiles (bucle en __main__)."""
        self.cerrar_sesion_solicitado = True
        self.on_closing()

    def on_closing(self):
        # La BD no se cierra acá: es compartida con el bucle login↔app de
        # __main__ (se cierra al salir definitivamente de la aplicación).
        self.sistema_activo  = False
        self._grafico_activo = False  # corta el bucle after() de la gráfica EAR
        if self.cap:
            self.cap.release()
        self.face_landmarker.close()
        self.destroy()

# ==========================================
# EJECUCIÓN (con depuración)
# ==========================================
if __name__ == "__main__":
    print("DEBUG: Inicio de la aplicación.")
    try:
        # --- 1. Obtener usuario de Windows y abrir BD ---
        usuario_windows = GestorAutenticacionWindows.usuario_actual()
        print(f"DEBUG: Usuario Windows detectado: {usuario_windows}")

        # --- 1.5 Pantalla de carga (splash con el ojo de Argos parpadeando) ---
        print("DEBUG: Mostrando pantalla de carga...")
        splash_root = ctk.CTk()
        splash_root.withdraw()
        carga = VentanaCarga(splash_root)
        splash_root.wait_window(carga)
        splash_root.destroy()

        bd = GestorBD()
        print(f"DEBUG: BD abierta. Windows Hello disponible: "
              f"{GestorAutenticacionWindows.hello_disponible()}")

        # --- 2. Bucle login ↔ aplicación (Cerrar Sesión vuelve al selector) ---
        while True:
            print("DEBUG: Creando ventana de login...")
            login_root = ctk.CTk()  # ventana temporal oculta
            login_root.withdraw()   # la ocultamos inmediatamente
            login = VentanaLogin(login_root, bd, usuario_windows)
            login_root.wait_window(login)
            login_root.destroy()

            if not login.resultado_ok:
                print("DEBUG: Login cancelado, saliendo.")
                break

#===========Aca hice un cambio en la linea 2438===========================

            print(f"DEBUG: Login OK — perfil '{login.perfil_nombre}' ({login.perfil_rol})")
            app = MenuPrincipal(login.perfil_nombre, login.perfil_id, login.perfil_rol, bd)
            app.protocol("WM_DELETE_WINDOW", app.on_closing)
            print("DEBUG: Entrando en mainloop...")
            app.mainloop()
            print("DEBUG: mainloop finalizado.")

            if not app.cerrar_sesion_solicitado:
                break  # cierre normal de la app → salir del todo
            print("DEBUG: Sesión cerrada, volviendo al selector de perfiles...")

        bd.cerrar()
    except Exception as e:
        print("ERROR CAPTURADO:")
        traceback.print_exc()
        with open("error_log.txt", "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print("Se ha guardado el error en 'error_log.txt'.")
        sys.exit(1)