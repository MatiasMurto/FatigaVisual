# Punto de recuperación — Sistema de Fatiga Ocular (EAR)

**Fecha:** 2026-07-11
**Archivo principal:** `main.py`

Este documento describe el estado funcional actual del proyecto, para poder retomarlo o revertir a este punto si una modificación futura rompe algo.

---

## 1. Qué hace el sistema

Aplicación de escritorio (Windows) que detecta fatiga ocular en tiempo real a partir de la cámara web:

- Usa **MediaPipe FaceLandmarker** para obtener landmarks faciales por frame.
- Calcula el **EAR (Eye Aspect Ratio)** de ambos ojos.
- Detecta parpadeos mediante una máquina de estados basada en umbral de EAR + frames consecutivos.
- Calcula frecuencia de parpadeo (parpadeos/minuto) y alerta si es muy baja (posible fatiga).
- Persiste cada parpadeo en SQLite, con fecha/hora y valor EAR **cifrados** (AES-256-GCM).
- Soporta múltiples usuarios, con estadísticas e historial por usuario.
- Incluye auto-calibración guiada (ojos abiertos → parpadeo normal) y ajuste manual por sliders.
- GUI hecha con `customtkinter`.

---

## 2. Estructura del código (`main.py`)

| Clase | Responsabilidad |
|---|---|
| `GestorCifrado` | Cifra/descifra valores con AES-256-GCM. Genera/lee `secret.key`. |
| `GestorBD` | Acceso a `fatiga_ocular.db` (SQLite): usuarios, registro de parpadeos, migración de datos legados sin cifrar, estadísticas, historial. |
| `CalculadorEAR` | Índices de landmarks de cada ojo (MediaPipe FaceMesh) y fórmula EAR. |
| `VentanaEstadisticas` | Ventana (`CTkToplevel`) con tarjetas resumen + tabla de últimos 50 registros. |
| `InterfazFatiga` | Ventana principal: UI, loop de video, lógica de detección, calibración. |

Modelo de MediaPipe (`face_landmarker.task`) se descarga automáticamente si no existe en el directorio del proyecto.

---

## 3. Cambios aplicados en esta sesión

### 3.1 Imagen de cámara estirada / poco fluida (resuelto)

**Causa:** el "zoom digital al rostro" recortaba una región variable alrededor de la cara y la forzaba a 640×480 sin respetar proporción — el recorte cambiaba de tamaño cada frame, generando estiramiento y saltos.

**Solución aplicada:**
- Se eliminó el zoom/recorte al rostro. Ahora se muestra el **frame completo real de la cámara**.
- Nueva función `InterfazFatiga._ajustar_a_marco(frame, ancho_marco, alto_marco)`: redimensiona respetando la proporción real y rellena con barras negras (letterbox) si hace falta, en vez de deformar la imagen.
- La imagen mostrada ahora siempre incluye el dibujo de los ojos y el texto "PARPADEO!" (antes, en algunos casos se mostraba el frame sin ese overlay por un orden incorrecto de operaciones).
- Apertura de cámara con backend `cv2.CAP_DSHOW` + `CAP_PROP_BUFFERSIZE = 1`, para reducir latencia/lag típico de Windows y mejorar la fluidez percibida.

### 3.2 Parpadeos rápidos no se contaban (resuelto)

**Causa:** la detección usaba `ear_suavizado`, un promedio móvil de los últimos `buffer_ear` frames (default 5). Un parpadeo rápido (1-2 frames) se diluía en ese promedio y nunca cruzaba el umbral, o cruzaba muy pocos frames, insuficiente contra `frames_cons`.

**Solución aplicada:**
- La máquina de estados de detección de parpadeo ahora usa el **EAR crudo** (`ear`, sin promediar) — enfoque estándar en la literatura de detección de parpadeo por EAR.
- `ear_suavizado` (promedio móvil) se conserva **únicamente** para el valor mostrado en pantalla (label "EAR:"), no interviene en la decisión de contar o no un parpadeo.
- La auto-calibración también procesa ahora el EAR crudo, consistente con la detección.
- `frames_cons` (frames consecutivos mínimos bajo el umbral para validar un parpadeo) se bajó de **3 a 2** por defecto, para compensar parpadeos cortos con pocos frames capturados.

### 3.3 Entorno de ejecución (resuelto)

- `requirements.txt` tenía una versión inexistente: `opencv-python==4.13.0` → corregido a `opencv-python==4.13.0.92`.
- Se creó un entorno virtual `.venv` en la raíz del proyecto con todas las dependencias instaladas y funcionando (Python 3.14.6).
- Se agregó `.vscode/settings.json` para que VS Code / Code Runner usen el intérprete de `.venv` en vez del Python global del sistema (que no tenía las dependencias instaladas).

---

## 4. Parámetros de calibración (valores por defecto actuales)

```python
DEFAULTS = {
    "umbral_ear":  0.22,
    "frames_cons": 2,     # bajado de 3 → 2 en esta sesión
    "buffer_ear":  5,     # solo afecta el valor mostrado en pantalla, no la detección
    "brillo":      0,
    "contraste":   1.0,
    "clahe":       3.5,
}
```

Otros parámetros ajustables por slider (no forman parte de `DEFAULTS` pero sí de la calibración en vivo):

- `p_frames_max` (default 15): frames máximos de cierre para considerarlo parpadeo (más que eso = "cierre largo", ignorado del conteo).
- `p_cooldown` (default 0): frames de espera tras contar un parpadeo antes de poder contar otro.

---

## 5. Cómo correr el proyecto

```powershell
# Activar entorno e instalar dependencias (ya hecho, dejar como referencia)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Ejecutar
.\.venv\Scripts\python.exe main.py
```

En VS Code: seleccionar el intérprete `.venv\Scripts\python.exe` (Ctrl+Shift+P → "Python: Select Interpreter"). Code Runner ya está configurado en `.vscode/settings.json` para usar ese mismo intérprete.

---

## 6. Advertencias conocidas (no bloqueantes)

- Logs informativos de MediaPipe/XNNPACK y TensorFlow Lite al iniciar: normales, no son errores.
- `UserWarning` de `customtkinter` sobre `CTkLabel` al ocultar la cámara (`configure(image="", text=...)` pasa un string en vez de `CTkImage`): estético, no afecta funcionalidad. Pendiente de limpieza menor si se quiere silenciar.

---

## 7. Pendientes / posibles próximos pasos

- Validar en uso real que los parpadeos rápidos ahora se cuentan correctamente (pendiente de confirmación del usuario tras el cambio de la sección 3.2).
- Si aún se pierden parpadeos: considerar umbral relativo (% de caída desde el EAR de ojos abiertos calibrado) en vez de umbral absoluto, o medir la ventana de detección en milisegundos reales en vez de cantidad de frames (para independizarse de variaciones de FPS).
- Limpiar el warning de `CTkImage` mencionado en la sección 6.
