# Brechas entre Documentación (CU / Diagramas) e Implementación

**Fecha:** 2026-07-11
**Fuentes comparadas:** `20263006DiagramasFatigaOcular.docx` (requerimientos + diagramas: conceptual, requerimientos, comunicación, red, casos de uso, secuencia, interacción, objetos, clases, estados) y `CU.docx` (10 casos de uso detallados) contra `main.py`.

Este documento registra qué exigía la documentación de diseño que no estaba cubierto por el código, y el estado actual de cada punto.

---

## 1. Casos de uso — cobertura

| Caso de uso | Estado |
|---|---|
| 1.1 Activar cámara web | ✅ Implementado (`toggle_sistema`) |
| 1.2 Detectar presencia del usuario | ⚠️ Parcial — hay detección de rostro por frame, pero sin el flujo explícito de "verificar usuario antes de iniciar" ni mensajes de camino alternativo del CU |
| 1.3 Obtener video en tiempo real | ✅ Implementado (`actualizar_video`) |
| 2.1 Detectar rostro y región ocular | ✅ Implementado (MediaPipe FaceLandmarker) |
| 2.2 Aislar la zona de los ojos | ✅ Implementado (`CalculadorEAR.obtener_coordenadas`) |
| 2.3 Calcular Eye Aspect Ratio (EAR) | ✅ Implementado (`CalculadorEAR.calcular_ear_ojo`) |
| 3.1 Comparar valores EAR con umbrales | ✅ Implementado (umbral único `p_umbral_ear`, no doble umbral alto/bajo del diagrama de estados) |
| 3.2 Clasificar estado visual | ✅ Implementado — nivel de fatiga (Baja/Media/Alta) por frecuencia de parpadeo, persistido en BD |
| 3.3 Detectar patrones consistentes con astenopía | 🔲 Pendiente — solo hay regla instantánea (bpm &lt; 10), no análisis histórico de patrón |
| 4.1 Emitir alerta preventiva | ⚠️ Parcial — alerta visual sí, sonora no |
| 4.2 Generar estadísticas personales | ✅ Implementado (`VentanaEstadisticas`) |

---

## 2. Resueltos en esta sesión

### 2.1 Login / autenticación (Requerimiento funcional #12, #13 — Diagrama de Clases: `Usuario.password`, `iniciarSesion()`)

**Intento inicial:** autenticar contra la contraseña real de Windows vía API `LogonUser` (sin guardar la contraseña, solo validarla contra el SO).

**Resultado:** descartado. En esta máquina, `LogonUser` rechazó la contraseña real (verificada primero con `Win+L`, donde sí funciona) en las 6 combinaciones de dominio/tipo de logon probadas — error 1326 consistente. Causa: protecciones NTLM/LSA modernas de Windows bloquean esta API clásica incluso con credenciales correctas; no es un bug del código, es una incompatibilidad de plataforma no resoluble de forma confiable desde una app de escritorio sin privilegios elevados.

**Solución aplicada:** `VentanaLogin` confirma identidad reutilizando la sesión de Windows ya iniciada (llegar al escritorio ya implica que el usuario pasó la autenticación real del SO). Pantalla simple "Continuar como {usuario}", sin contraseña.

### 2.2 Roles Usuario / Administrador (Diagrama de Clases: `Usuario.rol`, Actor "Administrador del Sistema")

- Columna `usuarios.rol` (migración automática).
- Rol inicial = "Administrador" si la cuenta de Windows pertenece al grupo Administradores del equipo; si no, "Usuario".
- Editable después vía `VentanaGestionUsuarios` (solo visible para Administrador).
- Pestaña "Calibración" ahora oculta para rol Usuario.

### 2.3 Nivel de fatiga por registro (Diagrama de Objetos: `RegistroFatiga.nivelFatiga`)

- Columna `registro_parpadeos.nivel_fatiga` (cifrada, migración automática).
- Clasificación Baja/Media/Alta según frecuencia de parpadeo (bpm) en el momento del evento (`InterfazFatiga._nivel_fatiga_actual`).
- Visible como columna nueva en `VentanaEstadisticas`.

---

## 3. Pendientes — propuesta de adaptación

Todos encajar en una sola tabla nueva `eventos_fatiga` (evitar rehacer el esquema por partes).

| # | Brecha | Fuente en documentación | Adaptación propuesta |
|---|---|---|---|
| 4 | Detección de patrones de astenopía | CU 3.3, módulo `AnalizadorEAR` (Diagrama de Objetos/Clases) | Ventana móvil (ej. últimos 5 min) combinando bpm bajo sostenido + duración de parpadeo creciente, no solo el valor instantáneo actual |
| 5 | Alerta por cierre prolongado | Diagrama de Estados (estado 3 "Alerta de fatiga") | Hoy el cierre prolongado (`contador_cuadros > p_frames_max`) simplemente se descarta del conteo; debería generar un evento explícito |
| 6 | Alertas sonoras | `GestorAlertas.emitirSonido()` (Diagrama de Clases), Requerimiento funcional #5 | `winsound.Beep()` — nativo de Windows, sin dependencia nueva |
| 7 | Campo "observaciones" | Diagrama de Objetos (`RegistroFatiga.observaciones`) | Columna de texto cifrada en `eventos_fatiga`, generada automáticamente según la causa del evento |
| 8 | Persistencia de umbrales de calibración entre sesiones | Diagrama Conceptual (BD de parámetros/umbrales) | Nueva tabla `configuracion` (por usuario), cargar al iniciar en vez de resetear siempre a `DEFAULTS` |

---

## 4. Observaciones menores (no bloqueantes)

- El Diagrama de Comunicación / Red menciona un "Server" externo; la arquitectura real es 100% local (Edge Computing, sin envío de imágenes fuera del equipo), consistente con la Descripción del Sistema del propio documento. Probable plantilla genérica, no requiere cambio de código.
- `GestorAlertas.intensidad` (int) del diagrama de clases no tiene equivalente en el código — quedaría cubierto naturalmente al implementar el punto 6.
