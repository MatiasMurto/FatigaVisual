# Argos — Código destacado (para consulta con IA / redacción del libro)

Extracto curado de `detector_fatiga1.py`. Contiene solo las piezas con valor
algorítmico/científico para documentar en el libro/tesis — se omite código de
interfaz gráfica (Tkinter), tablas de la base de datos y detalles de estética.

**Stack:** Python 3.14, OpenCV, MediaPipe FaceLandmarker, CustomTkinter,
SQLite3, cryptography (AES-GCM), pywin32 + pywinrt (Windows Hello).

---

## 1. Cálculo del EAR (Eye Aspect Ratio)

Landmarks de MediaPipe FaceLandmarker usados por ojo (6 puntos, convención
estándar del paper original de Soukupová & Čech, 2016):

```python
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
```

EAR final del cuadro = promedio de ambos ojos:
```python
ear_izq = CalculadorEAR.calcular_ear_ojo(p_izq)
ear_der = CalculadorEAR.calcular_ear_ojo(p_der)
ear     = (ear_izq + ear_der) / 2.0
```

---

## 2. Umbral adaptativo por baseline (no un valor fijo)

**Problema que resuelve:** un umbral EAR fijo (ej. 0.22 para todo el mundo)
falla entre usuarios (anatomía ocular distinta), con lentes, y con cambios de
luz/distancia a la cámara. La solución: calibrar el EAR "de ojo abierto" del
usuario actual al arrancar, y adaptarlo lentamente mientras el sistema corre.

```python
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
        return

    if ojo_abierto_confiable and self._baseline_abierto is not None:
        self._baseline_abierto = ((1 - self.BASELINE_EMA) * self._baseline_abierto
                                  + self.BASELINE_EMA * ear)
        self._aplicar_umbral_desde_baseline()

def _aplicar_umbral_desde_baseline(self):
    self.p_umbral_ear = max(0.08, min(0.40, round(self._baseline_abierto * self.K_CERRAR, 3)))
```

Constantes de calibración:
```python
self.K_CERRAR        = 0.72   # umbral_cerrar = baseline * K_CERRAR
self.K_ABRIR         = 0.82   # umbral_abrir  = baseline * K_ABRIR (banda muerta anti-chattering)
self.BASELINE_CALIB_S = 2.0   # segundos iniciales para fijar el baseline
self.BASELINE_EMA     = 0.02  # peso de adaptación lenta en operación
```

**Nota de evolución del diseño:** una versión anterior recalculaba el umbral
crudo cada cuadro con percentiles sobre una ventana corta; con parpadeos
frecuentes el umbral oscilaba (0.08 ↔ 0.26 en la misma sesión) y a veces el
sistema quedaba "trabado" creyendo el ojo cerrado por 10-15 s. El baseline con
EMA lento + recalibración implícita al inicio resolvió ambos problemas.

---

## 3. Máquina de estados de parpadeo (histéresis)

En vez de un único umbral, se usan **dos** (histéresis): el ojo se considera
"cerrado" al cruzar hacia abajo `umbral_cerrar`, y "abierto" recién al cruzar
`umbral_abrir` (más alto). La banda muerta entre ambos evita que el ruido en
el borde del umbral cuente un mismo parpadeo dos veces ("chattering").

La duración del cierre se mide con `time.time()` real, **no contando cuadros**:
el loop de video no corre a FPS fijo (la carga de MediaPipe/CLAHE varía cuadro
a cuadro), así que contar cuadros hacía que el mismo parpadeo físico se
clasificara distinto según el rendimiento del momento.

```python
umbral_cerrar = self._baseline_abierto * self.K_CERRAR
umbral_abrir  = self._baseline_abierto * self.K_ABRIR
ojo_abierto_confiable = (not self.ojo_cerrado) and (ear > umbral_abrir)
self._actualizar_baseline(ear, ojo_abierto_confiable)

if not self.ojo_cerrado:
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
    self.asimetria_max_cierre = max(self.asimetria_max_cierre, asimetria)
    # Duración = tiempo de FASE PROFUNDA (EAR bajo umbral_cerrar),
    # no hasta umbral_abrir: la cola de reapertura inflaba la medición ~2x.
    if ear < umbral_cerrar:
        self.cierre_fin = time.time()
    dur_ms      = (self.cierre_fin - self.cierre_inicio) * 1000
    dur_vivo_ms = (time.time() - self.cierre_inicio) * 1000

    if dur_vivo_ms > self.EMERGENCIA_MS:
        estado_ojo = self._resolver_cierre_anomalo(ear, dur_ms, ear_suavizado, frame)
        self.ojo_cerrado, self.cierre_inicio = False, None
    elif ear > umbral_abrir:
        etiqueta, categoria = self._clasificar_cierre(dur_ms, self.asimetria_max_cierre)
        if time.time() >= self.cooldown_hasta:
            self._registrar_cierre(dur_ms, etiqueta, categoria, ear_suavizado, frame)
            self.cooldown_hasta = time.time() + (self.p_cooldown / self.FPS_REFERENCIA)
        self.ojo_cerrado, self.cierre_inicio = False, None
        estado_ojo = "Abierto"
    else:
        estado_ojo = "Cerrado..."
```

