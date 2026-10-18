#from curses.panel import panel
import traceback  # para depuración
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import math
import numpy as np
import statistics
import hashlib
import asyncio
import threading
import queue
import socket
import re
import sqlite3
from datetime import datetime
import urllib.request
import os
import pathlib
import sys
import ctypes
import winsound
import subprocess
from collections import deque
import time
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
from PIL import Image
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import win32api
import win32gui
import win32con
import win32net
import win32security
import winreg
from PIL import Image, ImageTk, ImageOps, ImageSequence, ImageDraw, ImageFilter
import random
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
SPLASH_BG_PATH = next(
    (os.path.join(ASSETS_DIR, nombre)
     for nombre in ("menu_inicial.gif", "menu_inicial.webp")
     if os.path.isfile(os.path.join(ASSETS_DIR, nombre))),
    os.path.join(ASSETS_DIR, "menu_inicial.png"))

# ── Tipografía propia (viaja con la app) ─────────────────────────────
# Cinzel (SIL OFL 1.1) se usa solo en la portada. Se registra en el proceso
# con GDI, sin instalarla en el sistema ni pedir permisos de administrador.
FUENTES_DIR   = os.path.join(ASSETS_DIR, "fonts")
FUENTE_PORTADA_FAMILIA  = "Cinzel"
# Respaldos por si el .ttf falta o el registro falla: Tk no avisa cuando una
# familia no existe, simplemente cae en Arial, así que la elegimos nosotros.
FUENTE_PORTADA_RESPALDO = ("Sitka Banner", "Palatino Linotype", "Georgia", "Arial")


def registrar_fuentes_propias():
    """Carga los .ttf de assets/fonts en el proceso actual. Debe ejecutarse
    ANTES de crear la raíz de Tk: después, Tk ya enumeró las familias.
    Nunca lanza: si algo falla, la app sigue con las fuentes del sistema."""
    if not os.path.isdir(FUENTES_DIR):
        return 0
    FR_PRIVATE = 0x10
    cargadas = 0
    try:
        for nombre in os.listdir(FUENTES_DIR):
            if not nombre.lower().endswith((".ttf", ".otf")):
                continue
            ruta = os.path.join(FUENTES_DIR, nombre)
            try:
                if ctypes.windll.gdi32.AddFontResourceExW(
                        ctypes.c_wchar_p(ruta), FR_PRIVATE, 0):
                    cargadas += 1
            except Exception:
                continue
    except Exception:
        return cargadas
    return cargadas


def fuente_portada(tamano, peso="normal"):
    """Devuelve una tupla de fuente para la portada, usando Cinzel si quedó
    registrada y el primer respaldo disponible si no."""
    try:
        import tkinter.font as tkfont
        disponibles = set(tkfont.families())
        familia = (FUENTE_PORTADA_FAMILIA
                   if FUENTE_PORTADA_FAMILIA in disponibles
                   else next((f for f in FUENTE_PORTADA_RESPALDO if f in disponibles),
                             "Arial"))
    except Exception:
        familia = "Arial"
    return (familia, tamano, peso) if peso != "normal" else (familia, tamano)


class TemaArgos:
    """Tokens visuales de la aplicación: un único lugar donde vive el aspecto.

    La portada (MenuPrincipal) definió el lenguaje —azules fríos sobre casi
    negro, esquinas rectas, mayúsculas espaciadas— y estos tokens lo extienden
    al resto de la interfaz. Cambiar un valor acá reteamatiza toda la app;
    ningún módulo debería volver a escribir un color literal.
    """

    # ── Superficies ──────────────────────────────────
    FONDO       = "#050B12"   # fondo base, el mismo de la portada
    PANEL       = "#0A1420"   # superficie elevada (sidebar, tarjetas)
    PANEL_ALTO  = "#10283A"   # hover, igual que los botones de la portada
    LINEA       = "#12303F"   # separadores finos

    # ── Acento ───────────────────────────────────────
    ACENTO      = "#1B526F"   # la regla bajo el título de la portada
    ACENTO_VIVO = "#2E7BA6"   # foco, selección, ítem activo

    # ── Texto ────────────────────────────────────────
    TEXTO       = "#E8EDF2"
    TEXTO_SUAVE = "#C8D0D8"
    TEXTO_TENUE = "#8A93A8"

    # ── Estado (ámbar y rojo reservados: solo donde hay riesgo real) ──
    OK      = "#2E8B7A"
    ALERTA  = "#C9A227"
    RIESGO  = "#B4453C"

    # ── Geometría ────────────────────────────────────
    RADIO       = 0           # esquinas rectas, como la portada
    RADIO_CARD  = 4

    # ── Tipografía ───────────────────────────────────
    @staticmethod
    def titulo(tamano, peso="normal"):
        """Cinzel: nombre del producto y encabezados de sección."""
        return ctk.CTkFont(family=fuente_portada(tamano)[0], size=tamano, weight=peso)

    @staticmethod
    def ui(tamano=12, peso="normal"):
        """Texto de interfaz: la fuente por defecto de CTk, muy legible en chico."""
        return ctk.CTkFont(size=tamano, weight=peso)

    @staticmethod
    def dato(tamano=13, peso="normal"):
        """Monoespaciada para lecturas numéricas (EAR, FPS, contadores):
        las cifras no bailan al actualizarse, se lee como instrumento."""
        return ctk.CTkFont(family="Consolas", size=tamano, weight=peso)


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
    # Las operaciones de winrt 3.x son awaitables pero NO corrutinas, y
    # asyncio.run() solo acepta corrutinas: hay que envolverlas en un async def.
    @staticmethod
    def _esperar_winrt(operacion, timeout=None):
        async def _corrutina():
            return await asyncio.wait_for(operacion, timeout=timeout)
        return asyncio.run(_corrutina())

    @staticmethod
    def hello_disponible():
        if not HELLO_IMPORTADO:
            print("DEBUG: Windows Hello: no se pudo importar winrt.")
            return False
        try:
            avail = GestorAutenticacionWindows._esperar_winrt(
                winrt_ui.UserConsentVerifier.check_availability_async(), timeout=10)
            print(f"DEBUG: Windows Hello disponibilidad = {avail}")
            return int(avail) == 0  # 0 = Available
        except Exception as e:
            print(f"DEBUG: Windows Hello no disponible: {type(e).__name__}: {e}")
            return False

    @staticmethod
    def verificar_hello(mensaje="Confirmá tu identidad"):
        """Muestra el diálogo nativo de Windows Hello. True solo si Verified."""
        try:
            resultado = GestorAutenticacionWindows._esperar_winrt(
                winrt_ui.UserConsentVerifier.request_verification_async(mensaje),
                timeout=120)
            print(f"DEBUG: Windows Hello resultado = {resultado}")
            return int(resultado) == 0  # 0 = Verified
        except Exception as e:
            print(f"DEBUG: Windows Hello falló: {type(e).__name__}: {e}")
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

    # ── Diálogo nativo "Seguridad de Windows" (credui.dll) ────────
    # Funciona sin Windows Hello y tanto para cuentas locales como Microsoft:
    # Windows muestra su propio cuadro con la tarjeta del usuario de la sesión,
    # y la contraseña se valida con LogonUser contra ese mismo usuario (SID).
    @staticmethod
    def pedir_password_windows(mensaje, hwnd_padre=None):
        """Muestra el cuadro de credenciales de Windows y valida la contraseña.
        Devuelve True (correcta y del usuario de la sesión), False (incorrecta
        o de otra cuenta) o None (cancelado). Lanza OSError si el cuadro no
        se pudo mostrar, para que el login caiga al PIN de app."""
        from ctypes import wintypes

        class CREDUI_INFOW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("hwndParent", wintypes.HWND),
                        ("pszMessageText", wintypes.LPCWSTR),
                        ("pszCaptionText", wintypes.LPCWSTR),
                        ("hbmBanner", wintypes.HBITMAP)]

        CREDUIWIN_ENUMERATE_CURRENT_USER = 0x200
        ERROR_CANCELLED = 1223

        credui = ctypes.WinDLL("credui", use_last_error=True)
        ole32  = ctypes.WinDLL("ole32")

        info = CREDUI_INFOW(ctypes.sizeof(CREDUI_INFOW), hwnd_padre,
                            mensaje, "ARGOS - Seguridad de Windows", None)
        paquete  = wintypes.ULONG(0)
        buf_out  = ctypes.c_void_p()
        tam_out  = wintypes.ULONG(0)
        guardar  = wintypes.BOOL(False)
        rc = credui.CredUIPromptForWindowsCredentialsW(
            ctypes.byref(info), 0, ctypes.byref(paquete), None, 0,
            ctypes.byref(buf_out), ctypes.byref(tam_out), ctypes.byref(guardar),
            CREDUIWIN_ENUMERATE_CURRENT_USER)
        if rc == ERROR_CANCELLED:
            return None
        if rc != 0:
            raise OSError(f"CredUIPromptForWindowsCredentials error {rc}")

        try:
            n_usr, n_dom, n_pwd = wintypes.DWORD(256), wintypes.DWORD(256), wintypes.DWORD(256)
            usr = ctypes.create_unicode_buffer(256)
            dom = ctypes.create_unicode_buffer(256)
            pwd = ctypes.create_unicode_buffer(256)
            ok = credui.CredUnPackAuthenticationBufferW(
                0, buf_out, tam_out, usr, ctypes.byref(n_usr),
                dom, ctypes.byref(n_dom), pwd, ctypes.byref(n_pwd))
            if not ok:
                raise OSError(f"CredUnPackAuthenticationBuffer error {ctypes.get_last_error()}")
            usuario, dominio, password = usr.value, dom.value, pwd.value
        finally:
            ctypes.memset(buf_out, 0, tam_out.value)
            ole32.CoTaskMemFree(buf_out)
            ctypes.memset(pwd, 0, ctypes.sizeof(pwd))

        # El usuario puede venir como "DOMINIO\usuario"
        if not dominio and "\\" in usuario:
            dominio, usuario = usuario.split("\\", 1)
        return GestorAutenticacionWindows._password_es_del_usuario_actual(
            usuario, dominio, password)

    @staticmethod
    def _password_es_del_usuario_actual(usuario, dominio, password):
        """LogonUser con varias formas de dominio (local, equipo, MicrosoftAccount,
        UPN) y compara el SID del token con el del usuario de la sesión."""
        sid_actual = win32security.GetTokenInformation(
            win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                                           win32security.TOKEN_QUERY),
            win32security.TokenUser)[0]
        candidatos = []
        for d in (dominio, ".", win32api.GetComputerName(), "MicrosoftAccount", None):
            if (d, usuario) not in candidatos:
                candidatos.append((d, usuario))
        for d, u in candidatos:
            try:
                token = win32security.LogonUser(
                    u, d, password,
                    win32security.LOGON32_LOGON_INTERACTIVE,
                    win32security.LOGON32_PROVIDER_DEFAULT)
            except win32security.error:
                continue
            try:
                sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
                return sid == sid_actual
            finally:
                token.Close()
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
        try:
            self.cursor.execute(
                "INSERT INTO usuarios (nombre, rol, tipo) VALUES (?, 'Administrador', 'windows')",
                (nombre,))
            self.conn.commit()
            return self.cursor.lastrowid
        except sqlite3.IntegrityError:
            # Otra instancia o hilo creó el registro entre el SELECT y el INSERT.
            self.cursor.execute(
                "UPDATE usuarios SET tipo='windows', rol='Administrador' WHERE nombre = ?",
                (nombre,))
            self.conn.commit()
            self.cursor.execute("SELECT id FROM usuarios WHERE nombre = ?", (nombre,))
            fila = self.cursor.fetchone()
            return fila[0] if fila else None

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
    def obtener_coordenadas_3d(cls, indices, landmarks, w, h):
        """(x·w, y·h, z·w): la z de MediaPipe está en la escala del ancho, igual
        que x. Con la profundidad, el ojo lejano de una cabeza girada deja de
        verse escorzado y su EAR no se infla."""
        return [(landmarks[i].x * w, landmarks[i].y * h, landmarks[i].z * w) for i in indices]

    @classmethod
    def calcular_ear_ojo(cls, puntos):
        # math.dist acepta 2D o 3D: sirve para ambos tipos de coordenadas.
        v1 = cls.distancia_euclidiana(puntos[1], puntos[5])
        v2 = cls.distancia_euclidiana(puntos[2], puntos[4])
        h  = cls.distancia_euclidiana(puntos[0], puntos[3])
        if h == 0:
            return 0.0
        return (v1 + v2) / (2.0 * h)

    @staticmethod
    def pose_desde_matriz(matriz):
        """(pitch, yaw, roll) en grados desde la matriz de transformación 4×4
        de FaceLandmarker (su 3×3 superior izquierda es la rotación).
        Pitch positivo = cabeza hacia abajo."""
        r = matriz
        pitch = math.degrees(math.atan2(r[2][1], r[2][2]))
        yaw   = math.degrees(math.atan2(-r[2][0], math.hypot(r[0][0], r[1][0])))
        roll  = math.degrees(math.atan2(r[1][0], r[0][0]))
        return pitch, yaw, roll


# ==========================================
# 2.3 DETECTOR DE PARPADEO (sin interfaz)
# ==========================================
class DetectorParpadeo:
    """Máquina de estados del parpadeo, separada de la interfaz para poder
    probarla reproduciendo videos grabados. Por cuadro recibe el EAR de cada
    ojo, la pose de la cabeza y el movimiento de la nariz; devuelve el estado
    del cuadro y, si terminó un cierre, el evento clasificado.

    - Baseline móvil: percentil 90 de los últimos 10 s con ojo abierto y
      evaluable (sube y baja con la postura y la luz), uno por ojo y otro del
      promedio.
    - Cierre por caída relativa desde el pico, no por umbrales fijos: así los
      parpadeos rápidos seguidos no se fusionan en un solo cierre largo.
    - Duración medida a media amplitud entre pico y valle.
    - Mirar hacia abajo o estar de perfil = "no evaluable": no cuenta
      parpadeos ni suma al PERCLOS."""

    CALIB_S             = 1.5
    VENTANA_BASELINE_S  = 10.0
    K_INICIO            = 0.70   # inicio de cierre: EAR < baseline·K_INICIO ...
    K_CAIDA             = 0.25   # ... y pico − EAR ≥ baseline·K_CAIDA
    K_REAPERTURA_REL    = 0.25   # reapertura: EAR ≥ valle + baseline·K_REAPERTURA_REL
    K_REAPERTURA_ABS    = 0.85   # ... o EAR ≥ baseline·K_REAPERTURA_ABS
    MOVIMIENTO_MAX_PX   = 18     # nariz entre cuadros: más que esto no inicia cierre
    HUECO_MAX_S         = 0.5    # cámara trabada: cancela el cierre en curso
    GUINO_CERRADO       = 0.45   # un ojo cerró > 45 % de su baseline ...
    GUINO_ABIERTO       = 0.15   # ... y el otro < 15 % → guiño
    PROF_RUIDO          = 0.40
    PROF_ENTRECERRADO   = 0.60
    ENTRECERRADO_MIN_MS = 500
    NORMAL_MAX_MS       = 300
    LENTO_MAX_MS        = 500
    PROLONGADO_MAX_MS   = 2000
    CIERRE_LARGO_MS     = 15000  # se registra en vivo, sin esperar la reapertura
    PITCH_ABAJO         = 8.0    # grados sobre la referencia
    PITCH_CAIDA_CIERRE  = 5.0    # la cabeza bajó durante el cierre → no evaluable
    YAW_PERFIL          = 55.0
    PITCH_REF_PESO      = 0.01
    PITCH_REF_TOL       = 3.0
    K_OJO_BIEN_ABIERTO  = 0.90

    def __init__(self):
        self.reiniciar()

    def reiniciar(self, conservar_baseline=False):
        """Vuelve a cero. Con conservar_baseline=True (y ya calibrado) mantiene
        la referencia de ojo abierto y de pitch: la usa iniciar detección para
        no pisar una auto-calibración manual."""
        if not (conservar_baseline and getattr(self, "calibrado", False)):
            self.calibrado    = False
            self.baseline     = None
            self.baseline_izq = None
            self.baseline_der = None
            self.pitch_ref    = None
        self._calib_t0      = None
        self._calib         = []          # (ear, izq, der, pitch)
        self._ventana       = deque()     # (t, ear, izq, der) abierto y evaluable
        self.cerrado        = False
        self._pico          = None
        self._pitch_pico    = None
        self._cierre_t0     = None
        self._valle         = None
        self._muestras      = []          # (t, ear, izq, der) del cierre en curso
        self._largo_registrado = False
        self._t_prev        = None
        self._dts           = deque(maxlen=30)
        self.no_evaluable_s = 0.0

    def sembrar_baseline(self, ear_abierto, pitch=None):
        """Baseline inicial desde la auto-calibración manual (ojos abiertos)."""
        self.reiniciar()
        self.baseline = self.baseline_izq = self.baseline_der = ear_abierto
        self.pitch_ref = pitch
        self.calibrado = True
        print(f"DEBUG baseline sembrado por auto-calibración: {ear_abierto:.3f}")

    @property
    def periodo(self):
        """Período de cuadro típico (s); 1/15 hasta tener datos."""
        return statistics.median(self._dts) if self._dts else 1 / 15

    @staticmethod
    def _percentil(valores, p):
        orden = sorted(valores)
        return orden[min(len(orden) - 1, int(len(orden) * p))]

    def _resultado(self, estado, evaluable=True, cerrado=None, evento=None):
        return {"estado": estado, "evaluable": evaluable,
                "cerrado": cerrado, "evento": evento}

    def _cancelar_cierre(self):
        self.cerrado    = False
        self._cierre_t0 = None
        self._valle     = None
        self._muestras  = []
        self._largo_registrado = False
        self._pico      = None

    def _avanzar_tiempo(self, t):
        dt = (t - self._t_prev) if self._t_prev is not None else 0.0
        self._t_prev = t
        if 0 < dt <= self.HUECO_MAX_S:
            self._dts.append(dt)
        return dt

    def sin_rostro(self, t):
        """Cuadro sin cara detectada: no evaluable."""
        dt = self._avanzar_tiempo(t)
        self._cancelar_cierre()
        self.no_evaluable_s += min(dt, self.HUECO_MAX_S)
        return self._resultado("sin rostro", evaluable=False)

    def procesar(self, t, ear_izq, ear_der, pitch=None, yaw=None, movimiento=0.0):
        ear = (ear_izq + ear_der) / 2.0
        dt  = self._avanzar_tiempo(t)

        # ── Calibración inicial ──
        if not self.calibrado:
            if self._calib_t0 is None:
                self._calib_t0 = t
            self._calib.append((ear, ear_izq, ear_der, pitch))
            if t - self._calib_t0 >= self.CALIB_S:
                self.baseline     = self._percentil([m[0] for m in self._calib], 0.90)
                self.baseline_izq = self._percentil([m[1] for m in self._calib], 0.90)
                self.baseline_der = self._percentil([m[2] for m in self._calib], 0.90)
                pitches = [m[3] for m in self._calib if m[3] is not None]
                self.pitch_ref = self._percentil(pitches, 0.25) if pitches else None
                self.calibrado = True
                self._calib = []
                print(f"DEBUG baseline calibrado: {self.baseline:.3f} "
                      f"(izq {self.baseline_izq:.3f}, der {self.baseline_der:.3f}, "
                      f"pitch ref {self.pitch_ref if self.pitch_ref is None else round(self.pitch_ref, 1)})")
            return self._resultado("Calibrando... (mantené ojos abiertos)", evaluable=False)

        B = self.baseline

        # ── Estados no evaluables ──
        no_eval = None
        if yaw is not None and abs(yaw) > self.YAW_PERFIL:
            no_eval = "Perfil (no evaluable)"
        elif (pitch is not None and self.pitch_ref is not None
              and pitch - self.pitch_ref > self.PITCH_ABAJO and ear < B * self.K_INICIO):
            no_eval = "Mirando abajo (no evaluable)"
        elif (self.cerrado and pitch is not None and self._pitch_pico is not None
              and pitch - self._pitch_pico > self.PITCH_CAIDA_CIERRE):
            no_eval = "Mirando abajo (no evaluable)"
        if no_eval:
            self._cancelar_cierre()
            self.no_evaluable_s += min(dt, self.HUECO_MAX_S)
            return self._resultado(no_eval, evaluable=False)

        if dt > self.HUECO_MAX_S and self.cerrado:
            self._cancelar_cierre()      # cámara trabada: el cierre no es medible

        # ── Ojo abierto: buscar inicio de cierre ──
        if not self.cerrado:
            if self._pico is None or ear > self._pico:
                self._pico, self._pitch_pico = ear, pitch
            if (ear < B * self.K_INICIO and self._pico - ear >= B * self.K_CAIDA
                    and movimiento <= self.MOVIMIENTO_MAX_PX):
                self.cerrado    = True
                self._cierre_t0 = t
                self._valle     = ear
                self._muestras  = [(t, ear, ear_izq, ear_der)]
                self._largo_registrado = False
                return self._resultado("Cerrando...", cerrado=True)
            self._actualizar_baseline(t, ear, ear_izq, ear_der, pitch)
            if ear < B * self.K_INICIO:
                # Bajo el umbral pero sin caída nítida (deriva lenta, entrecerrar):
                # el pico decae para que una caída vieja no dispare un cierre.
                self._pico = max(ear, self._pico * 0.9)
            estado = ("Moviendo cabeza (ignorado)" if movimiento > self.MOVIMIENTO_MAX_PX
                      else "Abierto")
            return self._resultado(estado, cerrado=False)

        # ── Ojo cerrado: seguir el valle y esperar la reapertura ──
        self._muestras.append((t, ear, ear_izq, ear_der))
        self._valle = min(self._valle, ear)
        if ear >= self._valle + B * self.K_REAPERTURA_REL or ear >= B * self.K_REAPERTURA_ABS:
            evento = None if self._largo_registrado else self._clasificar()
            self._cancelar_cierre()
            self._pico, self._pitch_pico = ear, pitch
            return self._resultado("Abierto", cerrado=False, evento=evento)

        if (not self._largo_registrado
                and (t - self._cierre_t0) * 1000 > self.CIERRE_LARGO_MS):
            self._largo_registrado = True
            evento = {"duracion_ms": (t - self._cierre_t0) * 1000,
                      "etiqueta": "Cierre-largo", "categoria": "prolongado",
                      "profundidad": 1 - self._valle / B}
            return self._resultado("Cierre largo", cerrado=True, evento=evento)
        return self._resultado("Cerrado...", cerrado=True)

    def _actualizar_baseline(self, t, ear, izq, der, pitch):
        self._ventana.append((t, ear, izq, der))
        while self._ventana and t - self._ventana[0][0] > self.VENTANA_BASELINE_S:
            self._ventana.popleft()
        if len(self._ventana) >= 5:
            self.baseline     = self._percentil([m[1] for m in self._ventana], 0.90)
            self.baseline_izq = self._percentil([m[2] for m in self._ventana], 0.90)
            self.baseline_der = self._percentil([m[3] for m in self._ventana], 0.90)
        # Referencia de pitch: muy lenta, solo con ojo bien abierto y cabeza en
        # su postura habitual, para que mirar abajo un rato no la arrastre.
        if (pitch is not None and self.pitch_ref is not None
                and ear >= self.K_OJO_BIEN_ABIERTO * self.baseline
                and abs(pitch - self.pitch_ref) < self.PITCH_REF_TOL):
            self.pitch_ref += self.PITCH_REF_PESO * (pitch - self.pitch_ref)

    def _clasificar(self):
        """Evento del cierre que acaba de terminar: duración a media amplitud,
        profundidad y etiqueta."""
        B = self.baseline
        medio = (self._pico + self._valle) / 2.0
        bajo  = [m[0] for m in self._muestras if m[1] < medio]
        if bajo:
            duracion_ms = (bajo[-1] - bajo[0] + self.periodo) * 1000
        else:
            duracion_ms = self.periodo * 1000
        profundidad = 1 - self._valle / B

        guino = False
        if self.baseline_izq and self.baseline_der:
            for _, _, izq, der in self._muestras:
                c_izq = 1 - izq / self.baseline_izq
                c_der = 1 - der / self.baseline_der
                if ((c_izq > self.GUINO_CERRADO and c_der < self.GUINO_ABIERTO)
                        or (c_der > self.GUINO_CERRADO and c_izq < self.GUINO_ABIERTO)):
                    guino = True
                    break

        if guino:
            etiqueta, categoria = "Falso-guiño", "falso"
        elif profundidad < self.PROF_RUIDO:
            etiqueta, categoria = "Falso-ruido", "falso"
        elif duracion_ms > self.ENTRECERRADO_MIN_MS and profundidad < self.PROF_ENTRECERRADO:
            etiqueta, categoria = "Entrecerrado", "falso"
        elif duracion_ms <= self.NORMAL_MAX_MS:
            etiqueta, categoria = "Normal", "parpadeo"
        elif duracion_ms <= self.LENTO_MAX_MS:
            etiqueta, categoria = "Lento", "parpadeo"
        elif duracion_ms <= self.PROLONGADO_MAX_MS:
            etiqueta, categoria = "Prolongado", "prolongado"
        else:
            etiqueta, categoria = "Microsueño", "prolongado"
        return {"duracion_ms": duracion_ms, "etiqueta": etiqueta,
                "categoria": categoria, "profundidad": profundidad}