### Detección de movimiento de cabeza (falso positivo)

```python
nariz_x, nariz_y = int(face_landmarks[1].x * w), int(face_landmarks[1].y * h)
movimiento = math.dist((nariz_x, nariz_y), self.nariz_previa) if self.nariz_previa else 0
self.nariz_previa = (nariz_x, nariz_y)
# movimiento > self.umbral_movimiento (18 px/cuadro) → ignorar como giro de cabeza, no parpadeo
```

---

## 4. Clasificación por duración y detección de falsos

Umbrales en milisegundos, alineados con literatura de blink detection:

```python
self.ASIMETRIA_MAX     = 0.08   # asimetría entre ojos durante el cierre = reflejo/lente, no parpadeo real
self.RUIDO_MIN_MS      = 70     # cierre más corto = ruido de landmarks, no parpadeo humano
self.NORMAL_MAX_MS     = 300    # 70-300 ms  → parpadeo normal
self.LENTO_MAX_MS      = 500    # 300-500 ms → parpadeo lento
self.PROLONGADO_MAX_MS = 2000   # 500-2000 ms → prolongado; > 2000 ms → microsueño
self.EMERGENCIA_MS     = 15000  # red de seguridad para tracking perdido real

def _clasificar_cierre(self, duracion_ms, asimetria_max):
    """categoria ∈ {"parpadeo", "prolongado", "falso"}:
       - parpadeo   → suma a total_parpadeos y a la frecuencia (bpm)
       - prolongado → señal de fatiga, cuenta aparte (microsueño)
       - falso      → se registra para auditoría pero no cuenta"""
    if asimetria_max > self.ASIMETRIA_MAX:
        return "Falso-reflejo", "falso"     # un ojo cerró y el otro no → destello/lente
    if duracion_ms < self.RUIDO_MIN_MS:
        return "Falso-ruido", "falso"       # demasiado corto para ser humano
    if duracion_ms <= self.NORMAL_MAX_MS:
        return "Normal", "parpadeo"
    if duracion_ms <= self.LENTO_MAX_MS:
        return "Lento", "parpadeo"
    if duracion_ms <= self.PROLONGADO_MAX_MS:
        return "Prolongado", "prolongado"
    return "Microsueño", "prolongado"       # >2000 ms: con baseline estable, ojo cerrado real
```

### Recuperación ante cierre anómalo (distingue umbral roto de microsueño real)

```python
def _resolver_cierre_anomalo(self, ear_actual, dur_ms, ear_suavizado, frame):
    """Cierre en vivo > EMERGENCIA_MS. Con el baseline estable esto casi siempre
    es un cierre genuinamente largo (microsueño): se registra como prolongado
    SIN tocar el baseline. Solo si el EAR actual está cerca del baseline (el ojo
    en realidad está abierto y el baseline quedó bajo) se fuerza recalibración."""
    ref = self._baseline_abierto if self._baseline_abierto else ear_actual
    if ear_actual >= 0.85 * ref:
        self._baseline_abierto = ear_actual
        self._aplicar_umbral_desde_baseline()
        self.total_falsos += 1
        return "Recalibrando baseline"
    if time.time() >= self.cooldown_hasta:
        self._registrar_cierre(dur_ms, "Cierre-largo", "prolongado", ear_suavizado, frame)
        self.cooldown_hasta = time.time() + (self.p_cooldown / self.FPS_REFERENCIA)
    return "Cierre prolongado real"
```

---

## 5. PERCLOS (Percentage of Eye Closure)

Métrica estándar en investigación de somnolencia: % de tiempo real (no de
cuadros) con los ojos cerrados, en una ventana móvil de 60 s.

```python
self.PERCLOS_VENTANA = 60.0  # segundos de ventana móvil

def _actualizar_perclos(self, cerrado):
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
```

---

## 6. Índice de fatiga ponderado (0-100)

Combina cinco señales en un puntaje único, con clasificación en 4 niveles.
**Los pesos son ilustrativos** (documentado explícitamente en el código),
pensados para ajustarse con datos reales antes de citarlos como resultado
científico validado:

```python
PESOS_INDICE = {
    "perclos":      0.30,
    "duracion":     0.30,
    "frecuencia":   0.20,
    "prolongados":  0.10,
    "variabilidad": 0.10,
}

def _calcular_indice_fatiga(self):
    ahora = time.time()

    score_perclos = min(100.0, self.perclos_actual)

    # Duración promedio de cierres recientes, normalizada contra el techo
    # de "cierre prolongado" (derivado de p_frames_max) como referencia de 100%.
    techo_duracion_ms = max(1.0, (self.p_frames_max / self.FPS_REFERENCIA) * 1000)
    dur_prom_ms = (sum(self.duraciones_parpadeo) / len(self.duraciones_parpadeo)) * 1000 \
                  if self.duraciones_parpadeo else 0.0
    score_duracion = max(0.0, min(100.0, (dur_prom_ms / techo_duracion_ms) * 100.0))

    # Frecuencia: <15 parpadeos/min empieza a sumar fatiga (parpadeo reducido
    # = fijación prolongada en pantalla / ojo reseco).
    recientes = [t for t in self.historial_tiempos if ahora - t <= 60]
    bpm = len(recientes)
    score_frecuencia = max(0.0, min(100.0, (15 - bpm) / 15 * 100.0))

    # Proporción de cierres prolongados entre los últimos eventos.
    score_prolongados = (sum(self.prolongados_recientes) / len(self.prolongados_recientes)) * 100.0 \
                         if self.prolongados_recientes else 0.0

    # Variabilidad del EAR reciente (jitter alto = pérdida de estabilidad).
    if len(self.historico_ear) >= 10:
        variabilidad = statistics.pstdev(self.historico_ear)
        score_variabilidad = max(0.0, min(100.0, (variabilidad / 0.10) * 100.0))
    else:
        score_variabilidad = 0.0

    score = (score_perclos * PESOS_INDICE["perclos"] +
             score_duracion * PESOS_INDICE["duracion"] +
             score_frecuencia * PESOS_INDICE["frecuencia"] +
             score_prolongados * PESOS_INDICE["prolongados"] +
             score_variabilidad * PESOS_INDICE["variabilidad"])
    score = round(max(0.0, min(100.0, score)), 1)

    if score <= 30:      clasificacion = "Normal"
    elif score <= 60:    clasificacion = "Leve"
    elif score <= 80:    clasificacion = "Moderada"
    else:                clasificacion = "Alta"

    return score, clasificacion
```

---

## 7. Prueba guiada de validación (protocolo científico)

Un asistente paso a paso que le pide al usuario ejecutar patrones de parpadeo
controlados (rápidos, lentos, cierres largos, reposo) y compara lo detectado
contra lo esperado — evidencia de validación del algoritmo, generada
automáticamente:

```python
GUIA_FASES = [
    ("•", "Calibración",       "Mirá la cámara con los ojos MUY ABIERTOS y quieto", 3,  None, None),
    ("A", "Parpadeos normales","Parpadeá NORMAL (rápido y natural) — 5 veces",      12, 5,    "parpadeo"),
    ("B", "Parpadeos lentos",  "Parpadeá LENTO (cerrá ~1 s y abrí) — 5 veces",      15, 5,    "parpadeo"),
    ("C", "Cierres largos",    "Cerrá los ojos 3 SEGUNDOS y abrí — 3 veces",        18, 3,    "prolongado"),
    ("D", "Reposo",            "Quieto, ojos ABIERTOS, tratá de NO parpadear",      10, 0,    "falso"),
]
```

Cada evento detectado durante la prueba se cuenta en la fase activa
(`guia_conteos`), y al finalizar se genera un resumen `esperado vs. detectado`
por fase, con veredicto OK / ~ / X según la diferencia.