# ==========================================
# 2.4 REGISTRO DE DEPURACIÓN DE LA SEÑAL EAR
# ==========================================
class EARDebugLogger:
    """Graba, por escenario de prueba, la señal cuadro a cuadro (CSV), el video
    crudo de la webcam (.mp4, sin landmarks), capturas con landmarks cada
    CAPTURA_CADA_S segundos y un resumen con el FPS promedio.
    Se activa solo con la variable de entorno ARGOS_DEBUG=<letra de escenario>."""

    COLUMNAS = ["cuadro", "t_s", "rostro", "ear_izq", "ear_der", "ear_usado",
                "ear_suavizado", "baseline", "umbral_cerrar", "umbral_abrir",
                "ojo_cerrado", "estado", "parpadeos", "giro_cabeza",
                "pitch", "yaw", "no_evaluable_s", "movimiento_px", "fps"]
    CAPTURA_CADA_S = 10.0

    def __init__(self, escenario, carpeta, fps_video=30.0, tam_video=(640, 480)):
        import csv
        os.makedirs(carpeta, exist_ok=True)
        sello = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.base = os.path.join(carpeta, f"{escenario}_{sello}")
        self.escenario = escenario
        self._f   = open(self.base + ".csv", "w", newline="", encoding="utf-8")
        self._csv = csv.writer(self._f)
        self._csv.writerow(self.COLUMNAS)
        self._video = cv2.VideoWriter(self.base + ".mp4",
                                      cv2.VideoWriter_fourcc(*"mp4v"),
                                      fps_video, tam_video)
        self._tam_video  = tam_video
        self._t0         = time.time()
        self._n          = 0
        self._fps_suma   = 0.0
        self._fps_n      = 0
        self._ult_captura = None
        self._n_capturas = 0
        self._parpadeos  = 0
        print(f"DEBUG: EARDebugLogger grabando escenario {escenario} en {self.base}.*")

    def grabar_cuadro_crudo(self, frame):
        if frame.shape[1::-1] != self._tam_video:
            frame = cv2.resize(frame, self._tam_video)
        self._video.write(frame)

    def capturar_si_toca(self, frame_anotado):
        t = time.time() - self._t0
        if self._ult_captura is None or t - self._ult_captura >= self.CAPTURA_CADA_S:
            self._ult_captura = t
            self._n_capturas += 1
            cv2.imwrite(f"{self.base}_captura{self._n_capturas}.png", frame_anotado)

    def log(self, **valores):
        self._n += 1
        fila = {"cuadro": self._n, "t_s": round(time.time() - self._t0, 4)}
        fila.update(valores)
        fps = fila.get("fps") or 0.0
        if fps > 0:
            self._fps_suma += fps
            self._fps_n    += 1
        self._parpadeos = fila.get("parpadeos", self._parpadeos)
        fmt = lambda v: f"{v:.5f}" if isinstance(v, float) else ("" if v is None else v)
        self._csv.writerow([fmt(fila.get(c)) for c in self.COLUMNAS])

    def close(self):
        if self._f is None:
            return
        dur = time.time() - self._t0
        fps_prom = self._fps_suma / self._fps_n if self._fps_n else 0.0
        self._f.close()
        self._f = None
        self._video.release()
        with open(self.base + "_resumen.txt", "w", encoding="utf-8") as r:
            r.write(f"Escenario: {self.escenario}\n"
                    f"Duración: {dur:.1f} s\n"
                    f"Cuadros: {self._n}\n"
                    f"FPS promedio (sistema): {fps_prom:.1f}\n"
                    f"Parpadeos marcados por el sistema: {self._parpadeos}\n"
                    f"Capturas: {self._n_capturas}\n")
        print(f"DEBUG: EARDebugLogger cerrado ({dur:.1f} s, {fps_prom:.1f} FPS prom.)")


# ==========================================
# 2.5 PANTALLA DE CARGA (splash con ojo que parpadeaba, ahora ya no jeje)
# ==========================================
class VentanaCarga(ctk.CTkToplevel):
    """Splash inicial: el ojo de Argos parpadea mientras se prepara el sistema.
    Sin bordes, centrado, se cierra solo tras unos segundos."""

    DURACION_MS = 2800

    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(fg_color="#000000")

        w, h = 460, 420
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

        try:
            self.attributes("-topmost", True)
        except Exception:
            pass

        # Fondo del Splash - YA NO SE UTILIZA 
        """try:
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
        self.lbl_fondo.lower()"""

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
                size=(190,190)
        )
        except Exception:
            self.logo_splash = None

        self.lbl_ojo = ctk.CTkLabel(
            self,
            text="",
            image=self.logo_splash
        )
        self.lbl_ojo.pack(pady=(18,2))
        
  #===============================================================================================
  #===============================================================================================

        
        ctk.CTkLabel(self, text="A  R  G  O  S",
                     font=ctk.CTkFont(family="Agency FB",size=44, weight="normal")).pack(pady=(0, 8))
        
        ctk.CTkLabel(self, 
                    text="Monitor de Fatiga Visual",
                    text_color="#8A93A8",
                    font=ctk.CTkFont(
                        family="Agency FB",
                        size=20,
                        weight="normal"
                    )
                ).pack(pady=(2, 12))
        

        self.lbl_log = ctk.CTkLabel(self, text="Iniciando…", text_color="#8A93A8",
                                    font=ctk.CTkFont(family="Agency FB",
                                                            size=18,
                                                            weight="normal"))
        self.lbl_log.pack(pady=(4, 0))

 
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

        ctk.CTkLabel(
            self,
            text=mensaje,
            wraplength=320,
            text_color="#E8EDF2",
            font=ctk.CTkFont(family="Segoe UI", size=14)
        ).pack(pady=(20, 8))

        self.entry = ctk.CTkEntry(
            self,
            show="•",
            width=240,
            fg_color="#0D151E",
            border_color="#526474",
            border_width=1,
            text_color="#E8EDF2",
            font=ctk.CTkFont(family="Agency FB", size=18)
        )
        self.entry.pack(pady=4)
        self.entry.bind("<Return>", lambda e: self._aceptar())

        fr = ctk.CTkFrame(self, fg_color="transparent")
        fr.pack(pady=12)

        boton_aceptar = ctk.CTkButton(
            fr,
            text="A C E P T A R",
            width=100,
            font=ctk.CTkFont(family="Agency FB", size=14),
            fg_color="#E8EDF2",
            hover_color="#E8EDF2",
            text_color="#101820",
            command=self._aceptar
        )
        boton_aceptar.pack(side="left", padx=6)

        

        boton_cancelar = ctk.CTkButton(
            fr,
            text="C A N C E L A R",
            width=100,
            font=ctk.CTkFont(family="Agency FB", size=14),
            fg_color="#18232E",
            hover_color="#354957",
            text_color="#B7C5D2",
            border_width=1,
            border_color="#526474",
            command=self._cancelar
        )
        boton_cancelar.pack(side="left", padx=6)

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
        # Centrada en pantalla: sin coordenadas explícitas, Tk la ubica en una
        # esquina (o en el monitor secundario) y parece que "no abre".
        w, h = 660, 740
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
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
        size=(230, 230)
   )
        
        
        if self._logo:
            ctk.CTkLabel(self, text="", image=self._logo).pack(pady=(20, 2))
        
        self.titulo_argos = ctk.CTkLabel(
            self,
            text="A  R  G  O  S",
            font=ctk.CTkFont(
                family="Agency FB",
                size=45,
                weight="normal"
            ),
            text_color="#E8EDF2"
        )

        self.titulo_argos.pack(
            pady=(2 if self._logo else 20, 0)
        )

        self.linea_argos = ctk.CTkFrame(
            self,
            height=2,
            width=230,
            fg_color="#1B526F"
        )

        self.linea_argos.pack(
            pady=(3, 4)
        )
        
        

        ctk.CTkLabel(
                self,
                text="¿Quién está usando el sistema?",
                font=ctk.CTkFont(
                    family="Segoe UI",
                    size=18,
                    weight="normal"
                )
            ).pack(pady=(8, 4))
        
        
        subtitulo = ("Cuenta de Windows protegida con Windows Hello"
                     if self.hello_disponible else
                     "-")
                     #"Sin Windows Hello: contraseña de Windows (local) o PIN de app")
        
        ctk.CTkLabel(
            self,
            text=subtitulo,
            text_color="#8A93A8",
            font=ctk.CTkFont(
                size=14
            )
        ).pack(pady=(0, 10))

        self.label_error = ctk.CTkLabel(
            self,
            text="",
            text_color="#ff6060",
            font=ctk.CTkFont(
                size=14,
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
            text="S A L I R",
            fg_color="transparent",
            border_width=1,
            font=ctk.CTkFont(
                family= "Agency FB",
                size=16
            ),
            command=self._cancelar
        ).pack(padx=18, pady=(0, 14), fill="x")
        self.lift()
        self.grab_set()
        self._traer_al_frente()

    def _traer_al_frente(self):
        """Fuerza el login al primer plano. Sin esto la ventana puede quedar
        detrás del IDE o de la consola desde la que se lanzó la app."""
        self.lift()
        self.focus_force()
        try:
            self.attributes("-topmost", True)
            # Se libera enseguida para no dejarla clavada sobre todo lo demás.
            self.after(400, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

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
                    size=18,
                    weight="bold"
                )
            ).pack(expand=True)


            ctk.CTkLabel(
                card,   
                text=nombre,
                font=ctk.CTkFont(
                    size=14,
                    weight="bold"
                ),
                wraplength=150
            ).pack(padx=10)
            
            
            ctk.CTkLabel(
                card,
                text=detalle,
                text_color="#8A93A8",
                font=ctk.CTkFont(
                    size=14
                ),
                wraplength=150,
                justify="center"
            ).pack(padx=10, pady=(0, 10))
            
            ctk.CTkButton(
                card,
                text="E N T R A R",
                width=110,
                font=ctk.CTkFont(
                    family="Agency FB",
                    size=16
                ),
                fg_color="#E8EDF2",
                hover_color="#E8EDF2",
                text_color="#101820",
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
                size=14
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
            #   2) cuadro nativo "Seguridad de Windows" con la contraseña de
            #      la cuenta (local o Microsoft), validada con LogonUser
            #   3) PIN de app (PBKDF2)               — si el cuadro nativo falla
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
            try:
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                resultado = GestorAutenticacionWindows.pedir_password_windows(
                    f"Ingresá la contraseña de Windows para entrar como {nombre}.",
                    hwnd)
                cuadro_nativo_ok = True
            except Exception as e:
                print(f"DEBUG: cuadro nativo de Windows falló: {type(e).__name__}: {e}")
                resultado, cuadro_nativo_ok = None, False
            self.grab_set()  # recuperar el foco modal del login

            if cuadro_nativo_ok:
                if resultado is None:
                    return  # cancelado
                if not resultado:
                    self.label_error.configure(text="Contraseña de Windows incorrecta.")
                    return
            else:
                if pin_hash:
                    pin = self._pedir_secreto("PIN de la aplicación",
                                              f"Intruduzca su PIN para continuar")
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
        tema = TemaArgos
        self.title("Gestión de usuarios")
        aplicar_icono(self)
        self.geometry("620x500")
        self.minsize(540, 360)
        self.configure(fg_color=tema.FONDO)
        self.bd = bd
        self.lift()
        self.focus()
        ctk.CTkLabel(self, text="Usuarios", font=tema.ui(22),
                     text_color=tema.TEXTO, anchor="w").pack(fill="x", padx=20, pady=(20, 0))
        ctk.CTkLabel(self, text="Administrá los roles de los perfiles de Argos",
                     font=tema.ui(12), text_color=tema.TEXTO_TENUE,
                     anchor="w").pack(fill="x", padx=20, pady=(0, 16))
        self.lista = ctk.CTkScrollableFrame(self, fg_color=tema.FONDO,
                     corner_radius=tema.RADIO, scrollbar_button_color=tema.ACENTO,
                     scrollbar_button_hover_color=tema.ACENTO_VIVO)
        self.lista.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._refrescar()

    def _refrescar(self):
        tema = TemaArgos
        for widget in self.lista.winfo_children():
            widget.destroy()
        usuarios = self.bd.obtener_usuarios()
        if not usuarios:
            ctk.CTkLabel(self.lista, text="Todavía no hay perfiles registrados",
                         font=tema.ui(14), text_color=tema.TEXTO_TENUE).pack(pady=32)
        for uid, nombre, rol in usuarios:
            fila = ctk.CTkFrame(self.lista, fg_color=tema.PANEL, border_width=1,
                               border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
            fila.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(fila, text=nombre, anchor="w", justify="left", wraplength=440,
                         font=tema.ui(15, "bold"), text_color=tema.TEXTO).pack(
                             fill="x", padx=16, pady=(14, 4))
            ctk.CTkLabel(fila, text=f"  {rol}  ", font=tema.ui(11),
                         text_color=tema.ACENTO_VIVO if rol == "Administrador" else tema.TEXTO_SUAVE,
                         fg_color=tema.PANEL_ALTO, corner_radius=tema.RADIO_CARD).pack(
                             anchor="w", padx=16, pady=(0, 12))
            acciones = ctk.CTkFrame(fila, fg_color=tema.PANEL)
            acciones.pack(fill="x", padx=16, pady=(0, 14))
            ctk.CTkLabel(acciones, text="Rol", font=tema.ui(12),
                         text_color=tema.TEXTO_TENUE).pack(side="left", padx=(0, 10))
            combo = ctk.CTkComboBox(acciones, values=self.ROLES, width=180, height=34,
                         font=tema.ui(12), dropdown_font=tema.ui(12),
                         fg_color=tema.FONDO, border_color=tema.LINEA,
                         button_color=tema.ACENTO, button_hover_color=tema.ACENTO_VIVO,
                         text_color=tema.TEXTO, dropdown_fg_color=tema.PANEL,
                         dropdown_hover_color=tema.PANEL_ALTO, dropdown_text_color=tema.TEXTO,
                         corner_radius=tema.RADIO)
            combo.set(rol)
            combo.pack(side="left", padx=(0, 12))
            ctk.CTkButton(acciones, text="Guardar", width=110, height=34,
                          font=tema.ui(12), fg_color=tema.ACENTO,
                          hover_color=tema.ACENTO_VIVO, text_color=tema.TEXTO,
                          border_width=1, border_color=tema.ACENTO,
                          corner_radius=tema.RADIO,
                          command=lambda u=uid, c=combo: self._guardar(u, c.get())).pack(side="right")

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

class IconoBandeja:
    """Dueño exclusivo de HWND/HICON/menús en un hilo Win32, sin referencias a Tk."""
    MENSAJE = win32con.WM_USER + 20
    ACTUALIZAR = win32con.WM_USER + 21
    TIMER_CLIC = 1

    def __init__(self, comandos):
        self._comandos = comandos
        self._lock = threading.Lock()
        self._estado = {}
        self._tooltip = "Argos · Detección detenida"
        self._activo = False
        self._hwnd = None
        self._icono = None
        self._cerrando = threading.Event()
        self._nombre = f"ArgosBandeja{id(self)}"
        self._ignorar_up = False
        self._timer = 0
        self._hilo = threading.Thread(target=self._ejecutar, name=self._nombre, daemon=True)
        self._hilo.start()

    @property
    def activo(self):
        with self._lock:
            return self._activo

    def actualizar(self, estado, tooltip):
        with self._lock:
            self._estado = dict(estado)
            self._tooltip = tooltip[:127]
            hwnd = self._hwnd
        if hwnd and not self._cerrando.is_set():
            try:
                win32gui.PostMessage(hwnd, self.ACTUALIZAR, 0, 0)
            except win32gui.error:
                pass

    def _notificar_icono(self, operacion):
        with self._lock:
            texto = self._tooltip
        datos = (self._hwnd, 1, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                 self.MENSAJE, self._icono, texto)
        win32gui.Shell_NotifyIcon(operacion, datos)
        with self._lock:
            self._activo = True

    def _ejecutar(self):
        instancia = win32api.GetModuleHandle(None)
        registrada = False
        try:
            # SetTimer no está expuesto en todas las versiones de pywin32.
            # UINT_PTR/HWND deben conservar los 64 bits en Python para Windows.
            from ctypes import wintypes
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t,
                                               wintypes.UINT, ctypes.c_void_p)
            self._user32.SetTimer.restype = ctypes.c_size_t
            self._user32.KillTimer.argtypes = (wintypes.HWND, ctypes.c_size_t)
            self._user32.KillTimer.restype = wintypes.BOOL
            self._taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
            clase = win32gui.WNDCLASS()
            clase.hInstance = instancia
            clase.lpszClassName = self._nombre
            clase.style = win32con.CS_DBLCLKS
            clase.lpfnWndProc = self._wndproc
            win32gui.RegisterClass(clase)
            registrada = True
            hwnd = win32gui.CreateWindow(self._nombre, "Argos Bandeja", 0,
                                         0, 0, 0, 0, 0, 0, instancia, None)
            with self._lock:
                self._hwnd = hwnd
            self._icono = win32gui.LoadImage(0, ICON_PATH, win32con.IMAGE_ICON, 0, 0,
                                            win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
            if not self._icono:
                raise OSError("No se pudo cargar el ícono de Argos")
            if self._cerrando.is_set():
                return
            self._notificar_icono(win32gui.NIM_ADD)
            # Cubre cerrar() mientras se estaba cargando el ícono.
            if self._cerrando.is_set():
                return
            win32gui.PumpMessages()
        except Exception as exc:
            print(f"DEBUG bandeja Argos: {exc}")
        finally:
            with self._lock:
                self._activo = False
            try:
                if self._hwnd and win32gui.IsWindow(self._hwnd):
                    win32gui.DestroyWindow(self._hwnd)
            except win32gui.error:
                pass
            with self._lock:
                self._hwnd = None
            if self._icono:
                try:
                    win32gui.DestroyIcon(self._icono)
                except win32gui.error:
                    pass
                self._icono = None
            if registrada:
                try:
                    win32gui.UnregisterClass(self._nombre, instancia)
                except win32gui.error:
                    pass
            if not self._cerrando.is_set():
                self._comandos.put("bandeja_error")

    def _cancelar_clic(self, hwnd):
        if self._timer:
            self._user32.KillTimer(hwnd, self._timer)
            self._timer = 0

    def _wndproc(self, hwnd, mensaje, wparam, lparam):
        try:
            if mensaje == self._taskbar_created:
                if self._icono and not self._cerrando.is_set():
                    self._notificar_icono(win32gui.NIM_ADD)
                return 0
            if mensaje == self.ACTUALIZAR:
                if self._icono and not self._cerrando.is_set():
                    self._notificar_icono(win32gui.NIM_MODIFY)
                return 0
            if mensaje == self.MENSAJE:
                evento = lparam & 0xFFFF
                if evento == win32con.WM_LBUTTONDBLCLK:
                    self._cancelar_clic(hwnd)
                    self._ignorar_up = True  # Segundo UP del doble clic.
                    self._comandos.put("panel")
                elif evento == win32con.WM_LBUTTONUP:
                    if self._ignorar_up:
                        self._ignorar_up = False
                    else:
                        self._cancelar_clic(hwnd)
                        self._timer = self._user32.SetTimer(
                            hwnd, self.TIMER_CLIC, self._user32.GetDoubleClickTime(), None)
                        if not self._timer:
                            self._comandos.put("abrir")
                elif evento in (win32con.WM_RBUTTONUP, win32con.WM_CONTEXTMENU):
                    self._cancelar_clic(hwnd)
                    self._menu(hwnd)
                return 0
            if mensaje == win32con.WM_TIMER and self._timer and wparam == self._timer:
                self._cancelar_clic(hwnd)
                self._comandos.put("abrir")
                return 0
            if mensaje == win32con.WM_CLOSE:
                win32gui.DestroyWindow(hwnd)
                return 0
            if mensaje == win32con.WM_DESTROY:
                self._cancelar_clic(hwnd)
                try:
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 1))
                finally:
                    with self._lock:
                        self._activo = False
                    win32gui.PostQuitMessage(0)
                return 0
        except Exception as exc:
            print(f"DEBUG bandeja mensaje: {exc}")
            if mensaje in (self.ACTUALIZAR, self._taskbar_created):
                with self._lock:
                    self._activo = False
                self._comandos.put("bandeja_error")
        return win32gui.DefWindowProc(hwnd, mensaje, wparam, lparam)

    def _menu(self, hwnd):
        with self._lock:
            estado = dict(self._estado)
        menu = win32gui.CreatePopupMenu()
        comandos = {1: "abrir", 3: estado.get("accion_deteccion", "iniciar"),
                    4: "recomendacion", 5: "reactivar" if estado.get("silenciado") else "silenciar",
                    7: "salir"}
        try:
            win32gui.AppendMenu(menu, win32con.MF_STRING, 1, "Abrir Argos")
            win32gui.SetMenuDefaultItem(menu, 1, False)
            win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 2,
                                estado.get("estado_menu", "Detección detenida"))
            win32gui.AppendMenu(menu, win32con.MF_STRING, 3,
                                estado.get("texto_deteccion", "Iniciar detección"))
            disponible = estado.get("recomendacion", False)
            win32gui.AppendMenu(menu, win32con.MF_STRING | (0 if disponible else win32con.MF_GRAYED),
                                4, "Ver recomendación" if disponible else "Ver recomendación (sin fatiga)")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 5,
                                "Reactivar alertas" if estado.get("silenciado") else "Silenciar alertas 30 min")
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
            win32gui.AppendMenu(menu, win32con.MF_STRING, 7, "Salir de Argos")
            win32gui.SetForegroundWindow(hwnd)
            x, y = win32gui.GetCursorPos()
            elegido = win32gui.TrackPopupMenu(menu, win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD,
                                              x, y, 0, hwnd, None)
            if elegido in comandos:
                self._comandos.put(comandos[elegido])
        finally:
            if win32gui.IsWindow(hwnd):
                win32gui.PostMessage(hwnd, win32con.WM_NULL, 0, 0)
            win32gui.DestroyMenu(menu)

    def cerrar(self):
        self._cerrando.set()
        with self._lock:
            hwnd = self._hwnd
        if hwnd:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except win32gui.error:
                pass
        if threading.current_thread() is not self._hilo:
            self._hilo.join(timeout=0.4)


class PanelRapido(ctk.CTkToplevel):
    """Tarjeta de estado: el dueño Tk aporta los datos una vez por segundo."""
    ANCHO, ALTO = 340, 340

    def __init__(self, parent, estado):
        super().__init__(parent)
        self._raiz = parent
        self._animacion_after = self._foco_after = None
        self._cerrado = False
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.configure(fg_color=TemaArgos.PANEL)
        esc = self._get_window_scaling()
        izq, arriba, der, abajo = ToastArgos._area_trabajo(self)
        self._x = max(izq, der - round((self.ANCHO + 12)*esc))
        self._y = max(arriba, abajo - round((self.ALTO + 12)*esc))
        self._desliz = round(16*esc)
        self.geometry(f"{self.ANCHO}x{self.ALTO}{self._x:+d}{self._y+self._desliz:+d}")
        tarjeta = ctk.CTkFrame(self, fg_color=TemaArgos.PANEL, border_color=TemaArgos.LINEA,
                               border_width=1, corner_radius=TemaArgos.RADIO_CARD)
        tarjeta.pack(fill="both", expand=True)
        cabecera = ctk.CTkFrame(tarjeta, fg_color="transparent")
        cabecera.pack(fill="x", padx=14, pady=(12, 0))
        self._logo = cargar_logo((25, 25))
        if self._logo:
            ctk.CTkLabel(cabecera, text="", image=self._logo, width=26).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(cabecera, text="A R G O S", font=fuente_portada(17),
                     text_color=TemaArgos.TEXTO).pack(side="left")
        self._estado = ctk.CTkLabel(tarjeta, text="", font=TemaArgos.ui(12))
        self._estado.pack(fill="x", padx=14)
        indice = ctk.CTkFrame(tarjeta, fg_color=TemaArgos.PANEL_ALTO,
                              border_width=1, border_color=TemaArgos.LINEA,
                              corner_radius=TemaArgos.RADIO_CARD)
        indice.pack(fill="x", padx=14, pady=(4, 6))
        ctk.CTkLabel(indice, text="ÍNDICE DE FATIGA", font=TemaArgos.ui(10),
                     text_color=TemaArgos.TEXTO_TENUE, height=18).pack(pady=(4, 0))
        self._valor = ctk.CTkLabel(indice, text="—", font=TemaArgos.dato(30, "bold"), height=34)
        self._valor.pack()
        self._nivel = ctk.CTkLabel(indice, text="", font=TemaArgos.ui(11), height=18)
        self._nivel.pack()
        self._barra = ctk.CTkProgressBar(indice, height=5, fg_color=TemaArgos.LINEA)
        self._barra.pack(fill="x", padx=10, pady=(4, 8))
        metricas = ctk.CTkFrame(tarjeta, fg_color="transparent")
        metricas.pack(fill="x", padx=10)
        self._metricas = []
        for i, titulo in enumerate(("Parpadeos/min", "PERCLOS %", "Parpadeos\nde la sesión")):
            metricas.grid_columnconfigure(i, weight=1, uniform="metrica")
            valor = ctk.CTkLabel(metricas, text="—", font=TemaArgos.dato(16), height=22)
            valor.grid(row=0, column=i, sticky="ew")
            ctk.CTkLabel(metricas, text=titulo, font=TemaArgos.ui(10), height=26,
                         text_color=TemaArgos.TEXTO_TENUE).grid(row=1, column=i, sticky="n")
            self._metricas.append(valor)
        self._silencio = ctk.CTkLabel(tarjeta, text="", font=TemaArgos.ui(10), height=18,
                                      text_color=TemaArgos.TEXTO_TENUE)
        self._silencio.pack(fill="x", padx=10)
        botones = ctk.CTkFrame(tarjeta, fg_color="transparent")
        botones.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkButton(botones, text="Abrir Argos", height=27, fg_color=TemaArgos.ACENTO,
                      hover_color=TemaArgos.ACENTO_VIVO,
                      command=lambda: self._accion("abrir")).pack(fill="x", pady=(0, 4))
        fila = ctk.CTkFrame(botones, fg_color="transparent")
        fila.pack(fill="x")
        fila.grid_columnconfigure((0, 1), weight=1, uniform="boton")
        self._deteccion = ctk.CTkButton(fila, text="", width=0, height=28,
                                         font=TemaArgos.ui(10), fg_color=TemaArgos.PANEL_ALTO,
                                         command=lambda: self._accion(self._comando_deteccion))
        self._deteccion.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self._recomendacion = ctk.CTkButton(fila, text="Ver recomendación", width=0, height=28,
                                            font=TemaArgos.ui(10), fg_color=TemaArgos.PANEL_ALTO,
                                            command=lambda: self._accion("recomendacion"))
        self._recomendacion.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self.actualizar(estado)
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<FocusOut>", self._perder_foco, add="+")
        self._inicio = time.monotonic()
        self.lift()
        self.focus_force()
        self._animar()

    def actualizar(self, estado):
        activo, datos = estado["activo"], estado["datos"]
        color = GestorAlertas.COLORES.get(estado["nivel"], TemaArgos.OK)
        self._estado.configure(text="● Detección activa" if activo else "○ Detección detenida",
                               text_color=TemaArgos.OK if activo else TemaArgos.TEXTO_TENUE)
        self._valor.configure(text=f'{estado["score"]:.0f}' if datos else "—", text_color=color)
        self._nivel.configure(text=estado["nivel"] if datos else "Sin datos de esta sesión", text_color=color)
        self._barra.configure(progress_color=color)
        self._barra.set(estado["score"]/100 if datos else 0)
        for etiqueta, valor in zip(self._metricas, (str(estado["bpm"]), f'{estado["perclos"]:.1f}', str(estado["total"]))):
            etiqueta.configure(text=valor if datos else "—")
        self._silencio.configure(text=f'Alertas silenciadas hasta {estado["hasta"]}' if estado["silenciado"] else "")
        self._comando_deteccion = estado["accion_deteccion"]
        self._deteccion.configure(text=estado["texto_deteccion"])
        self._recomendacion.configure(state="normal" if estado["recomendacion"] else "disabled")

    def _accion(self, comando):
        raiz = self._raiz
        self.destroy()
        raiz._ejecutar_comando_bandeja(comando)

    def _animar(self):
        self._animacion_after = None
        fraccion = min(1, (time.monotonic()-self._inicio)/0.18)
        avance = 1-(1-fraccion)**3
        self.attributes("-alpha", avance)
        y = self._y + round(self._desliz*(1-avance))
        self.geometry(f"{self.ANCHO}x{self.ALTO}{self._x:+d}{y:+d}")
        if fraccion < 1:
            self._animacion_after = self.after(16, self._animar)

    def _perder_foco(self, event=None):
        if self._foco_after is not None:
            self.after_cancel(self._foco_after)
        self._foco_after = self.after(120, self._comprobar_foco)

    def _comprobar_foco(self):
        self._foco_after = None
        foco = self.focus_get()
        if foco is None or foco.winfo_toplevel() is not self:
            # Un doble clic en la bandeja quita primero el foco. Conservar
            # esa intención hasta que llegue "panel" por la cola de 200 ms.
            self._raiz._panel_cierre_foco = time.monotonic()
            self.destroy()

    def destroy(self):
        if self._cerrado:
            return
        self._cerrado = True
        for pendiente in (self._animacion_after, self._foco_after):
            if pendiente is not None:
                self.after_cancel(pendiente)
        if getattr(self._raiz, "_panel_rapido", None) is self:
            self._raiz._panel_rapido = None
        super().destroy()


class MenuPrincipal(ctk.CTk):
    """Carcasa de la aplicación. El fondo, el título y el menú son permanentes;
    cada sección se abre en su lugar, a ancho completo y sin el menú."""

    VENTANA_W = 1360
    VENTANA_H = 768

    COL_X    = 0.045     # borde izquierdo de la columna del menú
    BTN_W    = 268
    TITULO_Y = 0.115
    LINEA_Y  = 0.175
    BTN_Y0   = 0.285
    BTN_PASO = 0.068

    # (clave, etiqueta, ¿solo administrador?) - Que lo que pones mati?
    SECCIONES = [
        ("control",     "M O N I T O R E O",         False),
        ("calib",       "C A L I B R A C I Ó N",     True),
        ("stats",       "E S T A D Í S T I C A S",   False),
        ("stats_todos", "E S T A D.  T O T A L E S", True),
        ("chart",       "G R Á F I C A   E A R",     False),
        ("usuarios",    "U S U A R I O S",           True),
        ("about",       "A C E R C A   D E",         False),
    ]
    TITULOS = {
        "control":     "M O N I T O R E O",
        "calib":       "C A L I B R A C I Ó N",
        "stats":       "E S T A D Í S T I C A S",
        "stats_todos": "E S T A D.  T O T A L E S",
        "chart":       "G R Á F I C A  E A R",
        "about":       "A C E R C A  D E",
    }

    def __init__(self, perfil_nombre, perfil_id, perfil_rol, bd):
        super().__init__()
        self.configure(fg_color=TemaArgos.FONDO)

        self.perfil_nombre = perfil_nombre
        self.perfil_id     = perfil_id
        self.perfil_rol    = perfil_rol
        self.bd            = bd
        self.cerrar_sesion_solicitado = False
        self.monitoreo     = None      # InterfazFatiga, creada una sola vez
        self._recomendaciones_after = self.after(200, self._consultar_recomendaciones)
        self._recordatorio_recomendacion = None
        self._destruyendo = False
        self._comandos_bandeja = queue.Queue()
        self._bandeja = IconoBandeja(self._comandos_bandeja)
        self._panel_rapido = None
        self._panel_cierre_foco = 0.0
        self._aviso_bandeja_mostrado = False
        self._silencio_bandeja_hasta = 0.0
        self._ultimo_estado_bandeja = 0.0
        self._frente_after = None
        self.bind("<Unmap>", self._minimizar_bandeja, add="+")
        self.protocol("WM_DELETE_WINDOW", self._ocultar_o_cerrar)

        self.title("ARGOS")
        aplicar_icono(self)
        self._centrar()
        self.resizable(False, False)

        ancho = min(self.VENTANA_W, self.winfo_screenwidth())
        alto  = min(self.VENTANA_H, self.winfo_screenheight())

        # El menú es un Canvas: la foto de fondo y los textos se dibujan en él.
        # Tk no tiene transparencia real; con widgets, fg_color="transparent"
        # pintaba cajas del color del contenedor encima de la foto.
        self._fondo_tam = None
        self._fondos_tk = []
        self._fondo_duraciones = []
        self._fondo_indice = 0
        self._fondo_objetivo = None
        self._fondo_listo = False
        self._fondo_carga = None
        self._fondo_carga_after = None
        self._fondo_id = self._ojo_id = None
        try:
            from generar_assets import dibujar_ojo
        except ImportError:
            dibujar_ojo = None
        self._dibujar_ojo = dibujar_ojo
        self._ojo_originales = []
        for nombre in (() if dibujar_ojo else
                       ("ojo_abierto.png", "ojo_semi.png", "ojo_cerrado.png")):
            with Image.open(os.path.join(ASSETS_DIR, nombre)) as img:
                self._ojo_originales.append(img.convert("RGBA"))
        self._ojos_tk = []
        self._ojo_tam = None
        self._ojo_cuadro = 0
        self._ojo_inicio = None
        self._ojo_doble = False
        self._animaciones_pausa = None
        self._menu_visible = False
        self._animaciones_destruidas = False
        self._animaciones = {
            "fondo": {"after": None, "vence": None, "restante": None},
            "ojo": {"after": None, "vence": None,
                    "restante": round(random.uniform(2.5, 6) * 1000)},
        }
        self.bind("<Map>", self._estado_animaciones, add="+")
        self.bind("<Unmap>", self._estado_animaciones, add="+")
        self.vista_menu = ctk.CTkFrame(self, fg_color=TemaArgos.FONDO, corner_radius=0)
        self.vista_menu.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lienzo = tk.Canvas(self.vista_menu, highlightthickness=0, bd=0,
                                bg=TemaArgos.FONDO)
        self.lienzo.place(x=0, y=0, relwidth=1, relheight=1)

        # Fondo de las secciones, independiente del menú
        self.vista_seccion = ctk.CTkFrame(
            self,
            fg_color=TemaArgos.FONDO
        )
        
    #============================================================================
       

        self._construir_menu()
        self._construir_marco_seccion()
        self._actualizar_fecha_hora()
        self.mostrar_menu()

    # ══════════ MENÚ ══════════
    def _construir_menu(self):
        self._botones_menu = []          # (clave, x1, y1, x2, y2) en px del canvas
        self._hover_menu   = None
        self._fecha_id = self._hora_id = None
        self.lienzo.bind("<Configure>", lambda e: self._dibujar_menu())
        self.lienzo.bind("<Motion>", self._menu_movimiento)
        self.lienzo.bind("<Leave>", lambda e: self._menu_hover(None))
        self.lienzo.bind("<Button-1>", self._menu_clic)

    def _fuente_menu(self, familia, tamano, peso="normal"):
        """Tamaño en px lógicos de CTk → px físicos (el Canvas no escala solo)."""
        return (familia, -round(tamano * self._get_window_scaling()), peso)

    def _dibujar_menu(self):
        c = self.lienzo
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        s = self._get_window_scaling()

        # Fondo a la resolución física real, anclado arriba a la izquierda:
        # sin recentrado ni estirado (antes saltaba ~50 px al aplicar el DPI).
        if self._fondo_tam != (W, H):
            self._preparar_fondo(W, H)
        tam_ojo = max(1, round(120 * s))
        if self._ojo_tam != tam_ojo:
            if self._dibujar_ojo is not None:
                self._ojos_tk = []
                for nivel in range(16):
                    with self._dibujar_ojo(tam_ojo * 4, 1 - nivel / 15) as img:
                        self._ojos_tk.append(ImageTk.PhotoImage(img.resize(
                            (tam_ojo, tam_ojo), Image.Resampling.LANCZOS), master=c))
            else:
                self._ojos_tk = [ImageTk.PhotoImage(img.resize(
                    (tam_ojo, tam_ojo), Image.Resampling.LANCZOS), master=c)
                    for img in self._ojo_originales]
            self._ojo_tam = tam_ojo
        c.delete("all")
        self._fondo_id = c.create_image(
            0, 0, image=self._fondos_tk[self._fondo_indice], anchor="nw")
        self._ojo_id = c.create_image(
            0.915 * W, 0.14 * H, image=self._ojos_tk[self._ojo_cuadro],
            anchor="center")
        self._sincronizar_animaciones()

        x0     = self.COL_X * W
        ancho  = self.BTN_W * s
        ui_fam = ctk.ThemeManager.theme["CTkFont"]["family"]

        c.create_text(x0, self.TITULO_Y * H, text="A  R  G  O  S", anchor="w",
                      fill=TemaArgos.TEXTO, font=self._fuente_menu("Agency FB", 50))
        c.create_line(x0, self.LINEA_Y * H, x0 + ancho, self.LINEA_Y * H,
                      fill=TemaArgos.ACENTO, width=max(1, round(s)))

        self._botones_menu = []
        alto_btn = 34 * s
        fila = 0
        for clave, etiqueta, solo_admin in self.SECCIONES:
            if solo_admin and self.perfil_rol != "Administrador":
                continue      # se oculta, en vez de ofrecer algo que no responde
            y = (self.BTN_Y0 + fila * self.BTN_PASO) * H
            c.create_rectangle(x0, y - alto_btn / 2, x0 + 3 * s, y + alto_btn / 2,
                               fill=TemaArgos.ACENTO_VIVO, width=0,
                               state="hidden", tags=(f"barra_{clave}",))
            c.create_text(x0 + 14 * s, y, text=etiqueta, anchor="w",
                          fill=TemaArgos.TEXTO_SUAVE, tags=(f"txt_{clave}",),
                          font=self._fuente_menu("Agency FB", 18))
            self._botones_menu.append((clave, x0, y - alto_btn / 2, x0 + ancho, y + alto_btn / 2))
            fila += 1

        # ── Pie: sistema a la izquierda, sesión a la derecha ──
        yb = 0.955 * H
        self._fecha_id = c.create_text(x0, yb - 46 * s, anchor="sw", fill=TemaArgos.TEXTO_SUAVE,
                                       font=self._fuente_menu("Consolas", 13))
        self._hora_id = c.create_text(x0, yb - 24 * s, anchor="sw", fill=TemaArgos.TEXTO_SUAVE,
                                      font=self._fuente_menu("Consolas", 13))
        c.create_text(x0, yb, text="● ARGOS OS v1.0.0", anchor="sw",
                      fill=TemaArgos.TEXTO_TENUE, font=self._fuente_menu("Consolas", 10))
        self._refrescar_reloj()

        xd = 0.965 * W
        bw, bh = 88 * s, 30 * s
        c.create_rectangle(xd - bw, yb - bh, xd, yb, outline=TemaArgos.LINEA,
                           width=max(1, round(s)), fill="", tags=("salir_caja",))
        c.create_text(xd - bw / 2, yb - bh / 2, text="S A L I R", tags=("txt_salir",),
                      fill=TemaArgos.TEXTO_SUAVE, font=self._fuente_menu("Agency FB", 18))
        self._botones_menu.append(("salir", xd - bw, yb - bh, xd, yb))
        xn = xd - bw - 14 * s
        c.create_text(xn, yb - bh / 2 - 2 * s, text=self.perfil_nombre, anchor="se",
                      fill=TemaArgos.TEXTO, font=self._fuente_menu(ui_fam, 14, "bold"))
        c.create_text(xn, yb - bh / 2 + 2 * s, text=self.perfil_rol.upper(), anchor="ne",
                      fill=TemaArgos.TEXTO_TENUE, font=self._fuente_menu("Consolas", 10))
        if self._hover_menu:
            self._menu_hover(self._hover_menu, forzar=True)

    def _preparar_fondo(self, ancho, alto):
        """Guardá sólo el tamaño actual; Tk usa unos 4 bytes por píxel."""
        self._pausar_animaciones()
        if self._fondo_carga is not None:
            self._fondo_carga.close()
        # Liberamos la caché anterior antes de armar la nueva. Reservamos
        # margen para la conversión RGB, el recorte y las copias de Tk.
        if self._fondo_id is not None:
            self.lienzo.itemconfigure(self._fondo_id, image="")
        self._fondos_tk.clear()
        self._fondo_indice = 0
        self._fondo_objetivo = None
        self._fondo_listo = False
        self._fondo_tam = (ancho, alto)
        self._fondo_carga = self._cargar_cuadros_fondo(ancho, alto)
        # Sólo el primer cuadro se prepara ahora; el resto deja respirar a Tk.
        next(self._fondo_carga)

    def _cargar_cuadros_fondo(self, ancho, alto):
        presupuesto = 250 * 1024 * 1024
        with Image.open(SPLASH_BG_PATH) as fuente:
            duraciones = []
            for i, cuadro in enumerate(ImageSequence.Iterator(fuente)):
                duraciones.append(max(20, int(cuadro.info.get("duration", 80))))
                if i == 0:
                    self._agregar_cuadro_fondo(cuadro, ancho, alto)
                yield
            margen = fuente.width * fuente.height * 8 + ancho * alto * 8
            capacidad = max(1, (presupuesto - margen) // (ancho * alto * 4))
            salto = max(1, math.ceil(len(duraciones) / capacidad))
            self._fondo_duraciones = [sum(duraciones[i:i + salto])
                                     for i in range(0, len(duraciones), salto)]
            # También repartimos la lectura: buscar cuadros de un GIF largo
            # puede llevar tiempo aunque después salteemos algunos.
            fuente.seek(0)
            for i, cuadro in enumerate(ImageSequence.Iterator(fuente)):
                if i and i % salto == 0:
                    self._agregar_cuadro_fondo(cuadro, ancho, alto)
                yield
        self._fondo_listo = True
        self._animaciones["fondo"]["restante"] = self._fondo_duraciones[0]

    def _agregar_cuadro_fondo(self, cuadro, ancho, alto):
        with cuadro.convert("RGB") as rgb:
            with ImageOps.fit(rgb, (ancho, alto),
                              method=Image.Resampling.LANCZOS) as img:
                self._fondos_tk.append(ImageTk.PhotoImage(img, master=self.lienzo))

    def _continuar_carga_fondo(self):
        self._fondo_carga_after = None
        if not self._animaciones_visibles() or self._fondo_carga is None:
            return
        limite = time.monotonic() + 0.008
        try:
            # Como máximo dos cuadros por callback, sin bloquear toda la carga.
            for _ in range(2):
                next(self._fondo_carga)
                if time.monotonic() >= limite:
                    break
        except StopIteration:
            self._fondo_carga = None
        self._sincronizar_animaciones()

    def _animaciones_visibles(self):
        return (not self._animaciones_destruidas and self._menu_visible
                and self.winfo_ismapped() and self.state() != "iconic"
                and self.lienzo.winfo_ismapped())

    def _programar_animacion(self, nombre, demora, objetivo=None):
        estado = self._animaciones[nombre]
        if estado["after"] is not None:
            return
        estado["restante"] = demora
        if not self._animaciones_visibles():
            return
        estado["vence"] = (time.monotonic() + demora / 1000
                           if objetivo is None else objetivo)
        callback = self._avanzar_fondo if nombre == "fondo" else self._avanzar_ojo
        restante = (estado["vence"] - time.monotonic()) * 1000
        estado["after"] = self.after(max(1, math.ceil(restante)), callback)

    def _pausar_animaciones(self):
        if self._animaciones_pausa is None:
            self._animaciones_pausa = time.monotonic()
        if self._fondo_carga_after is not None:
            self.after_cancel(self._fondo_carga_after)
            self._fondo_carga_after = None
        for estado in self._animaciones.values():
            if estado["after"] is not None:
                self.after_cancel(estado["after"])
                estado["restante"] = max(
                    1, round((estado["vence"] - time.monotonic()) * 1000))
                estado["after"] = None
                estado["vence"] = None

    def _estado_animaciones(self, event):
        # El binding del toplevel también recibe eventos de sus hijos.
        if event.widget is self or event.widget is self.lienzo:
            if event.type == tk.EventType.Unmap:
                self._pausar_animaciones()
            else:
                self._sincronizar_animaciones()

    def _sincronizar_animaciones(self):
        if not self._animaciones_visibles():
            self._pausar_animaciones()
            return
        if self._animaciones_pausa is not None:
            pausa = time.monotonic() - self._animaciones_pausa
            if self._ojo_inicio is not None:
                self._ojo_inicio += pausa
            if self._fondo_objetivo is not None:
                self._fondo_objetivo += pausa
            self._animaciones_pausa = None
        if self._fondo_carga is not None and self._fondo_carga_after is None:
            self._fondo_carga_after = self.after(16, self._continuar_carga_fondo)
        if self._fondo_listo and self._fondo_id is not None and len(self._fondos_tk) > 1:
            if self._fondo_objetivo is None:
                self._fondo_objetivo = time.monotonic() + self._fondo_duraciones[0] / 1000
            self._programar_animacion("fondo", 0, self._fondo_objetivo)
        if self._ojo_id is not None:
            self._programar_animacion("ojo", self._animaciones["ojo"]["restante"])

    def _avanzar_fondo(self):
        self._animaciones["fondo"]["after"] = None
        if not self._animaciones_visibles():
            self._pausar_animaciones()
            return
        ahora = time.monotonic()
        anterior = self._fondo_indice
        ciclo = sum(self._fondo_duraciones) / 1000
        if ahora >= self._fondo_objetivo + ciclo:
            self._fondo_objetivo += math.floor((ahora - self._fondo_objetivo) / ciclo) * ciclo
        while ahora >= self._fondo_objetivo:
            self._fondo_indice = (self._fondo_indice + 1) % len(self._fondos_tk)
            self._fondo_objetivo += self._fondo_duraciones[self._fondo_indice] / 1000
        if anterior != self._fondo_indice:
            self.lienzo.itemconfigure(self._fondo_id,
                                     image=self._fondos_tk[self._fondo_indice])
        self._programar_animacion("fondo", 0, self._fondo_objetivo)

    def _avanzar_ojo(self):
        self._animaciones["ojo"]["after"] = None
        if not self._animaciones_visibles():
            self._pausar_animaciones()
            return
        ahora = time.monotonic()
        if self._ojo_inicio is None:
            self._ojo_inicio = ahora
            self._ojo_doble = random.random() < 0.20
        transcurrido = ahora - self._ojo_inicio
        # El segundo parpadeo arranca tras 120 ms con el ojo abierto.
        if self._ojo_doble and transcurrido >= 0.400:
            self._ojo_inicio += 0.400
            self._ojo_doble = False
            transcurrido = ahora - self._ojo_inicio
        demora = 16
        if transcurrido < 0.090:
            apertura = 1 - (transcurrido / 0.090) ** 2
        elif transcurrido < 0.130:
            apertura = 0
        elif transcurrido < 0.280:
            apertura = 1 - (1 - (transcurrido - 0.130) / 0.150) ** 2
        else:
            apertura = 1
            if self._ojo_doble:
                demora = max(1, math.ceil((0.400 - transcurrido) * 1000))
            else:
                self._ojo_inicio = None
                demora = round(random.uniform(2.5, 6) * 1000)
        nivel = round((1 - apertura) * (len(self._ojos_tk) - 1))
        if nivel != self._ojo_cuadro:
            self._ojo_cuadro = nivel
            self.lienzo.itemconfigure(self._ojo_id, image=self._ojos_tk[nivel])
        self._programar_animacion("ojo", demora)

    def _consultar_recomendaciones(self):
        self._recomendaciones_after = None
        # Un lote se reduce al último nivel recibido, sin reconstruir varias
        # veces la ventana ni monopolizar el hilo de la interfaz.
        clave = None
        for _ in range(32):
            try:
                clave = COLA_RECOMENDACIONES.get_nowait()
            except queue.Empty:
                break
        if clave is not None:
            VentanaRecomendacion.abrir(self, clave)
        for _ in range(32):
            try:
                comando = self._comandos_bandeja.get_nowait()
            except queue.Empty:
                break
            self._ejecutar_comando_bandeja(comando)
            if self._destruyendo:
                return
        if time.monotonic() - self._ultimo_estado_bandeja >= 1:
            self._actualizar_bandeja()
        self._recomendaciones_after = self.after(200, self._consultar_recomendaciones)

    def _estado_bandeja(self):
        ahora = time.time()
        mon = self.monitoreo
        activo = bool(mon and mon.sistema_activo)
        datos = bool(mon and mon.deteccion_inicio is not None)
        if mon and self._silencio_bandeja_hasta:
            mon.alertas._pospuesto_hasta = max(mon.alertas._pospuesto_hasta, self._silencio_bandeja_hasta)
            self._silencio_bandeja_hasta = 0.0
        hasta = mon.alertas._pospuesto_hasta if mon else self._silencio_bandeja_hasta
        score, nivel = mon._calcular_indice_fatiga() if datos else (0.0, "Normal")
        accion = "pausar" if activo else "reanudar" if datos else "iniciar"
        texto = {"pausar": "Pausar detección", "reanudar": "Reanudar detección", "iniciar": "Iniciar detección"}[accion]
        estado = dict(activo=activo, datos=datos, score=score, nivel=nivel,
                      bpm=sum(1 for t in mon.historial_tiempos if 0 <= ahora-t <= 60) if datos else 0,
                      perclos=mon.perclos_actual if datos else 0.0,
                      total=mon.total_parpadeos if datos else 0,
                      silenciado=hasta > ahora,
                      hasta=datetime.fromtimestamp(hasta).strftime("%H:%M") if hasta > ahora else "",
                      accion_deteccion=accion, texto_deteccion=texto,
                      recomendacion=datos and nivel in ("Leve", "Moderada", "Severa"),
                      estado_menu=f"Detección activa · índice {score:.0f} ({nivel})" if activo else "Detección detenida")
        if estado["silenciado"]:
            tooltip = f'Argos · Alertas silenciadas hasta {estado["hasta"]}'
        elif activo:
            tooltip = "Argos · Detección activa · " + (f"Fatiga {nivel.lower()}" if nivel != "Normal" else "Normal")
        else:
            tooltip = "Argos · Detección detenida"
        estado["tooltip"] = tooltip
        return estado

    def _actualizar_bandeja(self):
        estado = self._estado_bandeja()
        self._ultimo_estado_bandeja = time.monotonic()
        self._bandeja.actualizar(estado, estado["tooltip"])
        if self._panel_rapido is not None:
            self._panel_rapido.actualizar(estado)

    def _minimizar_bandeja(self, event):
        if event.widget is self and not self._destruyendo and self.state() == "iconic":
            if self._bandeja.activo:
                self._ocultar_en_bandeja()

    def _ocultar_o_cerrar(self):
        if self._bandeja.activo:
            self._ocultar_en_bandeja()
        else:
            self.on_closing()

    def _ocultar_en_bandeja(self):
        if not self._bandeja.activo:
            return
        if self._panel_rapido is not None:
            self._panel_rapido.destroy()
        self.withdraw()
        if not self._aviso_bandeja_mostrado:
            self._aviso_bandeja_mostrado = True
            threading.Thread(target=GestorAlertas._toast_windows,
                             args=("Argos en la bandeja del sistema",
                                   "Argos sigue activo en la bandeja del sistema. Doble clic en el ícono para ver su estado; clic derecho para más opciones."),
                             kwargs={"recomendacion": False, "tag": "argos-bandeja"},
                             daemon=True).start()

    def _abrir_desde_bandeja(self):
        self.deiconify()
        self.state("normal")
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        if self._frente_after is not None:
            self.after_cancel(self._frente_after)
        self._frente_after = self.after(400, self._quitar_topmost_bandeja)

    def _quitar_topmost_bandeja(self):
        self._frente_after = None
        self.attributes("-topmost", False)

    def _ejecutar_comando_bandeja(self, comando):
        if self._destruyendo:
            return
        if comando == "panel":
            if self._panel_rapido is not None:
                self._panel_rapido.destroy()
            else:
                margen = ctypes.windll.user32.GetDoubleClickTime()/1000 + 0.25
                if time.monotonic() - self._panel_cierre_foco > margen:
                    self._panel_rapido = PanelRapido(self, self._estado_bandeja())
                self._panel_cierre_foco = 0.0
            return
        if self._panel_rapido is not None:
            self._panel_rapido.destroy()
        if comando == "salir":
            self.on_closing()
            return
        if comando == "abrir":
            self._abrir_desde_bandeja()
        elif comando == "bandeja_error":
            # No dejar una ventana oculta si falla el ícono o muere su hilo.
            if self.state() in ("withdrawn", "iconic"):
                self._abrir_desde_bandeja()
        elif comando in ("iniciar", "reanudar"):
            if comando == "iniciar":
                self._abrir_desde_bandeja()
            self.abrir_seccion("control")
            self._estado_bandeja()  # Aplicar silencio pendiente antes de iniciar.
            if not self.monitoreo.sistema_activo:
                self.monitoreo.toggle_sistema()
        elif comando == "pausar":
            if self.monitoreo is not None and self.monitoreo.sistema_activo:
                self.monitoreo.toggle_sistema()
        elif comando == "recomendacion":
            estado = self._estado_bandeja()
            if estado["recomendacion"]:
                VentanaRecomendacion.abrir(self, estado["nivel"])
        elif comando in ("silenciar", "reactivar"):
            hasta = time.time()+1800 if comando == "silenciar" else 0.0
            self._silencio_bandeja_hasta = hasta if self.monitoreo is None else 0.0
            if self.monitoreo is not None:
                self.monitoreo.alertas._pospuesto_hasta = hasta
        self._actualizar_bandeja()

    def destroy(self):
        self._destruyendo = True
        if getattr(self, "_panel_rapido", None) is not None:
            self._panel_rapido.destroy()
        if hasattr(self, "_bandeja"):
            self._bandeja.cerrar()
        for nombre in ("_recomendaciones_after", "_recordatorio_recomendacion", "_frente_after"):
            pendiente = getattr(self, nombre, None)
            if pendiente is not None:
                self.after_cancel(pendiente)
                setattr(self, nombre, None)
        self._animaciones_destruidas = True
        if hasattr(self, "_animaciones"):
            self._pausar_animaciones()
        if getattr(self, "_fondo_carga", None) is not None:
            self._fondo_carga.close()
            self._fondo_carga = None
        super().destroy()

    def _boton_en(self, x, y):
        for clave, x1, y1, x2, y2 in self._botones_menu:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return clave
        return None

    def _menu_movimiento(self, event):
        self._menu_hover(self._boton_en(event.x, event.y))

    def _menu_hover(self, clave, forzar=False):
        if clave == self._hover_menu and not forzar:
            return
        c = self.lienzo
        anterior, self._hover_menu = self._hover_menu, clave
        if anterior and anterior != clave:
            if anterior == "salir":
                c.itemconfigure("salir_caja", fill="")
                c.itemconfigure("txt_salir", fill=TemaArgos.TEXTO_SUAVE)
            else:
                c.itemconfigure(f"barra_{anterior}", state="hidden")
                c.itemconfigure(f"txt_{anterior}", fill=TemaArgos.TEXTO_SUAVE)
        if clave == "salir":
            c.itemconfigure("salir_caja", fill=TemaArgos.RIESGO)
            c.itemconfigure("txt_salir", fill=TemaArgos.TEXTO)
        elif clave:
            c.itemconfigure(f"barra_{clave}", state="normal")
            c.itemconfigure(f"txt_{clave}", fill=TemaArgos.TEXTO)
        c.configure(cursor="hand2" if clave else "")

    def _menu_clic(self, event):
        clave = self._boton_en(event.x, event.y)
        if clave == "salir":
            self._cerrar_sesion()
        elif clave:
            self._menu_hover(None)
            self.abrir_seccion(clave)

    # ══════════ MARCO DE SECCIÓN ══════════
    def _construir_marco_seccion(self):
        v = self.vista_seccion
        v.grid_columnconfigure(0, weight=1)
        v.grid_rowconfigure(1, weight=1)

        cab = ctk.CTkFrame(v, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=26, pady=(18, 12))

        self.lbl_seccion = ctk.CTkLabel(cab, text="", font=fuente_portada(22),
                                         text_color=TemaArgos.TEXTO)
        self.lbl_seccion.pack(side="left")
        self.lbl_seccion_sub = ctk.CTkLabel(cab, text="", font=TemaArgos.dato(11),
                                             text_color=TemaArgos.TEXTO_TENUE)
        self.lbl_seccion_sub.pack(side="left", padx=(16, 0))

        ctk.CTkButton(cab, text="⌂   M E N Ú   P R I N C I P A L",
                      width=210, height=32,
                      font=TemaArgos.dato(11), fg_color="transparent",
                      hover_color=TemaArgos.PANEL_ALTO,
                      text_color=TemaArgos.TEXTO_SUAVE,
                      border_width=1, border_color=TemaArgos.ACENTO,
                      corner_radius=TemaArgos.RADIO,
                      command=self.mostrar_menu).pack(side="right")

        self.host_seccion = ctk.CTkFrame(v, fg_color="transparent")
        self.host_seccion.grid(row=1, column=0, sticky="nsew", padx=26, pady=(0, 18))
        self.host_seccion.grid_columnconfigure(0, weight=1)
        self.host_seccion.grid_rowconfigure(0, weight=1)

    # ══════════ NAVEGACIÓN ══════════
    def mostrar_menu(self):
        if self.monitoreo is not None:
            self.monitoreo.sistema_activo = False   # la cámara no sigue de fondo
            if self.monitoreo.cap:
                self.monitoreo.cap.release()
                self.monitoreo.cap = None
        self._menu_visible = True
        self.vista_seccion.place_forget()
        self.vista_menu.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._sincronizar_animaciones()

    def abrir_seccion(self, clave):
        if clave == "usuarios":
            VentanaGestionUsuarios(self, self.bd)
            return

        if self.monitoreo is None:
            # Se construye una sola vez: MediaPipe no vuelve a inicializarse.
            self.monitoreo = InterfazFatiga(
                self.host_seccion, self.perfil_nombre, self.perfil_id,
                self.perfil_rol, self.bd, al_volver=self.mostrar_menu)
            self.monitoreo.grid(row=0, column=0, sticky="nsew")

        self.monitoreo._mostrar_vista(clave)
        self.lbl_seccion.configure(text=self.TITULOS.get(clave, ""))
        self.lbl_seccion_sub.configure(text=self._subtitulo(clave))

        self._menu_visible = False
        self._pausar_animaciones()
        self.vista_menu.place_forget()
        self.vista_seccion.place(relx=0, rely=0, relwidth=1, relheight=1)

    def _subtitulo(self, clave):
        if clave in ("stats", "calib"):
            return self.perfil_nombre
        if clave == "stats_todos":
            return "todos los perfiles"
        if clave == "chart":
            return "tiempo real"
        if clave == "about":
            return "v1.0.0"
        return ""

    # ══════════ VARIOS ══════════
    def _actualizar_fecha_hora(self):
        self._refrescar_reloj()
        self.after(1000, self._actualizar_fecha_hora)

    def _refrescar_reloj(self):
        if self._fecha_id is None:
            return
        ahora = datetime.now()
        self.lienzo.itemconfigure(self._fecha_id, text=ahora.strftime("%d / %m / %Y"))
        self.lienzo.itemconfigure(self._hora_id, text=ahora.strftime("%H : %M : %S"))

    def _centrar(self):
        w = min(self.VENTANA_W, self.winfo_screenwidth())
        h = min(self.VENTANA_H, self.winfo_screenheight())
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.lift()
        self.focus_force()

    def _cerrar_sesion(self):
        self.cerrar_sesion_solicitado = True
        self._apagar()
        self.destroy()

    def on_closing(self):
        self.cerrar_sesion_solicitado = False
        self._apagar()
        self.destroy()

    def _apagar(self):
        if self.monitoreo is not None:
            self.monitoreo.detener_todo()
        
        
        

#========================================
#========================================
# INTERFAZ FATIGA:
#========================================
#========================================

# ==========================================
# 4.5 ALERTAS ESCALONADAS (4 canales)
# ==========================================
# Ojos del personaje de assets/recomendaciones/leve_original.png (1254 px),
# medidos a mano: (cx, cy, semieje_x, semieje_y, pestañas_arriba).
OJOS_RECO_LEVE = [(446, 504, 58, 42, 9), (624, 501, 39, 41, 8)]


def parpadeo_parametrico(img, ojos, k, ss=4):
    """Devuelve 'img' con los ojos a k de cerrarse (0 abierto, 1 cerrado).

    Para personajes sin versión de ojos cerrados: cada ojo es una elipse; el
    párpado baja como una cortina con el color de piel de cada columna (tomado
    justo encima del ojo y suavizado) y deja una línea de pestañas suave.
    Se dibuja a 'ss'× y se reduce, para bordes sin dientes."""
    if k <= 0.01:
        return img.copy()
    # Solo se procesa el recorte de los ojos (el supersampleado de la imagen
    # entera costaba ~130 ms por cuadro); después se pega en su lugar.
    margen = 16
    x0 = max(0, int(min(cx - ea for cx, _, ea, _, _ in ojos)) - margen)
    x1 = min(img.width, int(max(cx + ea for cx, _, ea, _, _ in ojos)) + margen)
    y0 = max(0, int(min(cy - eb - ex for _, cy, _, eb, ex in ojos)) - margen)
    y1 = min(img.height, int(max(cy + eb for _, cy, _, eb, _ in ojos)) + margen)
    if (x0, y0, x1, y1) != (0, 0, img.width, img.height):
        recorte = parpadeo_parametrico(
            img.crop((x0, y0, x1, y1)),
            [(cx - x0, cy - y0, ea, eb, ex) for cx, cy, ea, eb, ex in ojos], k, ss)
        salida = img.copy()
        salida.paste(recorte, (x0, y0))
        return salida
    a = np.array(img.convert("RGBA"))
    W, H = img.size
    mascara = Image.new("L", (W * ss, H * ss), 0)
    lineas = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0))
    dm, dl = ImageDraw.Draw(mascara), ImageDraw.Draw(lineas)
    relleno = a.copy()
    for cx, cy, ea, eb, extra in ojos:
        xs = np.linspace(cx - ea, cx + ea, 120)
        curva = np.sqrt(np.clip(1 - ((xs - cx) / ea) ** 2, 0, 1))
        semi = eb * curva
        arriba = cy - semi - extra * curva - 2
        abajo = cy + semi
        cierre = cy + 0.40 * semi                 # línea final: arco suave
        borde = arriba + k * (cierre - arriba)
        # al final del cierre también se tapa la parte baja del ojo
        hasta = borde + max(0.0, (k - 0.55) / 0.45) * (abajo + 3 - borde)
        dm.polygon([(x * ss, y * ss) for x, y in zip(xs, arriba)] +
                   [(x * ss, y * ss) for x, y in zip(xs[::-1], hasta[::-1])], fill=255)
        cols = list(range(int(cx - ea) - 2, int(cx + ea) + 3))
        muestras = []
        for x in cols:
            uu = min(1.0, max(-1.0, (x - cx) / ea))
            ytop = int(cy - eb * math.sqrt(1 - uu ** 2) - extra - 8)
            muestras.append(a[max(0, ytop - 4):ytop + 1, x, :3].mean(axis=0))
        muestras = np.array(muestras)
        nucleo = np.ones(9) / 9
        muestras = np.stack([np.convolve(np.pad(muestras[:, c], 4, mode="edge"), nucleo, "valid")
                             for c in range(3)], axis=1)
        for x, m in zip(cols, muestras):
            relleno[int(cy - eb - extra - 6):int(cy + eb + 6), x, :3] = m
        for i in range(len(xs) - 1):
            rel = i / (len(xs) - 1)
            grosor = (1.5 + 3.5 * math.sin(math.pi * rel) * min(1, k * 1.6)) * ss
            dl.line([(xs[i] * ss, borde[i] * ss), (xs[i + 1] * ss, borde[i + 1] * ss)],
                    fill=(38, 38, 40, 255), width=max(1, int(round(grosor))))
    mascara = mascara.resize((W, H), Image.Resampling.LANCZOS)
    lineas = lineas.resize((W, H), Image.Resampling.LANCZOS)
    salida = img.copy()
    salida.paste(Image.fromarray(relleno), (0, 0), mascara)
    salida.alpha_composite(lineas)
    return salida