Resultado de validación real (log de sesión, referencia para el libro):
```
Fase                    Esper.  Detect.  Desglose            Result.
--------------------------------------------------------------------
A Parpadeos normales    5       5        P:5 L:0 F:0         OK
B Parpadeos lentos      5       6        P:4 L:2 F:0         OK
C Cierres largos        3       3        P:1 L:2 F:0         OK
D Reposo                0       0        P:0 L:0 F:0         OK
```

---

## 8. Seguridad: cifrado de datos (AES-GCM)

Todo dato persistido en la base (fecha, EAR, duración, clasificación, etc.)
se cifra antes de guardarse:

```python
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
            data      = base64.urlsafe_b64decode(token.encode())
            nonce, ct = data[:12], data[12:]
            return self._aesgcm.decrypt(nonce, ct, None).decode()
        except Exception:
            return token  # dato legado sin cifrar
```

PIN de perfiles internos, hasheado con PBKDF2-HMAC-SHA256 (200.000
iteraciones, salt aleatorio por PIN) — nunca en texto plano:

```python
class GestorPin:
    ITERACIONES = 200_000

    @classmethod
    def hashear(cls, pin: str) -> str:
        salt = os.urandom(16)
        h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, cls.ITERACIONES)
        return f"{salt.hex()}${h.hex()}"

    @classmethod
    def verificar(cls, pin: str, almacenado: str) -> bool:
        salt_hex, hash_hex = almacenado.split("$")
        h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), cls.ITERACIONES)
        return h.hex() == hash_hex
```

---

## 9. Autenticación: Windows Hello (biometría nativa)

Cadena de verificación de identidad para la cuenta administradora (la de la
sesión de Windows), en orden de preferencia:

```python
class GestorAutenticacionWindows:
    @staticmethod
    def hello_disponible():
        avail = asyncio.run(winrt_ui.UserConsentVerifier.check_availability_async())
        return int(avail) == 0  # 0 = Available

    @staticmethod
    def verificar_hello(mensaje="Confirmá tu identidad"):
        """Muestra el diálogo nativo de Windows Hello (PIN/huella/rostro).
        True solo si el resultado es Verified."""
        resultado = asyncio.run(asyncio.wait_for(
            winrt_ui.UserConsentVerifier.request_verification_async(mensaje),
            timeout=120))
        return int(resultado) == 0  # 0 = Verified

    @staticmethod
    def es_cuenta_microsoft(usuario=None):
        """Detecta cuenta Microsoft (MSA) vinculada leyendo el registro
        HKCU\\...\\IdentityCRL\\UserExtendedProperties."""
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\IdentityCRL\UserExtendedProperties")
        return winreg.QueryInfoKey(k)[0] > 0

    @staticmethod
    def validar_password_local(usuario, password):
        """Contraseña de Windows vía LogonUser — solo funciona con cuentas
        LOCALES clásicas; las MSA no exponen hash validable localmente."""
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
```

**Cadena de fallback aplicada en el login** (documentar en el libro como
decisión de diseño): 1) Windows Hello si está disponible → 2) contraseña de
Windows real si es cuenta local sin Hello → 3) PIN propio de la app (PBKDF2)
si es cuenta Microsoft sin Hello. Ningún camino queda sin verificación.

*Hallazgo técnico relevante:* validar la contraseña de una cuenta Microsoft
(MSA) **no es posible localmente** — se probaron 4 vías (`LogonUser`,
`winsdk`, Windows Hello vía PowerShell suelto, SSPI/NTLM) y todas fallan por
límites reales de Windows (MSA no expone hash validable sin conexión online).
La solución que sí funciona es `winrt-runtime` (pywinrt) + Windows Hello
nativo, que solo verifica al usuario de la sesión activa.

---

## 10. Resumen de arquitectura (para el capítulo de diseño)

```
Cámara (OpenCV) → MediaPipe FaceLandmarker → landmarks de ojo
    → CalculadorEAR (EAR por cuadro)
    → Máquina de estados con histéresis (baseline adaptativo)
        → clasificación por duración + asimetría
        → PERCLOS (ventana móvil 60s)
        → Índice de fatiga ponderado (0-100)
    → SQLite cifrado (AES-GCM) por usuario/perfil
    → Prueba guiada (protocolo de validación automatizado)
```

Autenticación: selector de perfiles (estilo Netflix) — cuenta de Windows
(Administrador, verificada con Hello/contraseña/PIN según disponibilidad) +
perfiles internos (PIN opcional, PBKDF2).