PUERTO_RECOMENDACIONES = 47613
CLAVES_RECOMENDACION = frozenset(("Leve", "Moderada", "Severa", "BajaFrecuencia"))
COLA_RECOMENDACIONES = queue.Queue(maxsize=32)


# Identidad propia para las notificaciones de Windows: con ella el encabezado
# dice "Argos" con el ícono del ojo (antes "Windows PowerShell 5.1") y Argos
# aparece con su nombre en Configuración → Notificaciones.
AUMID_ARGOS = "Argos.MonitorFatiga"
AUMID_POWERSHELL = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
AUMID_TOAST = AUMID_POWERSHELL          # pasa a AUMID_ARGOS si el registro funciona


def registrar_identidad_notificaciones():
    """Registra AUMID_ARGOS por usuario (sin administrador), idempotente."""
    global AUMID_TOAST
    try:
        valores = {"DisplayName": "Argos",
                   "IconUri": os.path.join(ASSETS_DIR, "logo_ojo.png"),
                   "IconBackgroundColor": "FF101820"}
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                rf"Software\Classes\AppUserModelId\{AUMID_ARGOS}", 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as llave:
            for nombre, valor in valores.items():
                try:
                    actual, tipo = winreg.QueryValueEx(llave, nombre)
                except OSError:
                    actual, tipo = None, None
                if actual != valor or tipo != winreg.REG_SZ:
                    winreg.SetValueEx(llave, nombre, 0, winreg.REG_SZ, valor)
        AUMID_TOAST = AUMID_ARGOS
    except OSError as exc:
        print(f"DEBUG identidad de notificaciones: {exc}")


def registrar_protocolo_argos():
    """Registro por usuario, idempotente; no requiere privilegios de administrador."""
    try:
        if getattr(sys, "frozen", False):
            comando = f'"{sys.executable}" "%1"'
        else:
            ejecutable = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            comando = f'"{ejecutable}" "{os.path.abspath(__file__)}" "%1"'
        for subclave, valores in (
            (r"Software\Classes\argos", {"": "URL:Argos", "URL Protocol": ""}),
            (r"Software\Classes\argos\shell\open\command", {"": comando}),
        ):
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subclave, 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE) as llave:
                for nombre, valor in valores.items():
                    try:
                        actual, tipo = winreg.QueryValueEx(llave, nombre)
                    except OSError:
                        actual, tipo = None, None
                    if actual != valor or tipo != winreg.REG_SZ:
                        winreg.SetValueEx(llave, nombre, 0, winreg.REG_SZ, valor)
    except OSError as exc:
        print(f"DEBUG protocolo Argos: {exc}")


def enviar_recomendacion(clave):
    try:
        with socket.create_connection(("127.0.0.1", PUERTO_RECOMENDACIONES), timeout=0.7) as conexion:
            conexion.sendall(f"RECO {clave}\n".encode("ascii"))
            conexion.shutdown(socket.SHUT_WR)
            return conexion.recv(16) == b"OK\n"
    except OSError:
        return False


def escuchar_recomendaciones():
    """El hilo vive durante el proceso (también durante login); jamás llama a Tk."""
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            servidor.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        servidor.bind(("127.0.0.1", PUERTO_RECOMENDACIONES))
        servidor.listen(4)
    except OSError:
        servidor.close()
        return

    def recibir():
        with servidor:
            while True:
                try:
                    conexion, _ = servidor.accept()
                except OSError:
                    return
                with conexion:
                    try:
                        conexion.settimeout(0.5)
                        datos = b""
                        limite = time.monotonic() + 0.7
                        while len(datos) < 64 and b"\n" not in datos:
                            conexion.settimeout(max(0.01, limite - time.monotonic()))
                            bloque = conexion.recv(64 - len(datos))
                            if not bloque:
                                break
                            datos += bloque
                            if time.monotonic() >= limite:
                                break
                        match = re.fullmatch(rb"RECO (Leve|Moderada|Severa|BajaFrecuencia)\n", datos)
                        if match:
                            COLA_RECOMENDACIONES.put_nowait(match[1].decode("ascii"))
                            conexion.sendall(b"OK\n")
                    except (OSError, queue.Full):
                        pass
    threading.Thread(target=recibir, name="Argos recomendaciones", daemon=True).start()


class VentanaRecomendacion(ctk.CTkToplevel):
    """Guías no modales. PIL se prepara una vez por tamaño; el tick solo dibuja."""
    _instancia = None
    _cache = {}                 # PIL, nunca PhotoImage de un intérprete Tk anterior
    _parpadeos = None
    CIRCULOS = {
        "Leve": ((305, 980, 128), (625, 981, 128), (948, 981, 128)),
        "Moderada": ((304, 300, 162), (759, 235, 149), (1212, 365, 156)),
        "Severa": ((277, 999, 149), (632, 996, 145), (979, 999, 147)),
    }
    # Todos los textos de la ventana, por nivel. "pasos" se muestran en la
    # lista; "activos" reemplazan al paso mientras se está haciendo.
    TEXTOS = {
        "Leve": dict(
            titulo="Asistente 20-20-20",
            subtitulo="Pausa visual breve basada en la recomendación oftalmológica de la "
                      "American Optometric Association.",
            descripcion="Cada 20 minutos de uso continuo de pantalla, dirija la vista hacia un "
                        "objeto situado a 6 metros de distancia, durante 20 segundos. Esta "
                        "práctica relaja el músculo ciliar y previene la fatiga visual.",
            pasos=("Cada 20 minutos de pantalla continua",
                   "Mire a un objeto a 6 metros (20 pies) de distancia",
                   "Mantenga la mirada durante 20 segundos"),
            activos=("Preparando pausa visual...",
                     "Dirija la vista a 6 metros de distancia",
                     "Mantenga la mirada..."),
            espera="Inicie el asistente cuando esté listo.",
            final="¡Pausa completada! Vuelva a realizar la pausa en 20 minutos.",
            iniciar="Iniciar asistente",
            recordar=20,
            pie="Argos es una herramienta de apoyo preventiva. No sustituye la evaluación oftalmológica profesional.",
            pie_destacado=False,
        ),
        "Moderada": dict(
            titulo="Pausa activa",
            subtitulo="Interrumpa la actividad frente a la pantalla, descanse la vista y "
                      "realice ejercicios breves de estiramiento y lubricación ocular.",
            descripcion="Durante esta pausa, mantenga la vista alejada del monitor y combine "
                        "descanso visual con parpadeo consciente para favorecer la "
                        "lubricación natural del ojo.",
            pasos=("Mire a un objeto a 6 metros de distancia durante 20 segundos",
                   "Cierre los ojos y parpadee de forma consciente (30 segundos)",
                   "Verifique y ajuste la iluminación ambiental del entorno"),
            activos=("Dirija la vista a lo lejos — relajando el músculo ciliar",
                     "Parpadee conscientemente para restaurar la película lagrimal",
                     "Evite reflejos directos y contraste excesivo con la pantalla"),
            espera="Seleccione la duración e inicie la pausa.",
            final="¡Pausa completada! Retorne a su actividad con la vista descansada.",
            iniciar="Iniciar pausa",
            recordar=10,
            pie="Argos es una herramienta de apoyo preventiva. No sustituye la evaluación oftalmológica profesional.",
            pie_destacado=False,
        ),
        "Severa": dict(
            titulo="Pausa prolongada",
            subtitulo="Se detectaron indicadores sostenidos de fatiga visual. Interrumpa el "
                      "uso de pantallas durante al menos 10 minutos y realice los ejercicios "
                      "de relajación ocular descritos a continuación.",
            descripcion="Esta pausa es necesaria para favorecer la recuperación visual. Si los "
                        "síntomas persisten después del descanso, se recomienda consultar con "
                        "un profesional oftalmólogo.",
            pasos=("Mueva la vista de izquierda a derecha (5 repeticiones completas)",
                   "Mueva la vista de arriba a abajo (5 repeticiones completas)",
                   "Cierre los ojos y haga círculos lentos con la mirada "
                   "(10 segundos en cada sentido)"),
            activos=("Realice movimientos horizontales suaves",
                     "Realice movimientos verticales suaves",
                     "Movimientos circulares con los ojos cerrados"),
            espera="Seleccione la duración e inicie la pausa.",
            final="¡Pausa completada! Si los síntomas persisten, considere consultar con "
                  "un oftalmólogo.",
            iniciar="Iniciar pausa",
            recordar=30,
            pie="Si los síntomas de fatiga visual persisten de forma recurrente, consulte "
                "con un profesional oftalmólogo. Argos no realiza diagnóstico clínico.",
            pie_destacado=True,
        ),
    }

    @property
    def _textos(self):
        return self.TEXTOS[self.nivel]

    @classmethod
    def abrir(cls, parent, clave):
        if clave not in CLAVES_RECOMENDACION:
            return
        ventana = cls._instancia
        if ventana is not None:
            try:
                if ventana.winfo_exists():
                    ventana.mostrar(clave)
                    ventana._al_frente()
                    return ventana
            except tk.TclError:
                pass
        ventana = cls(parent.winfo_toplevel(), clave)
        cls._instancia = ventana
        return ventana

    def __init__(self, parent, clave):
        super().__init__(parent)
        self._raiz = parent
        self._after = None
        self._destruida = False
        self._grab_anterior = None
        self.configure(fg_color=TemaArgos.FONDO)
        self.title("Argos — Recomendación")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        esc = self._get_window_scaling()
        izq, arriba, der, abajo = ToastArgos._area_trabajo(self)
        w = min(980, int((der - izq - 32) / esc))
        h = min(620, int((abajo - arriba - 60) / esc))
        x = izq + (der - izq - round(w * esc)) // 2
        y = arriba + (abajo - arriba - round(h * esc)) // 2
        self.geometry(f"{w}x{h}{x:+d}{y:+d}")
        self._cw, self._ch = round(w * 0.54 * esc), round((h - 32) * esc)
        self.canvas = tk.Canvas(self, width=self._cw, height=self._ch,
                                bg=TemaArgos.PANEL, highlightthickness=1,
                                highlightbackground=TemaArgos.LINEA, bd=0)
        self.canvas.place(x=round(12 * esc), y=round(16 * esc))
        self.panel = ctk.CTkScrollableFrame(self, fg_color=TemaArgos.PANEL,
                                          border_color=TemaArgos.LINEA, border_width=1,
                                          corner_radius=TemaArgos.RADIO_CARD)
        self.panel.place(relx=0.57, y=16, relwidth=0.415, relheight=0.94)
        self.mostrar(clave)
        self._al_frente()
        self._after = self.after(33, self._tick)

    def _al_frente(self):
        self._raiz.deiconify()
        self.deiconify()
        self.lift()
        self.focus_force()
        # El aviso severo existente puede tener un grab. Transferirlo solo
        # mientras se lee la guía para que no bloquee sus controles.
        anterior = self.grab_current()
        if anterior is not None and anterior is not self:
            self._grab_anterior = anterior
            self.grab_set()

    @classmethod
    def _preparar(cls, nivel, ancho, alto):
        clave = (nivel, ancho, alto)
        if clave in cls._cache:
            return cls._cache[clave]
        with Image.open(os.path.join(ASSETS_DIR, "recomendaciones",
                                     nivel.lower() + "_original.png")) as archivo:
            original = archivo.convert("RGBA")
        fondo = Image.new("RGBA", original.size, TemaArgos.PANEL)
        dibujo = ImageDraw.Draw(fondo)
        if nivel == "Severa":
            dibujo.rounded_rectangle((26, 26, 1228, 1228), radius=160, fill="white")
        elif nivel == "Moderada":
            dibujo.rounded_rectangle((8, 8, 1528, 1016), radius=55, fill="#193C2D")
        fondo.alpha_composite(original)
        escala = min((ancho - 16) / original.width, (alto - 16) / original.height)
        tam = (round(original.width * escala), round(original.height * escala))
        base = fondo.resize(tam, Image.Resampling.LANCZOS)
        frames = [base]
        if nivel == "Leve":
            # Los párpados se dibujan ya al tamaño final (con las medidas de los
            # ojos escaladas): a 1254 px tardaba ~6 s, así es ~10 veces más rápido.
            chica = original.resize(tam, Image.Resampling.LANCZOS)
            ojos = [(cx * escala, cy * escala, a * escala, b * escala, e * escala)
                    for cx, cy, a, b, e in OJOS_RECO_LEVE]
            frames = []
            for i in range(10):
                compuesto = Image.new("RGBA", tam, TemaArgos.PANEL)
                compuesto.alpha_composite(parpadeo_parametrico(chica, ojos, i / 9))
                frames.append(compuesto)
        else:
            # Silueta aproximada: incluye los brazos reales de Moderada (más
            # anchos que la caja orientativa) y excluye las tres sugerencias.
            mascara = Image.new("L", original.size, 0)
            d = ImageDraw.Draw(mascara)
            if nivel == "Moderada":
                d.polygon([(95, 470), (180, 440), (540, 640), (525, 505),
                           (605, 405), (715, 385), (810, 425), (850, 545),
                           (840, 655), (1220, 625), (1290, 545), (1350, 560),
                           (1370, 680), (1020, 865), (995, 978), (490, 978),
                           (450, 855), (175, 655)], fill=255)
                # El recorte no debe llevarse pedazos del aro de las sugerencias.
                for ccx, ccy, cr in cls.CIRCULOS["Moderada"]:
                    d.ellipse((ccx - cr - 22, ccy - cr - 22, ccx + cr + 22, ccy + cr + 22), fill=0)
            else:
                d.rounded_rectangle((940, 485, 1145, 825), radius=60, fill=255)
            mascara = mascara.filter(ImageFilter.GaussianBlur(10)).resize(tam, Image.Resampling.LANCZOS)
            personaje = base.copy()
            personaje.putalpha(mascara)
            # Fondo sin la figura original, para que no se duplique cuando el
            # recorte se desplaza o rota. Moderada: se reconstruye el verde
            # difuso con inpainting en una zona algo más amplia que la silueta
            # (un desenfoque común arrastraba el gris del personaje y dejaba
            # siluetas fantasma). Severa: fondo blanco liso.
            if nivel == "Moderada":
                zona = np.array(mascara) > 8
                zona = cv2.dilate(zona.astype(np.uint8) * 255,
                                  np.ones((max(3, round(46 * escala)),) * 2, np.uint8))
                # Sin tocar los círculos de sugerencias: el inpainting estiraba
                # su aro verde en manchas junto a los puños.
                for ccx, ccy, cr in cls.CIRCULOS["Moderada"]:
                    cv2.circle(zona, (round(ccx * escala), round(ccy * escala)),
                               round((cr + 14) * escala), 0, -1)
                rgb = np.array(base.convert("RGB"))
                reconstruido = cv2.inpaint(rgb, zona, max(3, round(18 * escala)), cv2.INPAINT_TELEA)
                reconstruido = cv2.GaussianBlur(reconstruido, (0, 0), max(2, 14 * escala))
                relleno = Image.fromarray(reconstruido).convert("RGBA")
                zona_suave = Image.fromarray(zona).filter(ImageFilter.GaussianBlur(max(2, round(8 * escala))))
                limpio = base.copy()
                limpio.paste(relleno, (0, 0), zona_suave)
            else:
                limpio = base.copy()
                limpio.paste(Image.new("RGBA", tam, "white"), (0, 0), mascara)
            frames = []
            pivote = (round(760 * escala), round(1000 * escala))
            # Franja inferior del marco fija: el personaje se corta contra ella
            # y el borde no acompaña el balanceo.
            corte = round(968 * escala) if nivel == "Moderada" else None
            franja = base.crop((0, corte, tam[0], tam[1])) if corte else None
            for i in range(24):
                seno = math.sin(i * math.tau / 24)
                capa = personaje
                if nivel == "Moderada":
                    capa = personaje.rotate(3 * seno, Image.Resampling.BICUBIC,
                                             center=pivote)
                cuadro = limpio.copy()
                sube = 4 if nivel == "Moderada" else 7
                cuadro.alpha_composite(capa, (0, round(-sube * escala * seno)))
                if franja is not None:
                    cuadro.paste(franja, (0, corte))
                frames.append(cuadro)
        iconos = []
        for cx, cy, radio in cls.CIRCULOS[nivel]:
            r = round(radio * escala)
            x, y = round(cx * escala), round(cy * escala)
            recorte = base.crop((x - r, y - r, x + r, y + r))
            mask = Image.new("L", recorte.size, 0)
            ImageDraw.Draw(mask).ellipse((1, 1, 2*r-1, 2*r-1), fill=255)
            recorte.putalpha(mask)
            oscuro = Image.new("RGBA", recorte.size, TemaArgos.PANEL)
            oscuro = Image.blend(recorte, oscuro, 0.72)
            oscuro.putalpha(mask)
            pulsos, aparicion = [], []
            for i in range(12):
                factor = 1 + 0.06 * i / 11
                pulsos.append(recorte.resize((round(2*r*factor), round(2*r*factor)),
                                             Image.Resampling.LANCZOS))
                t = i / 11
                factor = 0.6 + 0.45 * t / 0.75 if t < 0.75 else 1.05 - 0.05*(t-0.75)/0.25
                pop = recorte.resize((round(2*r*factor), round(2*r*factor)), Image.Resampling.LANCZOS)
                pop.putalpha(pop.getchannel("A").point(lambda a, t=t: round(a*t)))
                aparicion.append(pop)
            iconos.append((oscuro, pulsos, aparicion))
        resultado = (frames, iconos, escala, tam)
        # Acotar memoria si cambia la resolución entre sesiones.
        if len(cls._cache) >= 6:
            cls._cache.pop(next(iter(cls._cache)))
        cls._cache[clave] = resultado
        return resultado

    def mostrar(self, clave):
        self.clave = clave
        self.nivel = "Leve" if clave == "BajaFrecuencia" else clave
        self.color = GestorAlertas.COLORES[self.nivel]
        self._inicio = None
        self._terminado = False
        self._etapa = -1
        self._mostrada = time.monotonic()
        self._parpadeo = self._mostrada
        self._proximo_parpadeo = self._mostrada + random.uniform(3, 5)
        self._topmost_hasta = self._mostrada + 1.5
        self.attributes("-topmost", True)
        for widget in self.panel.winfo_children():
            widget.destroy()
        self.canvas.delete("all")
        self._frames, self._iconos = [], []
        try:
            frames, iconos, self._escala, tam = self._preparar(self.nivel, self._cw, self._ch)
            self._frames = [ImageTk.PhotoImage(img, master=self) for img in frames]
            self._iconos = [(ImageTk.PhotoImage(osc, master=self),
                             [ImageTk.PhotoImage(img, master=self) for img in pul],
                             [ImageTk.PhotoImage(img, master=self) for img in pop])
                            for osc, pul, pop in iconos]
            self._ox, self._oy = (self._cw-tam[0])/2, (self._ch-tam[1])/2
            self._imagen = self.canvas.create_image(self._ox, self._oy, anchor="nw", image=self._frames[0])
        except (OSError, ValueError) as exc:
            self.canvas.create_text(self._cw/2, self._ch/2, text="Ilustración no disponible",
                                    fill=TemaArgos.TEXTO)
            print(f"DEBUG recomendación: {exc}")
        textos = self._textos
        self._label(textos["titulo"], 23, self.color, "bold")
        self._label(textos["subtitulo"], 13, TemaArgos.TEXTO)
        self._label(textos["descripcion"], 12)
        self._filas = [self._label(f"{i+1}. {paso}", 13) for i, paso in enumerate(textos["pasos"])]
        self._estado = self._label(textos["espera"], 14)
        self._reloj = self._label("", 30, self.color, "bold")
        self._barra = ctk.CTkProgressBar(self.panel, progress_color=self.color,
                                        fg_color=TemaArgos.LINEA)
        self._barra.pack(fill="x", padx=12, pady=8)
        self._barra.set(0)
        self._duracion = tk.StringVar(master=self, value="2" if self.nivel == "Moderada" else "10")
        self._selector = None
        if self.nivel != "Leve":
            self._label("Duración (minutos)", 12)
            self._selector = ctk.CTkSegmentedButton(self.panel, values=["2", "3", "5"] if self.nivel == "Moderada" else ["10", "15"],
                                                   variable=self._duracion, selected_color=TemaArgos.ACENTO)
            self._selector.pack(fill="x", padx=12, pady=6)
        self._iniciar_btn = ctk.CTkButton(self.panel, text=textos["iniciar"],
                                         command=self._iniciar, fg_color=TemaArgos.ACENTO,
                                         hover_color=TemaArgos.ACENTO_VIVO)
        self._iniciar_btn.pack(fill="x", padx=12, pady=8)
        self._recordar_btn = ctk.CTkButton(self.panel, text=f"Recordarme en {textos['recordar']} min",
                                          command=self._recordar,
                                          fg_color=TemaArgos.ACENTO, hover_color=TemaArgos.ACENTO_VIVO)
        self._cerrar_btn = ctk.CTkButton(self.panel, text="Cerrar", command=self.destroy,
                                         fg_color=TemaArgos.PANEL_ALTO)
        self._cerrar_btn.pack(fill="x", padx=12, pady=8)
        pie = self._label(textos["pie"], 11, TemaArgos.ALERTA if textos["pie_destacado"]
                          else TemaArgos.TEXTO_TENUE)
        if textos["pie_destacado"]:
            pie.configure(fg_color=TemaArgos.PANEL_ALTO)

    def _label(self, texto, tam, color=None, peso="normal"):
        label = ctk.CTkLabel(self.panel, text=texto, font=TemaArgos.ui(tam, peso),
                             text_color=color or TemaArgos.TEXTO_SUAVE, anchor="w",
                             justify="left", wraplength=max(160, self._cw/self._get_window_scaling()*0.64),
                             corner_radius=TemaArgos.RADIO_CARD)
        label.pack(fill="x", padx=12, pady=6)
        return label

    def _iniciar(self):
        self._inicio = time.monotonic()
        self._etapa = -2  # También refrescar la instrucción tras la vista previa.
        self._parpadeo = self._inicio
        self._total = 29 if self.nivel == "Leve" else int(self._duracion.get()) * 60
        self._iniciar_btn.configure(state="disabled")
        if self._selector:
            self._selector.configure(state="disabled")

    def _recordar(self):
        """Recordatorio pedido por el usuario: solo los avisos (app y Windows)
        del nivel, con el enlace a esta pantalla; sin sonido ni ventana modal."""
        raiz, clave, nivel = self._raiz, self.clave, self.nivel
        minutos = self._textos["recordar"]
        def avisar():
            if raiz.winfo_exists():
                gestor = getattr(getattr(raiz, "monitoreo", None), "alertas", None)
                if gestor is None:
                    gestor = GestorAlertas(raiz)
                texto, fuente = GestorAlertas.RECOMENDACIONES.get(clave, ("", ""))
                gestor.notificar(f"Recordatorio · {self.TEXTOS[nivel]['titulo']}", texto, fuente,
                                 GestorAlertas.COLORES[nivel],
                                 os.path.join(ASSETS_DIR, "alertas", GestorAlertas.IMAGENES[clave]),
                                 GestorAlertas.ACCIONES.get(clave, texto), nivel, clave)
        anterior = getattr(raiz, "_recordatorio_recomendacion", None)
        if anterior:
            raiz.after_cancel(anterior)
        raiz._recordatorio_recomendacion = raiz.after(minutos * 60 * 1000, avisar)
        self._recordar_btn.configure(text=f"Recordatorio programado en {minutos} min",
                                     state="disabled")

    def _punto(self, x, y):
        return self._ox + x*self._escala, self._oy + y*self._escala

    def _circulo(self, x, y, radio):
        cx, cy = self._punto(x, y)
        r = radio*self._escala
        return cx-r, cy-r, cx+r, cy+r

    def _tick(self):
        self._after = None
        if self._destruida:
            return
        ahora = time.monotonic()
        t = ahora - self._mostrada
        if self._topmost_hasta and ahora >= self._topmost_hasta:
            self.attributes("-topmost", False)
            self._topmost_hasta = None
        transcurrido = max(0, ahora-self._inicio) if self._inicio is not None else 0
        activo = self._inicio is not None and not self._terminado
        etapa = -1
        restante = 0
        if activo:
            restante = max(0, math.ceil(self._total-transcurrido))
            etapa = (0 if transcurrido < 4 else 1 if transcurrido < 9 else 2) if self.nivel == "Leve" else int(transcurrido//20) % 3
            if transcurrido >= self._total:
                self._terminado = True
                activo = False
                etapa = 3
                self._estado.configure(text=self._textos["final"])
                self._recordar_btn.pack(fill="x", padx=12, pady=8, before=self._cerrar_btn)
            self._barra.set(min(1, transcurrido/self._total))
            cuenta = max(0, math.ceil(29-transcurrido)) if self.nivel == "Leve" and etapa >= 2 else restante
            self._reloj.configure(text=(str(cuenta) if self.nivel == "Leve" and etapa >= 2 else
                                       f"{restante//60:02d}:{restante%60:02d}") if self.nivel != "Leve" or etapa >= 2 else "")
        elif self._terminado:
            etapa = 3
        elif self.nivel == "Moderada":
            etapa = min(2, int(t/1.2))
        if etapa != self._etapa:
            self._etapa = etapa
            self._parpadeo = ahora
            for i, fila in enumerate(self._filas):
                hecho = etapa == 3 or (self.nivel == "Leve" and i < etapa)
                fila.configure(text=f"{'✓' if hecho else str(i+1)+'.'} {self._textos['pasos'][i]}",
                               fg_color=TemaArgos.PANEL_ALTO if i == etapa else "transparent",
                               text_color=TemaArgos.OK if hecho else self.color if i == etapa else TemaArgos.TEXTO_SUAVE)
            if activo:
                self._estado.configure(text=self._textos["activos"][etapa])
        self.canvas.delete("animacion")
        if self._frames:
            if ahora >= self._proximo_parpadeo:
                self._parpadeo = ahora
                self._proximo_parpadeo = ahora + random.uniform(3, 5)
            dt = ahora-self._parpadeo
            k = dt/0.09 if dt < 0.09 else max(0, 1-(dt-0.09)/0.14)
            indice = round(min(1, k)*9) if self.nivel == "Leve" else int(t/2.4*24) % 24
            self.canvas.itemconfigure(self._imagen, image=self._frames[indice])
            for i, (cx, cy, r) in enumerate(self.CIRCULOS[self.nivel]):
                oscuro, pulsos, pop = self._iconos[i]
                hecho = etapa == 3 or (self.nivel == "Leve" and i < etapa)
                imagen = pulsos[0] if hecho else oscuro
                if i == etapa:
                    imagen = pulsos[round((math.sin(t*3)+1)*5.5)]
                if self.nivel == "Moderada":
                    aparicion = (t-i*1.2)/0.65
                    if aparicion < 1:
                        self.canvas.create_image(*self._punto(cx, cy), image=oscuro, tags="animacion")
                        imagen = pop[max(0, min(11, int(aparicion*11)))]
                self.canvas.create_image(*self._punto(cx, cy), image=imagen, tags="animacion")
                if hecho:
                    self.canvas.create_text(*self._punto(cx+r*0.65, cy-r*0.65), text="✓",
                                            fill=TemaArgos.OK, font=("Segoe UI", 22, "bold"), tags="animacion")
                if self.nivel == "Severa" and i == etapa and activo:
                    self.canvas.create_oval(*self._circulo(cx, cy, r*(1.02+0.03*math.sin(t*4))),
                                            outline=self.color, width=3, tags="animacion")
                    desplazamiento = 40*math.sin(t*3)
                    if i < 2:
                        ax, ay = (cx+desplazamiento, cy+60) if i == 0 else (cx+60, cy+desplazamiento)
                        inicio = self._punto(ax-45 if i == 0 else ax, ay-45 if i == 1 else ay)
                        fin = self._punto(ax+45 if i == 0 else ax, ay+45 if i == 1 else ay)
                        self.canvas.create_line(*inicio, *fin, fill=self.color, width=4, arrow=tk.BOTH, tags="animacion")
                    else:
                        angulo = t*100 % 360
                        self.canvas.create_arc(*self._circulo(cx, cy, 90), start=angulo, extent=260,
                                               style=tk.ARC, outline=self.color, width=4, tags="animacion")
                        rad = math.radians(angulo+260)
                        ex, ey = cx+90*math.cos(rad), cy-90*math.sin(rad)
                        self.canvas.create_line(*self._punto(ex-14*math.sin(rad), ey-14*math.cos(rad)),
                                                *self._punto(ex, ey), arrow=tk.LAST, fill=self.color, width=4, tags="animacion")
            if self.nivel == "Leve" and activo:
                if etapa == 1:
                    f = (transcurrido-4) % 1.5 / 1.5
                    self.canvas.create_oval(*self._circulo(660+325*f, 520+90*f, 12),
                                            fill="#E5FFD8", outline=self.color, tags="animacion")
                elif etapa == 2:
                    self.canvas.create_arc(*self._circulo(948, 981, 140), start=90,
                                           extent=-359.9*max(0, (29-transcurrido)/20), style=tk.ARC,
                                           outline=self.color, width=5, tags="animacion")
            elif self.nivel == "Severa":
                caja = self._circulo(977, 282, 125)
                self.canvas.create_oval(*caja, fill="white", outline="white", tags="animacion")
                fraccion = max(0, 1-transcurrido/self._total) if self._inicio is not None else 1
                self.canvas.create_arc(*caja, start=90, extent=-359.9*fraccion,
                                       fill=self.color, outline=self.color, tags="animacion")
                segundos = restante if self._inicio is not None else int(self._duracion.get())*60
                self.canvas.create_text(*self._punto(977, 282), text=f"{segundos//60:02d}:{segundos%60:02d}",
                                        fill=TemaArgos.FONDO, font=("Consolas", max(13, round(45*self._escala)), "bold"), tags="animacion")
        self._after = self.after(33, self._tick)

    def destroy(self):
        self._destruida = True
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        if type(self)._instancia is self:
            type(self)._instancia = None
        if self._grab_anterior is not None:
            try:
                self.grab_release()
                if self._grab_anterior.winfo_exists():
                    self._grab_anterior.grab_set()
            except tk.TclError:
                pass
        super().destroy()


class ToastArgos(ctk.CTkToplevel):
    """Aviso propio en la esquina inferior derecha, por encima de otras ventanas.

    Respaldo del toast nativo de Windows: si el usuario tiene el Asistente de
    concentración activo, o las notificaciones de la app silenciadas, el toast
    del sistema no aparece y tampoco da error. Este siempre se ve.

    Lleva el personaje del nivel con los ojos animados: parpadea rápido en
    Leve, lento y pesado en Moderada, y en Severa intenta abrir los ojos y se
    le vuelven a cerrar. Entra con fundido y deslizamiento; una barra muestra
    el tiempo que queda y pasar el mouse lo pausa."""

    ANCHO, ALTO = 400, 132
    DURACION_MS = 9000
    AVATAR = 76            # px lógicos
    TICK_MS = 16

    # Zona de cada ojo en las imágenes de assets/alertas (512 px): elipses que
    # empiezan debajo de las cejas, comunes a los cuatro personajes.
    OJOS = [(172, 211, 240, 266), (272, 211, 340, 266)]
    NIVELES_K = 13          # cuadros entre ojo abierto (0) y cerrado (1)

    # Parpadeo por nivel: ms de cierre, pausa y apertura; apertura→cierre
    # (desde/hasta, 0 = abierto, 1 = cerrado); espera entre parpadeos (s).
    PERFILES = {
        "Leve":     dict(cierre=90,  pausa=50,  apertura=140, desde=0.0, hasta=1.0,
                         espera=(2.2, 4.0), primera=0.7, doble=0.20),
        "Moderada": dict(cierre=200, pausa=170, apertura=340, desde=0.0, hasta=1.0,
                         espera=(1.8, 3.0), primera=0.6, doble=0.0),
        "Severa":   dict(cierre=380, pausa=260, apertura=240, desde=1.0, hasta=0.5,
                         espera=(1.6, 2.8), primera=0.8, doble=0.0),
    }
    _cache_cuadros = {}     # (imagen, nivel, lado) -> [PhotoImage]; se arma una vez

    def __init__(self, parent, titulo, cuerpo, fuente, color, imagen=None, nivel=None, clave=None):
        super().__init__(parent)
        self._recomendacion_parent = parent
        self._clave_recomendacion = clave or nivel or "Leve"
        self.overrideredirect(True)
        self.configure(fg_color=TemaArgos.PANEL)
        try:
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.0)
        except Exception:
            pass

        # Posición en píxeles físicos: CTk escala el tamaño pero no la posición,
        # y winfo_screenwidth() devuelve unidades lógicas (1536 en vez de 1920
        # al 125 %). Se usa el área de trabajo de Windows (sin la barra de tareas).
        esc = self._get_window_scaling()
        _, _, der, abajo = self._area_trabajo()
        self._x_final = der - round(self.ANCHO * esc) - round(16 * esc)
        self._y = abajo - round(self.ALTO * esc) - round(16 * esc)
        self._abajo = abajo
        self._desliz = round(36 * esc)
        self.geometry(f"{self.ANCHO}x{self.ALTO}+{self._x_final + self._desliz}+{self._y}")

        self._nivel = nivel
        self._vivo = True
        self._t0 = time.monotonic()
        self._restante_ms = self.DURACION_MS
        self._pausado = False
        self._ultimo_tick = self._t0

        # Franja de color: el nivel se reconoce antes de leer el texto.
        ctk.CTkFrame(self, width=4, fg_color=color, corner_radius=0).place(
            relx=0, rely=0, relheight=1)

        # Personaje del nivel (Canvas: permite animarlo sin recrear widgets).
        self._perfil = self.PERFILES.get(nivel, self.PERFILES["Leve"])
        self._frames = self._preparar_frames(imagen, nivel, esc)
        self._k = self._perfil["desde"]
        self._parpadeo_t0 = self._perfil["primera"]          # s desde la aparición
        self._dobles = 0
        lado = round(self.AVATAR * esc)
        self._lienzo = tk.Canvas(self, width=lado, height=lado, bg=TemaArgos.PANEL,
                                 highlightthickness=0, bd=0)
        texto_x = 18
        if self._frames:
            self._lienzo.place(x=round(16 * esc), y=round(((self.ALTO - self.AVATAR) / 2 - 4) * esc))
            self._centro = lado / 2
            self._item = self._lienzo.create_image(self._centro, self._centro,
                                                   image=self._frame(self._k))
            texto_x = 16 + self.AVATAR + 12

        cuerpo_fr = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo_fr.pack(fill="both", expand=True, padx=(texto_x, 14), pady=(12, 14))
        ancho_txt = self.ANCHO - texto_x - 20

        fila = ctk.CTkFrame(cuerpo_fr, fg_color="transparent")
        fila.pack(fill="x")
        ctk.CTkLabel(fila, text=titulo, font=TemaArgos.ui(13, "bold"),
                     text_color=color, anchor="w", justify="left",
                     wraplength=ancho_txt - 30).pack(side="left")
        ctk.CTkButton(fila, text="✕", width=22, height=22, font=TemaArgos.ui(11),
                      fg_color="transparent", hover_color=TemaArgos.PANEL_ALTO,
                      text_color=TemaArgos.TEXTO_TENUE,
                      corner_radius=TemaArgos.RADIO,
                      command=self._cerrar).pack(side="right", anchor="n")

        ctk.CTkLabel(cuerpo_fr, text=cuerpo, font=TemaArgos.ui(11),
                     text_color=TemaArgos.TEXTO_SUAVE, anchor="w",
                     justify="left", wraplength=ancho_txt).pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(cuerpo_fr, text=fuente, font=TemaArgos.dato(9),
                     text_color=TemaArgos.TEXTO_TENUE, anchor="w",
                     justify="left", wraplength=ancho_txt).pack(fill="x", pady=(6, 0))

        def enlazar_cuerpo(widget):
            if isinstance(widget, ctk.CTkButton):
                return
            widget.bind("<Button-1>", self._abrir_recomendacion, add="+")
            # CTkLabel.bind ya cubre sus componentes internos.
            if isinstance(widget, (ctk.CTkFrame, tk.Frame)):
                for hijo in widget.winfo_children():
                    if isinstance(hijo, (ctk.CTkFrame, ctk.CTkLabel)):
                        enlazar_cuerpo(hijo)
        enlazar_cuerpo(cuerpo_fr)
        self._lienzo.bind("<Button-1>", self._abrir_recomendacion)
        ctk.CTkButton(cuerpo_fr, text="Ver recomendación", height=26,
                      fg_color=TemaArgos.ACENTO, hover_color=TemaArgos.ACENTO_VIVO,
                      command=self._abrir_recomendacion).pack(fill="x", pady=(6, 0))

        # Barra de tiempo restante, abajo de todo.
        self._barra = tk.Canvas(self, height=max(2, round(3 * esc)), bg=TemaArgos.PANEL,
                                highlightthickness=0, bd=0)
        self._barra.place(relx=0, rely=1, relwidth=1, anchor="sw")
        self._barra_item = self._barra.create_rectangle(0, 0, 0, 10, fill=color, width=0)

        # El texto puede pedir más alto que el previsto: crecer, nunca cortar.
        self.update_idletasks()
        alto = max(self.ALTO, math.ceil(cuerpo_fr.winfo_reqheight() / esc) + 26)
        if alto != self.ALTO:
            self._y = self._abajo - round(alto * esc) - round(16 * esc)
            self.geometry(f"{self.ANCHO}x{alto}+{self._x_final + self._desliz}+{self._y}")

        for w in (self,):
            w.bind("<Enter>", lambda e: self._pausar(True), add="+")
            w.bind("<Leave>", lambda e: self._pausar(False), add="+")
        self._after = self.after(self.TICK_MS, self._tick)

    def _abrir_recomendacion(self, event=None):
        if not self._vivo:
            return
        VentanaRecomendacion.abrir(self._recomendacion_parent, self._clave_recomendacion)
        # Se oculta ya pero se destruye después: CTkToplevel guarda el widget
        # con foco (este aviso) ~200 ms después de crear la ventana nueva y
        # luego le devuelve el foco; si ya no existe, Tk lanza "bad window path".
        try:
            self.attributes("-alpha", 0.0)
        except Exception:
            pass
        self.after(700, self._cerrar)

    def _area_trabajo(self):
        """(izq, arriba, der, abajo) del área de trabajo en píxeles físicos."""
        try:
            from ctypes import wintypes
            r = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
        esc = self._get_window_scaling()
        return 0, 0, round(self.winfo_screenwidth() * esc), round(self.winfo_screenheight() * esc)

    # ── Cuadros del personaje ─────────────────────────
    @classmethod
    def _cuadro_ojos(cls, base, abierto, cerrado, k, mascara):
        """Ojos a k de cerrarse (0 abierto, 1 cerrado), pegados sobre 'base'.
        Dentro de cada elipse el ojo abierto se aplasta hacia la línea inferior
        (el párpado baja) y al final se funde con los ojos cerrados reales."""
        aplastado = abierto.copy()
        for x0, y0, x1, y1 in cls.OJOS:
            alto = y1 - y0
            nuevo = max(1, round(alto * (1 - 0.85 * k)))
            trozo = abierto.crop((x0, y0, x1, y1)).resize((x1 - x0, nuevo),
                                                          Image.Resampling.LANCZOS)
            zona = cerrado.crop((x0, y0, x1, y1))
            zona.alpha_composite(trozo, (0, alto - nuevo - round(alto * 0.12 * k)))
            aplastado.paste(zona, (x0, y0))
        ojos = Image.blend(aplastado, cerrado, min(1.0, max(0.0, (k - 0.55) / 0.40)))
        resultado = base.copy()
        resultado.paste(ojos, (0, 0), mascara)
        return resultado

    def _preparar_frames(self, imagen, nivel, esc):
        if not imagen or not os.path.isfile(imagen):
            return None
        lado = round(self.AVATAR * esc)
        clave = (imagen, nivel, lado)
        if clave in self._cache_cuadros:
            return self._cache_cuadros[clave]
        carpeta = os.path.dirname(imagen)
        try:
            abrir = lambda n: Image.open(os.path.join(carpeta, n)).convert("RGBA")
            base = Image.open(imagen).convert("RGBA")
            cerrado = abrir("fatiga_severa.png")
            # Severa ya tiene los ojos cerrados: los "intentos de abrir" usan
            # los ojos entrecerrados de Moderada, sobre la imagen roja.
            abierto = abrir("fatiga_moderada.png") if nivel == "Severa" else base
            if base.size != cerrado.size or base.size != abierto.size:
                raise ValueError("tamaños distintos")
            mascara = Image.new("L", base.size, 0)
            dibujo = ImageDraw.Draw(mascara)
            for caja in self.OJOS:
                dibujo.ellipse(caja, fill=255)
            mascara = mascara.filter(ImageFilter.GaussianBlur(4))
            cuadros = []
            for i in range(self.NIVELES_K):
                k = i / (self.NIVELES_K - 1)
                img = self._cuadro_ojos(base, abierto, cerrado, k, mascara)
                cuadros.append(ImageTk.PhotoImage(
                    img.resize((lado, lado), Image.Resampling.LANCZOS)))
        except Exception as e:
            print(f"DEBUG ToastArgos sin animación de ojos: {e}")
            try:
                cuadros = [ImageTk.PhotoImage(Image.open(imagen).convert("RGBA").resize(
                    (lado, lado), Image.Resampling.LANCZOS))] * self.NIVELES_K
            except Exception:
                return None
        self._cache_cuadros[clave] = cuadros
        return cuadros

    def _frame(self, k):
        return self._frames[round(min(1.0, max(0.0, k)) * (self.NIVELES_K - 1))]

    def _k_parpadeo(self, t_s):
        """Apertura de los ojos en el instante t_s (s desde la aparición)."""
        p = self._perfil
        dt = (t_s - self._parpadeo_t0) * 1000
        if dt < 0:
            return p["desde"]
        c, h, a = p["cierre"], p["pausa"], p["apertura"]
        if dt < c:                                   # ease-in: el párpado cae
            f = (dt / c) ** 2
        elif dt < c + h:
            f = 1.0
        elif dt < c + h + a:                         # ease-out: se abre suave
            f = (1 - (dt - c - h) / a) ** 2
        else:
            # terminó: programar el próximo (a veces uno doble enseguida)
            if p["doble"] and self._dobles == 0 and random.random() < p["doble"]:
                self._dobles = 1
                self._parpadeo_t0 = t_s + 0.12
            else:
                self._dobles = 0
                self._parpadeo_t0 = t_s + random.uniform(*p["espera"])
            return p["desde"]
        return p["desde"] + (p["hasta"] - p["desde"]) * f

    # ── Animación ────────────────────────────────────
    def _tick(self):
        if not self._vivo:
            return
        ahora = time.monotonic()
        t = (ahora - self._t0) * 1000           # ms desde que apareció

        # Entrada: fundido + deslizamiento (220 ms, ease-out)
        k = min(1.0, t / 220)
        suave = 1 - (1 - k) ** 3
        try:
            self.attributes("-alpha", 0.97 * suave)
        except Exception:
            pass
        x = self._x_final + round(self._desliz * (1 - suave))
        self.geometry(f"+{x}+{self._y}")

        if self._frames:
            k = self._k_parpadeo(t / 1000)
            if abs(k - self._k) > 1e-3:
                self._k = k
                self._lienzo.itemconfigure(self._item, image=self._frame(k))

        # Tiempo restante (se congela con el mouse encima)
        dt = (ahora - self._ultimo_tick) * 1000
        self._ultimo_tick = ahora
        if not self._pausado:
            self._restante_ms -= dt
        ancho = self._barra.winfo_width()
        self._barra.coords(self._barra_item, 0, 0,
                           ancho * max(0.0, self._restante_ms) / self.DURACION_MS, 10)
        if self._restante_ms <= 0:
            self._cerrar()
            return
        self._after = self.after(self.TICK_MS, self._tick)

    def _pausar(self, pausado):
        # <Leave> también llega al pasar a un hijo: confirmar con el puntero.
        if not pausado:
            x, y = self.winfo_pointerxy()
            dentro = (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width()
                      and self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height())
            if dentro:
                return
        self._pausado = pausado

    def _cerrar(self):
        """Se desvanece (160 ms) y recién ahí se destruye."""
        if not self._vivo:
            return
        self._vivo = False
        try:
            self.after_cancel(self._after)
        except Exception:
            pass
        inicio = time.monotonic()
        alfa0 = float(self.attributes("-alpha") or 0.97)

        def paso():
            k = (time.monotonic() - inicio) / 0.16
            if k >= 1:
                try:
                    self.destroy()
                except Exception:
                    pass
                return
            try:
                self.attributes("-alpha", alfa0 * (1 - k))
                self.after(self.TICK_MS, paso)
            except Exception:
                pass
        paso()


class DialogoPausa(ctk.CTkToplevel):
    """Modal bloqueante. Solo para fatiga severa: exige una respuesta."""

    def __init__(self, parent, indice, perclos, bpm, recomendacion, fuente,
                 al_responder=None):
        super().__init__(parent)
        self.configure(fg_color=TemaArgos.PANEL)
        self.title("Argos — Fatiga severa")
        self.resizable(False, False)
        self.respuesta = None
        self._al_responder = al_responder  # se llama con la respuesta tras cerrar

        # Centrado en píxeles físicos (winfo_screenwidth() da unidades lógicas
        # y la ventana quedaba corrida hacia arriba a la izquierda).
        w, h = 520, 450
        esc = self._get_window_scaling()
        izq, arriba, der, abajo = ToastArgos._area_trabajo(self)
        x = izq + (der - izq - round(w * esc)) // 2
        y = arriba + (abajo - arriba - round(h * esc)) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        aplicar_icono(self)
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.protocol("WM_DELETE_WINDOW", lambda: self._responder("ignorar"))

        ctk.CTkFrame(self, height=3, fg_color=TemaArgos.RIESGO,
                     corner_radius=0).pack(fill="x")

        ctk.CTkLabel(self, text="F A T I G A   S E V E R A",
                     font=fuente_portada(22), text_color=TemaArgos.RIESGO).pack(pady=(24, 4))
        ctk.CTkFrame(self, height=1, width=250,
                     fg_color=TemaArgos.ACENTO).pack(pady=(0, 16))

        # Evidencia: la alerta muestra en qué se basa, no solo el veredicto.
        datos = ctk.CTkFrame(self, fg_color=TemaArgos.FONDO,
                              corner_radius=TemaArgos.RADIO_CARD,
                              border_width=1, border_color=TemaArgos.LINEA)
        datos.pack(fill="x", padx=28)
        for etiqueta, valor in (("Índice de fatiga", f"{indice:.0f} / 100"),
                                 ("PERCLOS", f"{perclos:.1f} %"),
                                 ("Frecuencia", f"{bpm} / min")):
            fila = ctk.CTkFrame(datos, fg_color="transparent")
            fila.pack(fill="x", padx=14, pady=5)
            ctk.CTkLabel(fila, text=etiqueta, font=TemaArgos.ui(11),
                         text_color=TemaArgos.TEXTO_TENUE, anchor="w").pack(side="left")
            ctk.CTkLabel(fila, text=valor, font=TemaArgos.dato(13),
                         text_color=TemaArgos.TEXTO, anchor="e").pack(side="right")

        ctk.CTkLabel(self, text=recomendacion, font=TemaArgos.ui(12),
                     text_color=TemaArgos.TEXTO_SUAVE, wraplength=440,
                     justify="left").pack(fill="x", padx=28, pady=(16, 6))
        ctk.CTkLabel(self, text=fuente, font=TemaArgos.dato(9),
                     text_color=TemaArgos.TEXTO_TENUE, wraplength=440,
                     justify="left").pack(fill="x", padx=28)

        botones = ctk.CTkFrame(self, fg_color="transparent")
        botones.pack(pady=(20, 0))
        ctk.CTkButton(botones, text="Tomar pausa ahora", width=170, height=36,
                      font=TemaArgos.ui(13, "bold"), fg_color=TemaArgos.ACENTO,
                      hover_color=TemaArgos.ACENTO_VIVO, text_color=TemaArgos.TEXTO,
                      corner_radius=TemaArgos.RADIO,
                      command=lambda: self._responder("pausa")).pack(side="left", padx=6)
        ctk.CTkButton(botones, text="Recordar en 5 min", width=150, height=36,
                      font=TemaArgos.ui(12), fg_color="transparent",
                      hover_color=TemaArgos.PANEL_ALTO, text_color=TemaArgos.TEXTO_SUAVE,
                      border_width=1, border_color=TemaArgos.ACENTO,
                      corner_radius=TemaArgos.RADIO,
                      command=lambda: self._responder("posponer")).pack(side="left", padx=6)

        # Acceso directo a la pausa guiada (antes solo desde las notificaciones).
        ctk.CTkButton(self, text="Ver recomendación", width=332, height=36,
                      font=TemaArgos.ui(13, "bold"), fg_color=GestorAlertas.COLORES["Severa"],
                      hover_color=TemaArgos.RIESGO, text_color=TemaArgos.TEXTO,
                      corner_radius=TemaArgos.RADIO,
                      command=lambda: self._responder("recomendacion")).pack(pady=(12, 0))

        self.lift()
        self.focus_force()
        self.grab_set()          # bloqueante: es el punto del canal

    def _responder(self, valor):
        self.respuesta = valor
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        if self._al_responder:
            self._al_responder(valor)


class GestorAlertas:
    """Decide qué canales de aviso disparar según la severidad de la fatiga.

    Cuatro canales que escalan con el nivel: visual dentro de la app (siempre),
    notificación del sistema, sonido y modal bloqueante. El escalado responde a
    la proporcionalidad entre severidad y disruptividad: un usuario levemente
    cansado no puede recibir el mismo aviso que uno con microsueños.

    Argos no es un dispositivo médico: los mensajes recomiendan prácticas
    preventivas con respaldo bibliográfico, y nunca diagnostican, indican
    tratamientos ni mencionan medicamentos.
    """

    ORDEN = {"Normal": 0, "Leve": 1, "Moderada": 2, "Severa": 3}

    # nivel -> (toast, sonido, modal)
    CANALES = {
        "Normal":   (False, None,     False),
        "Leve":     (True,  None,     False),
        "Moderada": (True,  "suave",  False),
        "Severa":   (True,  "fuerte", True),
    }

    # Segundos mínimos entre dos avisos del mismo nivel: sin esto el aviso se
    # repetiría en cada cuadro (~15 por segundo).
    COOLDOWN = {"Leve": 300, "Moderada": 180, "Severa": 120}

    COLORES = {"Leve": "#2E86DE", "Moderada": "#F1C40F",
               "Severa": "#E24B4A"}

    RECOMENDACIONES = {
        "Leve": (
            "Fatiga leve detectada. Se recomienda aplicar la regla 20-20-20: "
            "cada 20 minutos, mire durante 20 segundos un punto ubicado a 20 pies "
            "(unos 6 metros) de distancia.",
            "Basado en la regla 20-20-20 (American Optometric Association)."
        ),
        "Moderada": (
            "Fatiga moderada: considere una pausa. Se recomienda una pausa activa "
            "de 2 a 5 minutos: aléjese del monitor, parpadee de forma consciente "
            "y ajuste la iluminación del entorno si es posible.",
            "Basado en TFOS DEWS II (Wolffsohn et al., 2017) y Coles-Brennan et al. (2019)."
        ),
        "Severa": (
            "Fatiga severa: haga una pausa inmediata. Se recomienda interrumpir "
            "el uso de la pantalla durante 10 a 15 minutos y realizar ejercicios "
            "oculares. Si los síntomas persisten, considere consultar con un "
            "especialista.",
            "Basado en Coles-Brennan et al. (2019) y las recomendaciones de la AOA."
        ),
        # Disparador propio: frecuencia de parpadeo anormalmente baja. Se trata
        # con el canal de nivel leve aunque el índice todavía no haya subido.
        "BajaFrecuencia": (
            "Frecuencia de parpadeo baja. Parpadee de forma consciente durante "
            "30 segundos para restaurar la película lagrimal.",
            "Basado en TFOS DEWS II (Wolffsohn et al., 2017)."
        ),
    }

    def __init__(self, ventana):
        self.ventana        = ventana     # padre Tk para toasts y modal
        self.sonido_activo  = True
        self.toast_activo   = True
        self.modal_activo   = True
        self._ultimo_nivel  = "Normal"
        self._ultimo_aviso  = {}          # nivel -> timestamp
        self._modal_abierto = False
        self._pospuesto_hasta = 0.0

    # ── Entrada ──────────────────────────────────────
    def evaluar(self, nivel, indice, perclos, bpm):
        """Se llama en cada actualización de métricas. Solo dispara cuando el
        nivel sube o cuando venció el cooldown de ese nivel."""
        ahora = time.time()

        if nivel == "Normal":
            if 0 < bpm < 10:
                self._quizas_disparar("BajaFrecuencia", "Leve", indice, perclos, bpm, ahora)
            else:
                self._ultimo_nivel = nivel
            return

        subio = self.ORDEN.get(nivel, 0) > self.ORDEN.get(self._ultimo_nivel, 0)
        self._ultimo_nivel = nivel
        vencido = ahora - self._ultimo_aviso.get(nivel, 0) >= self.COOLDOWN.get(nivel, 300)
        if subio or vencido:
            self._quizas_disparar(nivel, nivel, indice, perclos, bpm, ahora)

    def _quizas_disparar(self, clave, nivel_canal, indice, perclos, bpm, ahora):
        if ahora < self._pospuesto_hasta:
            return
        if ahora - self._ultimo_aviso.get(clave, 0) < self.COOLDOWN.get(nivel_canal, 300):
            return
        self._ultimo_aviso[clave] = ahora
        self.disparar(clave, nivel_canal, indice, perclos, bpm)

    # ── Disparo ──────────────────────────────────────
    # Cuerpo corto para la notificación de Windows: solo la acción recomendada
    # (el título ya dice el nivel; el texto completo queda en el aviso propio).
    ACCIONES = {
        "Leve":           "Aplique la regla 20-20-20: cada 20 minutos, mire 20 segundos un punto a 6 metros.",
        "Moderada":       "Haga una pausa activa de 2 a 5 minutos y parpadee de forma consciente.",
        "Severa":         "Haga una pausa de 10 a 15 minutos y realice ejercicios oculares.",
        "BajaFrecuencia": "Parpadee de forma consciente durante 30 segundos.",
    }

    TITULOS = {
        "Leve":           "Fatiga leve detectada",
        "Moderada":       "Fatiga moderada — considerar pausa",
        "Severa":         "Fatiga severa — pausa inmediata",
        "BajaFrecuencia": "Frecuencia de parpadeo baja",
    }

    # Personaje del aviso por nivel (anillo del color del nivel). La baja
    # frecuencia usa el de leve: la lágrima indica ojo seco / irritación.
    IMAGENES = {
        "Normal":         "fatiga_normal.png",
        "Leve":           "fatiga_leve.png",
        "Moderada":       "fatiga_moderada.png",
        "Severa":         "fatiga_severa.png",
        "BajaFrecuencia": "fatiga_leve.png",
    }

    def disparar(self, clave, nivel_canal, indice, perclos, bpm):
        toast, sonido, modal = self.CANALES.get(nivel_canal, (False, None, False))
        texto, fuente = self.RECOMENDACIONES.get(clave, ("", ""))
        titulo = self.TITULOS.get(clave, "Argos")
        color = self.COLORES.get(nivel_canal, TemaArgos.ALERTA)
        imagen = os.path.join(ASSETS_DIR, "alertas", self.IMAGENES.get(clave, ""))

        if sonido and self.sonido_activo:
            self.reproducir(sonido)
        if toast and self.toast_activo:
            self.notificar(titulo, texto, fuente, color, imagen,
                           self.ACCIONES.get(clave, texto), nivel_canal, clave)
        if modal and self.modal_activo:
            self.abrir_modal(indice, perclos, bpm, texto, fuente)

    # ── Canal 3: sonido ──────────────────────────────
    # Sonidos del propio Windows en vez de tonos crudos: winsound.Beep genera
    # una onda cuadrada floja y poco reconocible, que con el volumen bajo
    # directamente no se escucha. Estos WAV son audibles y ya le resultan
    # familiares al usuario como "algo que pide atención".
    SONIDOS = {
        "suave":  [(r"C:\Windows\Media\Windows Notify System Generic.wav", 0.0)],
        "fuerte": [(r"C:\Windows\Media\Windows Exclamation.wav", 0.0),
                   (r"C:\Windows\Media\Windows Exclamation.wav", 0.55),
                   (r"C:\Windows\Media\Windows Foreground.wav",  1.10)],
    }

    def reproducir(self, tipo):
        """En hilo aparte: reproducir bloquea, y bloquear acá congelaría el
        bucle de video."""
        def _sonar():
            secuencia = self.SONIDOS.get(tipo, self.SONIDOS["suave"])
            reproducido = False
            inicio = time.time()
            for ruta, retardo in secuencia:
                espera = retardo - (time.time() - inicio)
                if espera > 0:
                    time.sleep(espera)
                if os.path.exists(ruta):
                    try:
                        winsound.PlaySound(ruta, winsound.SND_FILENAME | winsound.SND_ASYNC)
                        reproducido = True
                    except Exception:
                        pass
            if not reproducido:
                # Sin los WAV del sistema: tono generado, mejor que nada.
                try:
                    if tipo == "suave":
                        winsound.Beep(660, 220)
                    else:
                        for frec in (880, 880, 1046):
                            winsound.Beep(frec, 260)
                            time.sleep(0.06)
                except Exception:
                    try:
                        winsound.MessageBeep()
                    except Exception:
                        pass
        threading.Thread(target=_sonar, daemon=True).start()

    # ── Canal 2: notificación del sistema ────────────
    def notificar(self, titulo, cuerpo, fuente, color, imagen=None, cuerpo_corto=None,
                  nivel=None, clave=None):
        # Siempre mostramos el aviso propio: es el que garantiza que se vea.
        try:
            ToastArgos(self.ventana, titulo, cuerpo, fuente, color, imagen, nivel, clave)
        except Exception:
            pass
        threading.Thread(target=self._toast_windows,
                         args=(titulo, cuerpo_corto or cuerpo, imagen, clave or nivel), daemon=True).start()

    @staticmethod
    def _xml_toast(titulo, cuerpo, imagen=None, clave="Leve", recomendacion=True):
        """XML ToastGeneric. La imagen va como logo circular (appLogoOverride):
        el personaje del nivel con su anillo de color."""
        from xml.sax.saxutils import escape, quoteattr
        texto = lambda t: escape(t.replace("\n", " "))
        logo = ""
        if imagen and os.path.isfile(imagen):
            logo = (f'<image placement="appLogoOverride" hint-crop="circle" '
                    f'src={quoteattr(pathlib.Path(imagen).resolve().as_uri())}/>')
        clave = clave if clave in CLAVES_RECOMENDACION else "Leve"
        uri = quoteattr(f"argos://recomendacion/{clave}")
        apertura = f'<toast launch={uri} activationType="protocol">' if recomendacion else '<toast>'
        acciones = (f'<actions><action content="Ver recomendación" arguments={uri} '
                    'activationType="protocol"/></actions>') if recomendacion else ''
        return (apertura + '<visual><binding template="ToastGeneric">'
                f'<text>{texto(titulo)}</text>'
                f'<text>{texto(cuerpo)}</text>{logo}'
                f'</binding></visual>{acciones}</toast>')

    @staticmethod
    def _toast_windows(titulo, cuerpo, imagen=None, clave="Leve", recomendacion=True,
                       tag="argos-fatiga"):
        """Notificación nativa de Windows vía PowerShell. Puede no aparecer si
        el Asistente de concentración está activo; por eso nunca es el único
        canal. Silenciosa ante cualquier fallo."""
        xml = GestorAlertas._xml_toast(titulo, cuerpo, imagen, clave, recomendacion).replace("'", "''")
        tag_ps = tag.replace("'", "''")
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
            " ContentType = WindowsRuntime] | Out-Null; "
            "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument,"
            " ContentType = WindowsRuntime] | Out-Null; "
            "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; "
            f"$x.LoadXml('{xml}'); "
            f"$id = '{AUMID_TOAST}'; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($x); "
            f"$toast.Tag = '{tag_ps}'; $toast.Group = 'argos'; "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($id).Show($toast)"
        )
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                               timeout=12, capture_output=True)
            if r.returncode != 0:
                print(f"DEBUG toast Windows falló: {r.stderr.decode(errors='replace')[:300]}")
        except Exception:
            pass

    # ── Canal 4: modal bloqueante ────────────────────
    def abrir_modal(self, indice, perclos, bpm, texto, fuente):
        if self._modal_abierto:
            return
        self._modal_abierto = True
        # Sin wait_window: esperar acá frenaba la cadena after() del bucle de
        # video (la app quedaba congelada mientras el modal estaba abierto).
        # La respuesta llega por callback cuando el usuario cierra el diálogo.
        try:
            DialogoPausa(self.ventana, indice, perclos, bpm, texto, fuente,
                         al_responder=self._al_responder_modal)
        except Exception:
            self._modal_abierto = False

    def _al_responder_modal(self, respuesta):
        if respuesta == "posponer":
            self._pospuesto_hasta = time.time() + 300
        elif respuesta in ("pausa", "recomendacion"):
            # Ver la recomendación cuenta como tomar la pausa.
            self._pospuesto_hasta = time.time() + 600
        self._modal_abierto = False
        if respuesta == "recomendacion":
            VentanaRecomendacion.abrir(self.ventana, "Severa")

    # ── Prueba manual (para la defensa) ──────────────
    def probar(self, nivel):
        self._pospuesto_hasta = 0
        self.disparar(nivel, nivel, 84.0, 22.4, 7)

#==========================================================================================

class InterfazFatiga(ctk.CTkFrame):
    """Núcleo de monitoreo. Ya no es una ventana aparte: vive como panel dentro
    de la carcasa (MenuPrincipal), que aporta fondo, menú y encabezado."""

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

    def __init__(self, parent, perfil_nombre, perfil_id, perfil_rol, bd,
                 al_volver=None):
        super().__init__(parent, fg_color="transparent")
        print("DEBUG: InterfazFatiga.__init__ iniciado")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        # La carcasa nos pasa cómo volver al menú; ya no cerramos una ventana.
        self._al_volver = al_volver

        # Estado detección
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

        # Anti-falsos-positivos
        self.cooldown_hasta    = 0.0  # timestamp real hasta el que se ignoran nuevos cierres
        self.p_frames_max      = 15
        self.p_cooldown        = 4    # "cuadros" @ FPS_REFERENCIA (~0.13 s) — evita doble conteo por temblor del párpado al reabrir
        self.umbral_movimiento = 18  # px entre cuadros (nariz) para descartar giro de cabeza

        # Máquina de estados del parpadeo (baseline móvil, cierre por caída
        # relativa, clasificación y estados no evaluables): vive aparte para
        # poder probarla reproduciendo videos sin la interfaz.
        self.detector             = DetectorParpadeo()
        self.total_prolongados    = 0
        self.total_falsos         = 0
        self._ultimo_pitch        = None  # para sembrar la referencia de la auto-calibración

        # Calentamiento: PERCLOS y frecuencia usan ventanas de 60 s; antes de
        # completarlas la frecuencia da ~0/min y dispararía alertas falsas.
        self.CALENTAMIENTO_S      = 60.0
        self.deteccion_inicio     = None

        # FPS real (diagnóstico: resolución temporal de la medición de duración)
        self._fps    = 0.0
        self._fps_n  = 0
        self._fps_t0 = None
        self.debug_logger = None  # EARDebugLogger, solo con ARGOS_DEBUG=<escenario>

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

        # Gestor de alertas: la ventana raiz es el padre de toasts y modal.
        self.alertas = GestorAlertas(self.winfo_toplevel())

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
            min_tracking_confidence=0.6,
            output_facial_transformation_matrixes=True  # pose de cabeza (pitch/yaw)
        )
        self.face_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        # Timestamps reales (ms desde que se creó el modelo), siempre crecientes:
        # sumar 33 ms fijos con la cámara a ~15 FPS desajustaba el seguimiento.
        self._mp_t0          = time.time()
        self.timestamp_ms    = -1
        print("DEBUG: FaceLandmarker creado.")

    # ── Construcción UI ──────────────────────────────
    def _construir_ui(self):
        """Sin rail: la navegación vive en la carcasa. Este frame solo aloja
        las vistas, que ocupan todo el ancho disponible."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._nav_buttons = {}
        self._nav_icons   = []
        self._grafico_activo = False

        principal = ctk.CTkFrame(self, corner_radius=TemaArgos.RADIO,
                                  fg_color="transparent")
        principal.grid(row=0, column=0, sticky="nsew")

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
        """Detiene la captura y avisa a la carcasa. No destruye nada: el panel
        se conserva para no reinicializar MediaPipe en la próxima entrada."""
        self.sistema_activo = False

        if self.cap:
            self.cap.release()
            self.cap = None

        if callable(self._al_volver):
            self._al_volver()

    def _crear_nav_item(self, parent, key, icono_nombre, texto, command):
        """Botón de navegación estilo rail (ícono dibujado + texto, sin
        colores fuertes salvo cuando está activo)."""
        icono = cargar_icono(f"icon_nav_{icono_nombre}", (16, 16))
        self._nav_icons.append(icono)  # evitar garbage-collection de la imagen
        btn = ctk.CTkButton(parent, text="  " + texto, image=icono, anchor="w",
                             fg_color="transparent",
                             hover_color=TemaArgos.PANEL_ALTO,
                             text_color=TemaArgos.TEXTO_SUAVE,
                             font=TemaArgos.ui(12),
                             height=32, corner_radius=TemaArgos.RADIO,
                             command=command)
        btn.pack(fill="x", pady=1)
        self._nav_buttons[key] = btn
        return btn

    def _marcar_nav_activo(self, nombre):
        """Resalta el ítem de la sección visible. Sin esto el rail no da
        ninguna pista de dónde está parado el usuario."""
        for key, btn in self._nav_buttons.items():
            activo = (key == nombre)
            try:
                btn.configure(
                    fg_color=TemaArgos.PANEL_ALTO if activo else "transparent",
                    text_color=TemaArgos.TEXTO if activo else TemaArgos.TEXTO_SUAVE,
                    font=TemaArgos.ui(12, "bold" if activo else "normal"))
            except Exception:
                pass

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
        self._marcar_nav_activo(nombre)

        for key, btn in self._nav_buttons.items():
            activo = key == nombre
            btn.configure(fg_color="#1f4a6b" if activo else "transparent",
                          text_color="white" if activo else "#cccccc")

    def _construir_vista_control(self, tab):
        # ── Barra de acciones: lo que antes vivía en el rail lateral ──
        barra = ctk.CTkFrame(tab, fg_color="transparent")
        barra.pack(fill="x", pady=(0, 12))

        self.btn_iniciar = ctk.CTkButton(
            barra, text="Iniciar Detección", width=150, height=32,
            font=TemaArgos.ui(13, "bold"),
            fg_color=TemaArgos.ACENTO, hover_color=TemaArgos.ACENTO_VIVO,
            text_color=TemaArgos.TEXTO, corner_radius=TemaArgos.RADIO,
            command=self.toggle_sistema)
        self.btn_iniciar.pack(side="left", padx=(0, 8))

        self.btn_auto = ctk.CTkButton(
            barra, text="Auto-ajustar", width=120, height=32,
            font=TemaArgos.ui(12), fg_color="transparent",
            hover_color=TemaArgos.PANEL_ALTO, text_color=TemaArgos.TEXTO_SUAVE,
            border_width=1, border_color=TemaArgos.ACENTO,
            corner_radius=TemaArgos.RADIO,
            command=self._iniciar_auto_calibracion)
        self.btn_auto.pack(side="left", padx=(0, 8))

        self.btn_guia = ctk.CTkButton(
            barra, text="Prueba Guiada", width=126, height=32,
            font=TemaArgos.ui(12), fg_color="transparent",
            hover_color=TemaArgos.PANEL_ALTO, text_color=TemaArgos.TEXTO_SUAVE,
            border_width=1, border_color=TemaArgos.ACENTO,
            corner_radius=TemaArgos.RADIO,
            command=self._iniciar_prueba_guiada)
        self.btn_guia.pack(side="left")

        self.label_fps = ctk.CTkLabel(barra, text="0 FPS", font=TemaArgos.dato(11),
                                       text_color=TemaArgos.TEXTO_TENUE)
        self.label_fps.pack(side="right", padx=(10, 0))
        self.label_estado = ctk.CTkLabel(barra, text="INACTIVO", font=TemaArgos.dato(11),
                                          text_color=TemaArgos.TEXTO_TENUE)
        self.label_estado.pack(side="right")

        self.label_calib_estado = ctk.CTkLabel(tab, text="",
                                                text_color=TemaArgos.ALERTA,
                                                font=TemaArgos.ui(11, "bold"),
                                                anchor="w", justify="left")
        self.label_calib_estado.pack(fill="x", pady=(0, 6))

        cuerpo = ctk.CTkFrame(tab, fg_color="transparent")
        cuerpo.pack(fill="both", expand=True)
        cuerpo.grid_columnconfigure(0, weight=0)
        cuerpo.grid_columnconfigure(1, weight=1)
        cuerpo.grid_rowconfigure(0, weight=1)

        # Columna izquierda: métricas (ancho fijo, con scroll si no entra todo)
        columna = ctk.CTkScrollableFrame(cuerpo, fg_color="transparent", width=272)
        columna.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        # Card: interruptores de visualización
        card_sw = ctk.CTkFrame(columna, corner_radius=TemaArgos.RADIO_CARD,
                                fg_color=TemaArgos.PANEL, border_width=1,
                                border_color=TemaArgos.LINEA)
        card_sw.pack(fill="x", padx=2, pady=(0, 8))
        ctk.CTkLabel(card_sw, text="MOSTRAR EN PANTALLA", anchor="w",
                     font=TemaArgos.ui(9, "bold"), text_color=TemaArgos.TEXTO_TENUE).pack(
            fill="x", padx=12, pady=(10, 4))
        self.sw_camara = ctk.CTkSwitch(card_sw, text="Cámara", command=self._sw_camara,
                                        font=TemaArgos.ui(12),
                                        progress_color=TemaArgos.ACENTO)
        self.sw_camara.pack(anchor="w", padx=12, pady=(0, 6))   # apagado por defecto
        self.sw_metricas = ctk.CTkSwitch(card_sw, text="Métricas en vivo",
                                          command=self._sw_metricas,
                                          font=TemaArgos.ui(12),
                                          progress_color=TemaArgos.ACENTO)
        self.sw_metricas.select()                                # encendido por defecto
        self.sw_metricas.pack(anchor="w", padx=12, pady=(0, 10))

        # Card: canales de aviso. El sonido siempre debe poder apagarse —
        # en oficina compartida un beep recurrente es inaceptable.
        card_av = ctk.CTkFrame(columna, corner_radius=TemaArgos.RADIO_CARD,
                                fg_color=TemaArgos.PANEL, border_width=1,
                                border_color=TemaArgos.LINEA)
        card_av.pack(fill="x", padx=2, pady=(0, 8))
        ctk.CTkLabel(card_av, text="AVISOS DE FATIGA", anchor="w",
                     font=TemaArgos.ui(9, "bold"),
                     text_color=TemaArgos.TEXTO_TENUE).pack(fill="x", padx=12, pady=(10, 4))
        self.sw_sonido = ctk.CTkSwitch(card_av, text="Sonido",
                                        command=self._sw_sonido,
                                        font=TemaArgos.ui(12),
                                        progress_color=TemaArgos.ACENTO)
        self.sw_sonido.select()
        self.sw_sonido.pack(anchor="w", padx=12, pady=(0, 6))
        self.sw_toast = ctk.CTkSwitch(card_av, text="Notificaciones",
                                       command=self._sw_toast,
                                       font=TemaArgos.ui(12),
                                       progress_color=TemaArgos.ACENTO)
        self.sw_toast.select()
        self.sw_toast.pack(anchor="w", padx=12, pady=(0, 6))
        self.sw_modal = ctk.CTkSwitch(card_av, text="Aviso bloqueante (severa)",
                                       command=self._sw_modal,
                                       font=TemaArgos.ui(12),
                                       progress_color=TemaArgos.ACENTO)
        self.sw_modal.select()
        self.sw_modal.pack(anchor="w", padx=12, pady=(0, 8))

        fila_prueba = ctk.CTkFrame(card_av, fg_color="transparent")
        fila_prueba.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(fila_prueba, text="Probar:", font=TemaArgos.ui(10),
                     text_color=TemaArgos.TEXTO_TENUE).pack(side="left", padx=(0, 6))
        for etiqueta, nivel in (("Leve", "Leve"), ("Mod.", "Moderada"), ("Sev.", "Severa")):
            ctk.CTkButton(fila_prueba, text=etiqueta, width=46, height=24,
                          font=TemaArgos.ui(10), fg_color="transparent",
                          hover_color=TemaArgos.PANEL_ALTO,
                          text_color=TemaArgos.TEXTO_SUAVE,
                          border_width=1, border_color=TemaArgos.ACENTO,
                          corner_radius=TemaArgos.RADIO,
                          command=lambda n=nivel: self.alertas.probar(n)
                          ).pack(side="left", padx=2)

        # El estado y los FPS viven ahora en la barra de acciones, arriba.
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
        self.label_alerta = ctk.CTkLabel(columna, text="",
                                          text_color=TemaArgos.RIESGO,
                                          font=TemaArgos.ui(13, "bold"))
        self.label_alerta.pack(pady=6)

        # ── Columna derecha: cámara ──
        # La etiqueta y la resolución van en una cabecera propia, FUERA del
        # marco: dentro quedaban tapadas por el borde y por el propio video.
        self.frame_camara = ctk.CTkFrame(cuerpo, fg_color="transparent")
        self.frame_camara.grid(row=0, column=1, sticky="nsew")
        self.frame_camara.grid_rowconfigure(1, weight=1)
        self.frame_camara.grid_columnconfigure(0, weight=1)

        cab_cam = ctk.CTkFrame(self.frame_camara, fg_color="transparent")
        cab_cam.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(cab_cam, text="● CÁMARA EN VIVO", font=TemaArgos.dato(10),
                     text_color=TemaArgos.ACENTO_VIVO).pack(side="left")
        ctk.CTkLabel(cab_cam, text=" 640 × 480 ", font=TemaArgos.dato(10),
                     text_color=TemaArgos.TEXTO_TENUE,
                     fg_color=TemaArgos.PANEL, corner_radius=TemaArgos.RADIO_CARD
                     ).pack(side="left", padx=10)
        self.label_cam_hint = ctk.CTkLabel(
            cab_cam, text="malla facial · MediaPipe FaceLandmarker",
            font=TemaArgos.ui(11), text_color=TemaArgos.TEXTO_TENUE)
        self.label_cam_hint.pack(side="right")

        marco_cam = ctk.CTkFrame(self.frame_camara, corner_radius=TemaArgos.RADIO_CARD,
                                  fg_color="#03070C", border_width=1,
                                  border_color=TemaArgos.LINEA)
        marco_cam.grid(row=1, column=0, sticky="nsew")
        self.label_video = ctk.CTkLabel(marco_cam, text="[ Cámara oculta ]",
                                         text_color=TemaArgos.TEXTO_TENUE,
                                         font=TemaArgos.ui(13))
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
        """Resumen de eventos descifrados; no infiere duración de sesiones."""
        from collections import Counter, defaultdict
        from datetime import timedelta
        from matplotlib.ticker import MaxNLocator

        for widget in contenedor.winfo_children():
            widget.destroy()
        tema = TemaArgos
        # LIMIT -1 recupera todo por el mismo camino de descifrado del historial.
        filas = self.bd.obtener_historial(usuario_id, limit=-1)

        def numero(valor):
            try:
                valor = float(valor)
                return valor if math.isfinite(valor) else None
            except (ValueError, TypeError):
                return None

        def formato(valor, decimales=1, unidad=""):
            valor = numero(valor)
            return "—" if valor is None else f"{valor:.{decimales}f}".replace(".", ",") + unidad

        def fecha(valor):
            try:
                return datetime.fromisoformat(valor)
            except (ValueError, TypeError):
                return None

        def categoria(valor):
            if valor.startswith("Falso") or valor == "Entrecerrado":
                return "Falsos"
            if valor == "Cierre-largo":
                return "Prolongado"
            return valor if valor in ("Normal", "Lento", "Prolongado", "Microsueño") else "Sin clasificar"

        colores_nivel = {"Normal": tema.TEXTO_TENUE, "Leve": tema.ALERTA,
                         "Moderada": tema.ALERTA, "Severa": tema.RIESGO}
        colores_clase = {"Normal": tema.OK, "Lento": tema.ACENTO_VIVO,
                         "Prolongado": tema.ALERTA, "Microsueño": tema.RIESGO,
                         "Falsos": tema.TEXTO_TENUE, "Sin clasificar": tema.TEXTO_TENUE}

        def etiqueta(parent, texto, tam=12, color=None, **kwargs):
            return ctk.CTkLabel(parent, text=texto, font=tema.ui(tam),
                                text_color=color or tema.TEXTO, **kwargs)

        etiqueta(contenedor, "Estadísticas", 22, anchor="w").pack(fill="x")
        etiqueta(contenedor, f"{usuario_nombre} · Resumen del historial", 12,
                 tema.TEXTO_TENUE, anchor="w").pack(fill="x", pady=(0, 12))
        contenido = ctk.CTkScrollableFrame(
            contenedor, fg_color=tema.FONDO, corner_radius=tema.RADIO,
            scrollbar_button_color=tema.ACENTO,
            scrollbar_button_hover_color=tema.ACENTO_VIVO)
        contenido.pack(fill="both", expand=True)

        if not filas:
            vacio = ctk.CTkFrame(contenido, fg_color=tema.PANEL,
                                 corner_radius=tema.RADIO_CARD,
                                 border_width=1, border_color=tema.LINEA)
            vacio.pack(fill="x", padx=12, pady=30)
            etiqueta(vacio, "Todavía no hay registros", 20).pack(pady=(48, 12))
            etiqueta(vacio, "Iniciá una sesión de detección para ver tu actividad y su evolución.",
                     13, tema.TEXTO_SUAVE, wraplength=550).pack(padx=24, pady=(0, 48))
            return

        conteos = Counter(categoria(f[5]) for f in filas)
        diarios = defaultdict(list)
        for f in filas:
            d = fecha(f[0])
            if d is not None:
                diarios[d.date()].append(f)

        def promedio(registros, columna):
            valores = [v for f in registros if (v := numero(f[columna])) is not None]
            return sum(valores) / len(valores) if valores else None

        indice = promedio(filas, 7)
        nivel = ("Sin datos" if indice is None else "Normal" if indice < 30 else
                 "Leve" if indice < 60 else "Moderada" if indice < 80 else "Severa")
        tarjetas = [
            ("Total de parpadeos", str(conteos["Normal"] + conteos["Lento"]), "Normales y lentos", tema.TEXTO),
            ("Frecuencia media", "—", "Sin duración de sesiones", tema.TEXTO_TENUE),
            ("PERCLOS promedio", formato(promedio(filas, 6), unidad=" %"), "Promedio por registro", tema.TEXTO),
            ("Índice de fatiga", formato(indice), nivel, colores_nivel.get(nivel, tema.TEXTO_TENUE)),
            ("Cierres prolongados", str(conteos["Prolongado"] + conteos["Microsueño"]), "Incluye microsueños", tema.TEXTO),
            ("Días con sesiones", str(len(diarios)), "Días con eventos registrados", tema.TEXTO),
        ]
        resumen = ctk.CTkFrame(contenido, fg_color=tema.FONDO)
        resumen.pack(fill="x", pady=(0, 12))
        # Dos filas mantienen las etiquetas legibles con la barra lateral a 1280 px.
        for i, (titulo, valor, detalle, color) in enumerate(tarjetas):
            resumen.grid_columnconfigure(i % 3, weight=1, uniform="kpi")
            card = ctk.CTkFrame(resumen, fg_color=tema.PANEL, border_width=1,
                                border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            etiqueta(card, titulo, 12, tema.TEXTO_SUAVE).pack(padx=8, pady=(12, 2))
            ctk.CTkLabel(card, text=valor, font=tema.dato(25, "bold"),
                         text_color=color).pack()
            etiqueta(card, detalle, 11, tema.TEXTO_TENUE).pack(padx=8, pady=(2, 12))

        def grafico(titulo, alto=240):
            panel = ctk.CTkFrame(contenido, fg_color=tema.PANEL,
                                 corner_radius=tema.RADIO_CARD, border_width=1,
                                 border_color=tema.LINEA)
            panel.pack(fill="x", padx=4, pady=(0, 12))
            etiqueta(panel, titulo, 14, anchor="w").pack(fill="x", padx=16, pady=(12, 0))
            figura = Figure(figsize=(7, alto / 100), dpi=100, facecolor=tema.PANEL)
            ax = figura.add_subplot(111)
            ax.set_facecolor(tema.PANEL)
            ax.tick_params(colors=tema.TEXTO_TENUE, labelsize=9)
            for lado in ("bottom", "left"):
                ax.spines[lado].set_color(tema.LINEA)
            for lado in ("top", "right"):
                ax.spines[lado].set_visible(False)
            ax.grid(axis="y", color=tema.LINEA, linewidth=0.7)
            ax.set_axisbelow(True)
            canvas = FigureCanvasTkAgg(figura, master=panel)
            widget = canvas.get_tk_widget()
            widget.configure(height=alto, width=1, background=tema.PANEL,
                             highlightthickness=0)
            widget.pack(fill="x", padx=8, pady=8)

            def liberar(event):
                if event.widget is not widget:
                    return
                # Figure directa: no se registra en pyplot. Cancelar draws pendientes
                # y vaciar la figura; no desenganchar canvas.figure (matplotlib
                # todavía procesa eventos del canvas y fallaría con None).
                for atributo in ("_idle_draw_id", "_event_loop_id"):
                    pendiente = getattr(canvas, atributo, None)
                    if pendiente:
                        widget.after_cancel(pendiente)
                        setattr(canvas, atributo, None)
                figura.clear()
            widget.bind("<Destroy>", liberar, add="+")
            return figura, ax, canvas

        hoy = datetime.now().date()
        dias = [hoy - timedelta(days=i) for i in range(13, -1, -1)]
        fig, ax, canvas = grafico("Parpadeos por día · últimos 14 días")
        ax.bar(range(14), [sum(categoria(f[5]) in ("Normal", "Lento")
                              for f in diarios.get(d, ())) for d in dias],
               color=tema.ACENTO_VIVO, width=0.6)
        ax.set_xticks(range(14), [d.strftime("%d/%m") for d in dias], rotation=35)
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylim(bottom=0)
        fig.tight_layout(pad=1.5)
        canvas.draw()

        fig, ax, canvas = grafico("Evolución · promedios diarios del historial", 270)
        for columna, nombre, color in ((7, "Índice de fatiga", tema.ACENTO_VIVO),
                                        (6, "PERCLOS (%)", tema.OK)):
            puntos = [(d, promedio(diarios[d], columna)) for d in sorted(diarios)]
            puntos = [(d, v) for d, v in puntos if v is not None]
            if puntos:
                ax.plot([d for d, _ in puntos], [v for _, v in puntos],
                        marker="o", markersize=3, linewidth=1.5, color=color, label=nombre)
        if ax.lines:
            from matplotlib.dates import AutoDateLocator, DateFormatter
            fechas = sorted(diarios)
            if len(fechas) < 3:
                # Con 1-2 días el localizador automático abre el eje varios años.
                ax.set_xlim(fechas[0] - timedelta(days=3), fechas[-1] + timedelta(days=3))
                ax.set_xticks(fechas)
            else:
                ax.xaxis.set_major_locator(AutoDateLocator(minticks=3, maxticks=7))
            ax.xaxis.set_major_formatter(DateFormatter("%d/%m"))
            leyenda = ax.legend(frameon=False, fontsize=9)
            for texto in leyenda.get_texts():
                texto.set_color(tema.TEXTO_SUAVE)
        else:
            ax.text(0.5, 0.5, "Todavía no hay mediciones con fecha válida",
                    transform=ax.transAxes, ha="center", color=tema.TEXTO_TENUE)
        ax.set_ylim(0, 100)
        fig.tight_layout(pad=1.5)
        canvas.draw()

        fig, ax, canvas = grafico("Distribución de eventos · todo el historial")
        clases = ["Normal", "Lento", "Prolongado", "Microsueño", "Falsos"]
        if conteos["Sin clasificar"]:
            clases.append("Sin clasificar")
        barras = ax.barh(clases, [conteos[c] for c in clases],
                         color=[colores_clase[c] for c in clases], height=0.55)
        ax.bar_label(barras, padding=4, color=tema.TEXTO_SUAVE, fontsize=9)
        ax.invert_yaxis()
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_xlim(0, max(1, max(conteos.values())) * 1.18)
        fig.tight_layout(pad=1.5)
        canvas.draw()

        etiqueta(contenido, "Últimos 50 registros", 16, anchor="w").pack(fill="x", padx=8)
        etiqueta(contenido, "Orden de registro · duración en ms · PERCLOS en % · índice de 0 a 100",
                 11, tema.TEXTO_TENUE, anchor="w").pack(fill="x", padx=8, pady=(0, 8))
        tabla = ctk.CTkFrame(contenido, fg_color=tema.PANEL, corner_radius=tema.RADIO_CARD)
        tabla.pack(fill="x", padx=4, pady=(0, 12))
        cabecera = ctk.CTkFrame(tabla, fg_color=tema.PANEL_ALTO, corner_radius=tema.RADIO)
        cabecera.pack(fill="x", padx=(6, 22), pady=(6, 0))
        cuerpo = ctk.CTkScrollableFrame(tabla, height=300, fg_color=tema.PANEL,
                                       corner_radius=tema.RADIO,
                                       scrollbar_button_color=tema.ACENTO,
                                       scrollbar_button_hover_color=tema.ACENTO_VIVO)
        cuerpo.pack(fill="x", padx=0, pady=(0, 6))
        columnas = [("Fecha y hora", 3), ("EAR", 1), ("Duración", 1),
                    ("Clasificación", 2), ("Usuario", 2), ("Nivel", 2),
                    ("PERCLOS", 1), ("Índice", 1)]

        def fila_tabla(parent, valores, encabezado=False, registro=None):
            for col, ((_, peso), valor) in enumerate(zip(columnas, valores)):
                parent.grid_columnconfigure(col, weight=peso, uniform="tabla")
                color = tema.TEXTO_SUAVE
                fondo = tema.PANEL_ALTO if encabezado else tema.PANEL
                if registro and col in (3, 5):
                    color = (colores_clase[categoria(registro[5])] if col == 3 else
                             colores_nivel.get(registro[3], tema.TEXTO_TENUE))
                    fondo = tema.PANEL_ALTO
                label = ctk.CTkLabel(parent, text=str(valor), width=1, height=32,
                                     anchor="e" if col in (1, 2, 6, 7) else "w",
                                     font=tema.ui(11, "bold") if encabezado else tema.ui(11),
                                     text_color=color, fg_color=fondo,
                                     corner_radius=tema.RADIO_CARD)
                label.grid(row=0, column=col, sticky="ew", padx=3, pady=3)

        fila_tabla(cabecera, [c[0] for c in columnas], encabezado=True)
        for f in filas[:50]:
            d = fecha(f[0])
            valores = [d.strftime("%d/%m/%y %H:%M") if d else "Sin fecha",
                       formato(f[1], 3), formato(f[4], 0),
                       f[5] if f[5] != "—" else "Sin clasificar", f[2], f[3],
                       formato(f[6]), formato(f[7])]
            renglon = ctk.CTkFrame(cuerpo, fg_color=tema.PANEL, corner_radius=tema.RADIO)
            renglon.pack(fill="x")
            fila_tabla(renglon, valores, registro=f)
            ctk.CTkFrame(cuerpo, height=1, fg_color=tema.LINEA).pack(fill="x")

    def _construir_vista_chart(self, tab):
        tema = TemaArgos
        ctk.CTkLabel(tab, text="Gráfica EAR en tiempo real", font=tema.ui(22),
                     text_color=tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(tab, text="Apertura de los ojos · señal cruda, suavizado y referencias",
                     font=tema.ui(12), text_color=tema.TEXTO_TENUE,
                     anchor="w").pack(fill="x", pady=(0, 12))
        contenido = ctk.CTkScrollableFrame(tab, fg_color=tema.FONDO,
                     corner_radius=tema.RADIO, scrollbar_button_color=tema.ACENTO,
                     scrollbar_button_hover_color=tema.ACENTO_VIVO)
        contenido.pack(fill="both", expand=True)
        tarjetas = ctk.CTkFrame(contenido, fg_color=tema.FONDO)
        tarjetas.pack(fill="x", pady=(0, 12))
        self._chart_valores = {}
        for i, (clave, titulo) in enumerate((('ear', 'EAR actual · suavizado'),
                ('base', 'Referencia de ojo abierto'), ('estado', 'Estado del ojo'),
                ('fps', 'Cuadros por segundo'))):
            tarjetas.grid_columnconfigure(i % 2, weight=1, uniform="ear")
            card = ctk.CTkFrame(tarjetas, fg_color=tema.PANEL,
                               border_width=1, border_color=tema.LINEA,
                               corner_radius=tema.RADIO_CARD)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)
            ctk.CTkLabel(card, text=titulo, font=tema.ui(11),
                         text_color=tema.TEXTO_TENUE).pack(padx=12, pady=(10, 0))
            valor = ctk.CTkLabel(card, text="—", font=tema.dato(18),
                                text_color=tema.TEXTO, wraplength=300)
            valor.pack(padx=12, pady=(0, 10))
            self._chart_valores[clave] = valor
        panel = ctk.CTkFrame(contenido, fg_color=tema.PANEL, border_width=1,
                             border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
        panel.pack(fill="x", padx=4, pady=(0, 8))
        self._chart_figure = Figure(figsize=(7, 3.5), dpi=100, facecolor=tema.PANEL)
        ax = self._chart_ax = self._chart_figure.add_subplot(111)
        ax.set_facecolor(tema.PANEL)
        for lado in ("bottom", "left"):
            ax.spines[lado].set_color(tema.LINEA)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        ax.tick_params(colors=tema.TEXTO_TENUE, labelsize=9)
        ax.grid(True, color=tema.LINEA, linewidth=0.7)
        ax.set_axisbelow(True)
        self._chart_crudo, = ax.plot([], [], color=tema.TEXTO_TENUE,
                                     linewidth=1, alpha=0.7, label="EAR crudo")
        self._chart_suave, = ax.plot([], [], color=tema.ACENTO_VIVO,
                                     linewidth=1.8, label="EAR suavizado")
        self._chart_umbral = ax.axhline(self.p_umbral_ear, color=tema.ALERTA,
                              linestyle="--", linewidth=1.2, label="Inicio de cierre")
        self._chart_base = ax.axhline(0, color=tema.OK, linestyle=":",
                              linewidth=1.2, label="Referencia de ojo abierto")
        self._chart_base.set_visible(False)
        self._chart_mensaje = ax.text(0.5, 0.5, "Iniciá la detección para ver la señal",
                       ha="center", va="center", transform=ax.transAxes,
                       color=tema.TEXTO_SUAVE, fontsize=10)
        leyenda = ax.legend(loc="upper right", ncol=2, fontsize=8, frameon=False)
        for texto in leyenda.get_texts():
            texto.set_color(tema.TEXTO_SUAVE)
        ax.set_xlim(-149, 0)
        ax.set_ylim(0, 0.5)
        ax.set_xlabel("Cuadros anteriores al más reciente", color=tema.TEXTO_TENUE, fontsize=9)
        ax.set_ylabel("EAR", color=tema.TEXTO_TENUE, fontsize=9)
        self._chart_figure.tight_layout(pad=1.5)
        canvas = self._chart_canvas = FigureCanvasTkAgg(self._chart_figure, master=panel)
        widget = canvas.get_tk_widget()
        widget.configure(width=1, height=350, background=tema.PANEL, highlightthickness=0)
        widget.pack(fill="x", padx=8, pady=8)
        self._chart_after_id = None
        figura = self._chart_figure

        def liberar(event):
            if event.widget is not widget:
                return
            if self._chart_after_id is not None:
                self.after_cancel(self._chart_after_id)
                self._chart_after_id = None
            for atributo in ("_idle_draw_id", "_event_loop_id"):
                pendiente = getattr(canvas, atributo, None)
                if pendiente:
                    widget.after_cancel(pendiente)
                    setattr(canvas, atributo, None)
            # Matplotlib puede seguir despachando eventos de cierre del canvas.
            figura.clear()
        widget.bind("<Destroy>", liberar, add="+")
        canvas.draw_idle()

    def _refrescar_grafico(self):
        """Actualiza artistas existentes y mantiene una sola cadena de after()."""
        pendiente = getattr(self, "_chart_after_id", None)
        if pendiente is not None:
            self.after_cancel(pendiente)
            self._chart_after_id = None
        if not self._grafico_activo:
            return
        datos = list(self.historico_ear)
        n = max(1, self.ear_buffer.maxlen or 1)
        # Solo ventanas completas: al recortarse el historial no conocemos
        # los cuadros anteriores. No se inventa suavizado en el borde izquierdo.
        suaves = [sum(datos[i - n + 1:i + 1]) / n for i in range(n - 1, len(datos))]
        xs = list(range(1 - len(datos), 1))
        self._chart_crudo.set_data(xs, datos)
        self._chart_suave.set_data(xs[n - 1:], suaves)
        self._chart_umbral.set_ydata([self.p_umbral_ear] * 2)
        base = self.detector.baseline
        self._chart_base.set_visible(base is not None)
        if base is not None:
            self._chart_base.set_ydata([base] * 2)
        estado = self.label_estado_ojo.cget("text").removeprefix("Ojo: ")
        activo = self.sistema_activo
        sin_senal = not activo or not datos or estado in ("sin señal", "sin rostro", "—")
        actual = sum(self.ear_buffer) / len(self.ear_buffer) if self.ear_buffer else None
        self._chart_valores['ear'].configure(text="—" if sin_senal or actual is None
                                            else f"{actual:.3f}".replace('.', ','))
        self._chart_valores['base'].configure(text="Sin calibrar" if base is None
                                             else f"{base:.3f}".replace('.', ','))
        self._chart_valores['estado'].configure(text=estado if activo else "Detección detenida")
        self._chart_valores['fps'].configure(text=f"{self._fps:.0f}" if activo else "—")
        self._chart_mensaje.set_visible(sin_senal)
        self._chart_mensaje.set_text("Iniciá la detección para ver la señal" if not activo
                                     else "Sin señal de los ojos · se conserva la última traza")
        self._chart_ax.set_xlim(-max(1, (self.historico_ear.maxlen or 150) - 1), 0)
        self._chart_ax.set_ylim(0, max(0.5, max(datos + [base or 0, self.p_umbral_ear]) * 1.15))
        self._chart_canvas.draw_idle()
        self._chart_after_id = self.after(200, self._refrescar_grafico)

    def _about_texto_adaptable(self, contenedor, texto, padding=20, tamano=13,
                              color=None, pady=(0, 18)):
        """Ajusta el texto desde el ancho del contenedor, nunca desde el label."""
        label = ctk.CTkLabel(contenedor, text=texto, font=TemaArgos.ui(tamano),
                            text_color=color or TemaArgos.TEXTO_SUAVE,
                            justify="left", anchor="w", wraplength=280)
        label.pack(fill="x", padx=padding, pady=pady)

        # CTkFrame.bind engancha el evento a su canvas interno: event.widget es
        # ese canvas, no el frame.
        objetivo = getattr(contenedor, "_canvas", contenedor)

        def ajustar(event):
            if event.widget is objetivo:
                ancho = int(event.width / contenedor._get_widget_scaling())
                limite = max(160, ancho - 2 * padding - 4)
                if label.cget("wraplength") != limite:
                    label.configure(wraplength=limite)
        contenedor.bind("<Configure>", ajustar, add="+")
        return label

    def _construir_vista_about(self, tab):
        tema = TemaArgos
        contenido = ctk.CTkScrollableFrame(tab, fg_color=tema.FONDO,
                       corner_radius=tema.RADIO, scrollbar_button_color=tema.ACENTO,
                       scrollbar_button_hover_color=tema.ACENTO_VIVO)
        contenido.pack(fill="both", expand=True)
        hero = ctk.CTkFrame(contenido, fg_color=tema.PANEL, border_width=1,
                           border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
        hero.pack(fill="x", padx=4, pady=(4, 18))
        cabecera = ctk.CTkFrame(hero, fg_color=tema.PANEL)
        cabecera.pack(fill="x", padx=24, pady=(24, 16))
        logo = cargar_logo((104, 104))
        ctk.CTkLabel(cabecera, text="" if logo else "ARGOS", image=logo,
                     width=112, height=112, font=tema.dato(20),
                     text_color=tema.ACENTO_VIVO).pack(side="left", padx=(0, 24))
        titulos = ctk.CTkFrame(cabecera, fg_color=tema.PANEL)
        titulos.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(titulos, text="A R G O S", font=fuente_portada(34),
                     text_color=tema.TEXTO, anchor="w").pack(fill="x")
        ctk.CTkLabel(titulos, text="Monitor de fatiga visual", font=tema.ui(18),
                     text_color=tema.TEXTO_SUAVE, anchor="w").pack(fill="x", pady=(2, 4))
        self._about_texto_adaptable(titulos, 'Argos Panoptes — «el que todo lo ve»',
                                    padding=0, color=tema.TEXTO_TENUE, pady=0)
        chips = ctk.CTkFrame(hero, fg_color=tema.PANEL)
        chips.pack(fill="x", padx=24, pady=(0, 24))
        for texto in ("Proyecto de tesis", "Python", "Uso preventivo, no médico"):
            ctk.CTkLabel(chips, text=f"  {texto}  ", font=tema.ui(11),
                         fg_color=tema.PANEL_ALTO, text_color=tema.TEXTO_SUAVE,
                         corner_radius=tema.RADIO_CARD).pack(side="left", padx=(0, 8))
        self._about_por_que(contenido)
        self._about_sistema(contenido)
        self._about_creadores(contenido)

    def _about_por_que(self, tab):
        tema = TemaArgos
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
        card = ctk.CTkFrame(tab, fg_color=tema.PANEL, border_width=1,
                           border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
        card.pack(fill="x", padx=4, pady=(0, 18))
        ctk.CTkLabel(card, text="¿Por qué Argos?", font=tema.ui(22),
                     text_color=tema.TEXTO, anchor="w").pack(fill="x", padx=20, pady=(18, 12))
        self._about_texto_adaptable(card, texto)

    def _about_sistema(self, tab):
        tema = TemaArgos

        def titulo(texto):
            ctk.CTkLabel(tab, text=texto, font=tema.ui(22), text_color=tema.TEXTO,
                         anchor="w").pack(fill="x", padx=8, pady=(8, 12))

        titulo("Cómo funciona")
        flujo = ctk.CTkFrame(tab, fg_color=tema.FONDO)
        flujo.pack(fill="x", padx=4, pady=(0, 18))
        pasos = [("Cámara", "Captura de la imagen"),
                 ("MediaPipe", "478 puntos de la cara"),
                 ("EAR 3D", "Apertura de los ojos + pose de cabeza"),
                 ("Detector de parpadeos", "Caída relativa respecto del baseline"),
                 ("Índice de fatiga", "Evaluación y alertas")]
        tarjetas, flechas = [], []
        for i, (nombre, detalle) in enumerate(pasos):
            card = ctk.CTkFrame(flujo, fg_color=tema.PANEL, border_width=1,
                               border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
            ctk.CTkLabel(card, text=f"0{i + 1}", font=tema.dato(20, "bold"),
                         text_color=tema.ACENTO_VIVO, anchor="w").pack(
                             fill="x", padx=14, pady=(14, 4))
            self._about_texto_adaptable(card, nombre, padding=14, tamano=14,
                                        color=tema.TEXTO, pady=(0, 6))
            self._about_texto_adaptable(card, detalle, padding=14, tamano=12,
                                        color=tema.TEXTO_TENUE, pady=(0, 14))
            tarjetas.append(card)
            if i < 4:
                flechas.append(ctk.CTkLabel(flujo, text="→", width=24,
                               font=tema.ui(20), text_color=tema.ACENTO_VIVO))
        distribucion = [None]

        def distribuir(event):
            if event.widget is not flujo._canvas:  # CTkFrame.bind → canvas interno
                return
            ancho = event.width / flujo._get_widget_scaling()
            columnas = 5 if ancho >= 1120 else 3
            if distribucion[0] == columnas:
                return
            distribucion[0] = columnas
            for widget in tarjetas + flechas:
                widget.grid_forget()
            for col in range(9):
                flujo.grid_columnconfigure(col, weight=0, minsize=0, uniform="")
            for col in range(columnas):
                flujo.grid_columnconfigure(col * 2, weight=1, uniform="pasos")
            for i, card in enumerate(tarjetas):
                fila, col = divmod(i, columnas)
                card.grid(row=fila * 2, column=col * 2, sticky="nsew", pady=4)
                if i < 4:
                    if col < columnas - 1:
                        flechas[i].configure(text="→")
                        flechas[i].grid(row=fila * 2, column=col * 2 + 1, padx=4)
                    else:
                        flechas[i].configure(text="↓")
                        flechas[i].grid(row=fila * 2 + 1, column=0,
                                        columnspan=columnas * 2 - 1)
        flujo.bind("<Configure>", distribuir, add="+")

        titulo("Qué mide")
        metricas = ctk.CTkFrame(tab, fg_color=tema.FONDO)
        metricas.pack(fill="x", pady=(0, 18))
        metricas.grid_columnconfigure((0, 1), weight=1, uniform="metricas")
        items = [
            ("control", "Parpadeos", "EAR en 3D con baseline móvil por ojo. Detecta por caída relativa para contar bien las ráfagas y los parpadeos con la cabeza girada."),
            ("stats", "PERCLOS", "Porcentaje de tiempo con los ojos cerrados en una ventana de 60 s. Los cuadros mirando abajo o de perfil no se cuentan."),
            ("chart", "Índice de fatiga", "Puntaje de 0 a 100 que pondera PERCLOS, duración, frecuencia, cierres prolongados y variabilidad. Niveles: Normal, Leve, Moderada y Severa."),
            ("calib", "Alertas escalonadas", "Aviso en la app, notificación, sonido y pausa según el nivel. Esperan 60 s de calentamiento antes de activarse."),
        ]
        for i, (icono, nombre, texto) in enumerate(items):
            card = ctk.CTkFrame(metricas, fg_color=tema.PANEL, border_width=1,
                               border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)
            ctk.CTkLabel(card, text=f"  {nombre}", image=cargar_icono(f"icon_nav_{icono}", (24, 24)),
                         compound="left", font=tema.ui(16, "bold"), text_color=tema.TEXTO,
                         anchor="w").pack(fill="x", padx=20, pady=(18, 12))
            self._about_texto_adaptable(card, texto)

        titulo("Fundamento")
        fundamento = ctk.CTkFrame(tab, fg_color=tema.PANEL, border_width=1,
                                 border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
        fundamento.pack(fill="x", padx=4, pady=(0, 10))
        referencias = [
            "Soukupová y Čech (2016) · Detección de parpadeo con landmarks y EAR.",
            "Wolffsohn et al. (2017) · TFOS DEWS II.",
            "Coles-Brennan et al. (2019) · Fatiga visual digital.",
            "American Optometric Association · Regla 20-20-20.",
        ]
        self._about_texto_adaptable(fundamento, "\n\n".join(f"•  {r}" for r in referencias),
                                    pady=(18, 18))
        aviso = ctk.CTkFrame(tab, fg_color=tema.PANEL, border_width=1,
                            border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
        aviso.pack(fill="x", padx=4, pady=(0, 18))
        self._about_texto_adaptable(aviso,
            "Argos no es un dispositivo médico: recomienda prácticas preventivas y no diagnostica.",
            color=tema.ALERTA, pady=(16, 16))

        titulo("Tecnologías")
        tecnologias = ctk.CTkFrame(tab, fg_color=tema.FONDO)
        tecnologias.pack(fill="x", padx=4, pady=(0, 18))
        chips = []
        for texto in ("Python", "OpenCV", "MediaPipe", "CustomTkinter", "Matplotlib",
                      "SQLite con cifrado AES-GCM", "Windows Hello"):
            chip = ctk.CTkLabel(tecnologias, text=f"  {texto}  ", font=tema.ui(12),
                                fg_color=tema.PANEL_ALTO, text_color=tema.TEXTO_SUAVE,
                                corner_radius=tema.RADIO_CARD)
            chips.append(chip)

        # Posicionar por fila evita compartir anchos de columna entre filas.
        def distribuir_chips(event):
            if event.widget is not tecnologias._canvas:  # CTkFrame.bind → canvas interno
                return
            escala = tecnologias._get_widget_scaling()
            ancho = event.width / escala
            x, y = 0, 0
            for chip in chips:
                pedido = chip.winfo_reqwidth() / escala
                if x and x + pedido > ancho:
                    x, y = 0, y + 36
                chip.place(x=x, y=y)
                x += pedido + 8
            tecnologias.configure(height=y + 32)
        tecnologias.bind("<Configure>", distribuir_chips, add="+")

    def _about_creadores(self, tab):
        tema = TemaArgos
        ctk.CTkLabel(tab, text="Creadores", font=tema.ui(22), text_color=tema.TEXTO,
                     anchor="w").pack(fill="x", padx=8, pady=(8, 12))
        creadores = ctk.CTkFrame(tab, fg_color=tema.FONDO)
        creadores.pack(fill="x", pady=(0, 20))
        creadores.grid_columnconfigure((0, 1), weight=1, uniform="creadores")
        for i, (iniciales, nombre) in enumerate((("TM", "Tobias Molinas"), ("MM", "Matias Murto"))):
            card = ctk.CTkFrame(creadores, fg_color=tema.PANEL, border_width=1,
                               border_color=tema.LINEA, corner_radius=tema.RADIO_CARD)
            card.grid(row=0, column=i, sticky="nsew", padx=4)
            ctk.CTkLabel(card, text=iniciales, width=52, height=52,
                         font=tema.dato(18, "bold"), text_color=tema.TEXTO,
                         fg_color=tema.ACENTO, corner_radius=tema.RADIO_CARD).pack(
                             side="left", padx=16, pady=20)
            caja = ctk.CTkFrame(card, fg_color=tema.PANEL)
            caja.pack(side="left", fill="x", expand=True, padx=(0, 16))
            self._about_texto_adaptable(caja, nombre, padding=0, tamano=16,
                                        color=tema.TEXTO, pady=(0, 4))
            self._about_texto_adaptable(caja, "Desarrollo · Investigación", padding=0,
                                        tamano=12, color=tema.TEXTO_TENUE, pady=0)

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

                # La calibración manual siembra el baseline inicial de ojo abierto
                # (reemplaza a la calibración implícita); después lo ajusta la
                # ventana móvil del detector.
                if self.calib_ear_open:
                    self.detector.sembrar_baseline(self.calib_ear_open, self._ultimo_pitch)
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
        self.detector.reiniciar()

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
            self.cooldown_hasta       = 0.0
            self.deteccion_inicio     = time.time()
            self._fps = 0.0; self._fps_n = 0; self._fps_t0 = None
            escenario = os.environ.get("ARGOS_DEBUG", "").strip()
            if escenario:
                self.debug_logger = EARDebugLogger(
                    escenario, os.path.join(_dir_datos(), "debug_argos"))
            # Re-calibrar baseline al iniciar (salvo que ya venga de auto-calibración)
            self.detector.reiniciar(conservar_baseline=True)
            self.btn_iniciar.configure(text="Detener Detección",
                                        fg_color=TemaArgos.RIESGO,
                                        hover_color="#8F332C")
            self.label_estado.configure(text="ACTIVO",
                                        text_color=TemaArgos.OK)
            self.actualizar_video()
        else:
            self.sistema_activo = False
            self._cancelar_prueba_guiada()  # si estaba en curso, abortarla
            self.btn_iniciar.configure(text="Iniciar Detección",
                                        fg_color=TemaArgos.ACENTO,
                                        hover_color=TemaArgos.ACENTO_VIVO)
            self.label_estado.configure(text="INACTIVO",
                                        text_color=TemaArgos.TEXTO_TENUE)
            if self.cap:
                self.cap.release()
            self._cerrar_debug_logger()
            self._limpiar_video("")

    def _cerrar_debug_logger(self):
        if self.debug_logger:
            self.debug_logger.close()
            self.debug_logger = None

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
            self._limpiar_video("[ Cámara oculta ]")

    def _sw_metricas(self):
        """Interruptor: muestra u oculta el bloque de métricas en vivo."""
        if self.sw_metricas.get():
            self.frame_metricas.pack(fill="x")
        else:
            self.frame_metricas.pack_forget()

    # ── Canales de aviso ─────────────────────────────
    def _sw_sonido(self):
        self.alertas.sonido_activo = bool(self.sw_sonido.get())

    def _sw_toast(self):
        self.alertas.toast_activo = bool(self.sw_toast.get())

    def _sw_modal(self):
        self.alertas.modal_activo = bool(self.sw_modal.get())

    # ── Prueba guiada de validación ──────────────────
    def _iniciar_prueba_guiada(self):
        self._mostrar_vista("control")     # la guía se ve en la cámara de Control
        if not self.sistema_activo:
            self.toggle_sistema()          # arranca la detección
        if not self.camara_visible:
            self.toggle_camara()           # asegura que se vea la guía
        # Recalibrar baseline desde cero (la fase 0 de la guía lo calibra)
        self.detector.reiniciar()
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
        cuadros), igual que la duración de cierre. cerrado=None (no evaluable:
        mirando abajo, de perfil, calibrando) no suma ni abierto ni cerrado."""
        ahora = time.time()
        if self._ultimo_ts_perclos is None or cerrado is None:
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

    def _registrar_cierre(self, duracion_ms, etiqueta, categoria, ear_suavizado, frame,
                          profundidad=0.0):
        print(f"DEBUG cierre: {duracion_ms:.0f} ms | {etiqueta} ({categoria}) | "
              f"prof={profundidad:.2f} | baseline={self.detector.baseline or 0:.3f} | "
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

        if score < 30:
            clasificacion = "Normal"
        elif score < 60:
            clasificacion = "Leve"
        elif score < 80:
            clasificacion = "Moderada"
        else:
            clasificacion = "Severa"

        return score, clasificacion

    def actualizar_frecuencia(self):
        ahora = time.time()
        self.historial_tiempos = [t for t in self.historial_tiempos if ahora - t <= 60]
        bpm = len(self.historial_tiempos)
        self.label_bpm.configure(text=f"Frecuencia: {bpm} / min")

        score, clasificacion = self._calcular_indice_fatiga()
        self.label_perclos.configure(text=f"{self.perclos_actual:.1f} %")
        self.bar_perclos.set(min(1.0, self.perclos_actual / 100))

        colores = {"Normal": TemaArgos.TEXTO_TENUE, "Leve": TemaArgos.ALERTA,
                   "Moderada": TemaArgos.ALERTA, "Severa": TemaArgos.RIESGO}
        color_indice = colores.get(clasificacion, TemaArgos.TEXTO_TENUE)
        self.label_indice.configure(text=f"{score:.1f}  ({clasificacion})", text_color=color_indice)
        self.bar_indice.set(min(1.0, score / 100))
        self.bar_indice.configure(progress_color=color_indice)

        calentando = (self.deteccion_inicio is None
                      or time.time() - self.deteccion_inicio < self.CALENTAMIENTO_S)

        # Canal 1: aviso dentro de la app, siempre visible mientras la ventana lo esté.
        if calentando:
            self.label_alerta.configure(text="")
        elif clasificacion in ("Moderada", "Severa"):
            self.label_alerta.configure(
                text=f"¡ALERTA FATIGA!\nÍndice {clasificacion.upper()}\nPERCLOS {self.perclos_actual:.0f}%")
        elif 0 < bpm < 10:
            self.label_alerta.configure(text="¡ALERTA FATIGA!\nBaja frecuencia\nde parpadeo.")
        else:
            self.label_alerta.configure(text="")

        # Canales 2 a 4: el gestor decide cuáles disparar y evita repetirlos.
        # Solo después del calentamiento: antes, las ventanas de 60 s están
        # incompletas y la frecuencia ~0/min dispararía alertas falsas.
        if calentando:
            return
        self.alertas.evaluar(clasificacion, score, self.perclos_actual, bpm)

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
        """Refleja en p_umbral_ear (slider y gráfica EAR) el umbral de inicio de
        cierre del detector. Solo toca el slider si cambió de forma visible."""
        if self.detector.baseline is None:
            return
        umbral = max(0.08, min(0.40, round(self.detector.baseline * DetectorParpadeo.K_INICIO, 3)))
        if abs(umbral - self.p_umbral_ear) >= 0.005:
            self.p_umbral_ear = umbral
            self._set_slider("sl_umbral", umbral)

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
        """Bucle de video (cadena de after). Un error en un cuadro se registra
        y el bucle sigue: antes, una excepción acá cortaba la cadena y la
        detección se detenía en silencio aunque la app dijera ACTIVO."""
        espera_ms = 10
        try:
            espera_ms = self._procesar_cuadro()
        except Exception:
            traceback.print_exc()
        if self.sistema_activo:
            self.after(espera_ms, self.actualizar_video)

    def _procesar_cuadro(self):
        """Procesa un cuadro. Devuelve los ms hasta el próximo."""
        if self.sistema_activo and self.cap.isOpened():
            try:
                ret, frame = self.cap.read()
            except Exception:
                ret = False
            if not ret:
                self.label_estado_ojo.configure(text="Ojo: sin señal")
                return 500

            if self.debug_logger:
                self.debug_logger.grabar_cuadro_crudo(frame)  # crudo, sin espejo ni landmarks

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
            # Timestamp real y estrictamente creciente (requisito de VIDEO mode).
            self.timestamp_ms = max(int((time.time() - self._mp_t0) * 1000),
                                    self.timestamp_ms + 1)
            resultado = self.face_landmarker.detect_for_video(mp_image, self.timestamp_ms)
            t_cuadro  = time.time()

            ear_suavizado = 0.0
            recorte_cara  = None
            estado_ojo    = "—"
            ear_izq = ear_der = ear = movimiento = giro_cabeza = None
            pitch = yaw = None

            if resultado.face_landmarks:
                face_landmarks = resultado.face_landmarks[0]

                # EAR en 3D sobre los landmarks crudos: con la cabeza girada el
                # ojo lejano no se escorza, y sin el retraso del suavizado los
                # parpadeos rápidos no se fusionan.
                ear_izq = CalculadorEAR.calcular_ear_ojo(CalculadorEAR.obtener_coordenadas_3d(
                    CalculadorEAR.OJO_IZQUIERDO, face_landmarks, w, h))
                ear_der = CalculadorEAR.calcular_ear_ojo(CalculadorEAR.obtener_coordenadas_3d(
                    CalculadorEAR.OJO_DERECHO, face_landmarks, w, h))
                ear     = (ear_izq + ear_der) / 2.0
                self.historico_ear.append(ear)  # memoria cruda, siempre, abierto y cerrado
                self.ear_buffer.append(ear)
                ear_suavizado = sum(self.ear_buffer) / len(self.ear_buffer)

                # El suavizado EMA queda solo para dibujar (evita el temblor).
                p_izq = self._suavizar_puntos(CalculadorEAR.obtener_coordenadas(
                    CalculadorEAR.OJO_IZQUIERDO, face_landmarks, w, h), "_ema_izq", alpha=0.8)
                p_der = self._suavizar_puntos(CalculadorEAR.obtener_coordenadas(
                    CalculadorEAR.OJO_DERECHO, face_landmarks, w, h), "_ema_der", alpha=0.8)
                self.dibujar_ojo(frame, p_izq)
                self.dibujar_ojo(frame, p_der)

                if resultado.facial_transformation_matrixes:
                    pitch, yaw, _ = CalculadorEAR.pose_desde_matriz(
                        resultado.facial_transformation_matrixes[0])
                    self._ultimo_pitch = pitch

                nariz_x = int(face_landmarks[1].x * w)
                nariz_y = int(face_landmarks[1].y * h)
                if self.nariz_previa is not None:
                    movimiento = math.dist((nariz_x, nariz_y), self.nariz_previa)
                else:
                    movimiento = 0
                self.nariz_previa = (nariz_x, nariz_y)
                # Giro aproximado: posición de la nariz entre las comisuras
                # externas de los ojos (0 = de frente, ±1 = de perfil).
                ojo_a, ojo_b = face_landmarks[33].x, face_landmarks[263].x
                if abs(ojo_b - ojo_a) > 1e-6:
                    giro_cabeza = ((face_landmarks[1].x - (ojo_a + ojo_b) / 2)
                                   / (abs(ojo_b - ojo_a) / 2))

                r = self.detector.procesar(t_cuadro, ear_izq, ear_der, pitch, yaw, movimiento)
                estado_ojo = r["estado"]
                self._actualizar_perclos(r["cerrado"])
                self._aplicar_umbral_desde_baseline()
                evento = r["evento"]
                if evento:
                    if time.time() >= self.cooldown_hasta:
                        self._registrar_cierre(evento["duracion_ms"], evento["etiqueta"],
                                               evento["categoria"], ear_suavizado, frame,
                                               evento["profundidad"])
                        self.cooldown_hasta = time.time() + (self.p_cooldown / self.FPS_REFERENCIA)
                    else:
                        print(f"DEBUG bloqueado por cooldown: {evento['duracion_ms']:.0f} ms")

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
                self.detector.sin_rostro(t_cuadro)  # no evaluable: cancela el cierre en curso
                self._actualizar_perclos(None)

            # Marco verde + etiqueta sobre la cara (frame completo, con contexto).
            if recorte_cara:
                x1, y1, x2, y2 = recorte_cara
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                if self.guia_activa:
                    etiqueta = self.GUIA_FASES[self.guia_fase_idx][0]  # letra de fase
                else:
                    etiqueta = estado_ojo.split(" (")[0]  # "Mirando abajo", no solo "Mirando"
                cv2.putText(frame, etiqueta, (x1, max(24, y1 - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
            if self.debug_logger:
                base = self.detector.baseline
                self.debug_logger.capturar_si_toca(frame)
                self.debug_logger.log(
                    rostro=int(bool(resultado.face_landmarks)),
                    ear_izq=ear_izq, ear_der=ear_der, ear_usado=ear,
                    ear_suavizado=ear_suavizado, baseline=base,
                    umbral_cerrar=base * DetectorParpadeo.K_INICIO if base else None,
                    umbral_abrir=base * DetectorParpadeo.K_REAPERTURA_ABS if base else None,
                    ojo_cerrado=int(self.detector.cerrado), estado=estado_ojo,
                    parpadeos=self.total_parpadeos, giro_cabeza=giro_cabeza,
                    pitch=pitch, yaw=yaw,
                    no_evaluable_s=self.detector.no_evaluable_s,
                    movimiento_px=movimiento, fps=self._fps)
            frame_mostrar = self._ajustar_a_marco(frame, 640, 480)
            if self.debug_logger and giro_cabeza is not None:
                # Guía para las pruebas de giro: 0.7-0.9 ≈ 35-40° (verde)
                en_rango = 0.7 <= abs(giro_cabeza) <= 0.9
                cv2.putText(frame_mostrar, f"GIRO {giro_cabeza:+.2f}", (440, 465),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 255, 0) if en_rango else (0, 165, 255), 2)

            self.label_ear.configure(text=f"EAR: {ear_suavizado:.3f}")
            self.label_parpadeos.configure(text=str(self.total_parpadeos))
            self.label_prolongados.configure(text=f"Prolongados: {self.total_prolongados}")
            self.label_falsos.configure(text=f"Falsos descartados: {self.total_falsos}")
            self.label_fps.configure(text=f"{self._fps:.0f} FPS")
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
                self._limpiar_video("[ Cámara oculta ]")
        return 10

    def _limpiar_video(self, texto):
        """Saca la imagen del label de video. CTkLabel 5.2.2 ignora image=None
        en su label interno de Tk, que queda apuntando a un PhotoImage ya
        liberado; al volver a mostrar la cámara Tk fallaba con
        'image "pyimageN" doesn't exist'. Por eso se limpia también el interno."""
        self.label_video.configure(image=None, text=texto)
        self.label_video._label.configure(image="")
        self.label_video.imgtk = None

    def detener_todo(self):
        """Suelta cámara y modelo. La llama la carcasa al cerrar la aplicación
        o al cerrar sesión; el panel en sí lo destruye Tk con su padre."""
        self.sistema_activo  = False
        self._grafico_activo = False  # corta el bucle after() de la gráfica EAR
        self._cerrar_debug_logger()
        if self.cap:
            self.cap.release()
            self.cap = None
        try:
            self.face_landmarker.close()
        except Exception:
            pass

# ==========================================
# EJECUCIÓN (con depuración)
# ==========================================
if __name__ == "__main__":
    # Activaciones externas se validan antes del splash y se entregan a la
    # instancia viva con ACK. Si no hay receptor, esperan al primer menú.
    _pendiente_recomendacion = None
    for _argumento in sys.argv[1:]:
        if _argumento.startswith("argos://"):
            _coincidencia = re.fullmatch(
                r"argos://recomendacion/(Leve|Moderada|Severa|BajaFrecuencia)/?", _argumento)
            if _coincidencia:
                _pendiente_recomendacion = _coincidencia[1]
                break
    if _pendiente_recomendacion and enviar_recomendacion(_pendiente_recomendacion):
        sys.exit(0)
    registrar_protocolo_argos()
    registrar_identidad_notificaciones()
    escuchar_recomendaciones()
    if _pendiente_recomendacion:
        COLA_RECOMENDACIONES.put_nowait(_pendiente_recomendacion)

    # La consola de Windows usa cp1252: un print con «→», «·» o acentos lanza
    # UnicodeEncodeError y, si ocurre dentro de un after(), corta el bucle de
    # video. Forzamos UTF-8 tolerante antes de cualquier print.
    for _flujo in (sys.stdout, sys.stderr):
        try:
            _flujo.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("DEBUG: Inicio de la aplicación.")
    # Antes de crear cualquier ventana: después Tk ya fijó las familias.
    print(f"DEBUG: Fuentes propias registradas: {registrar_fuentes_propias()}")
    try:
        # --- 1. Obtener usuario de Windows y abrir BD ---
        usuario_windows = GestorAutenticacionWindows.usuario_actual()
        print(f"DEBUG: Usuario Windows detectado: {usuario_windows}")

        # --- 1.5 Pantalla de carga (splash con el ojo de Argos) ---
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
            app.protocol("WM_DELETE_WINDOW", app._ocultar_o_cerrar)
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
