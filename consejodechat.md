# Propuestas de Mejora para el Sistema de Detección de Fatiga Ocular Basado en EAR

## Introducción

El algoritmo basado en **Eye Aspect Ratio (EAR)** constituye una técnica ampliamente utilizada para la detección de parpadeos debido a su simplicidad computacional y capacidad para operar en tiempo real. Sin embargo, utilizar únicamente un umbral fijo sobre el EAR presenta limitaciones, ya que factores como la anatomía del usuario, la iluminación, la orientación de la cabeza y el ruido generado por la detección de landmarks pueden provocar falsas detecciones.

Por ello, se propone una serie de mejoras orientadas a incrementar la precisión, robustez y confiabilidad del sistema de detección de fatiga visual.

---

# 1. Implementar una Máquina de Estados para la Detección de Parpadeos

En lugar de contabilizar un parpadeo únicamente cuando el valor del EAR cae por debajo de un umbral, se recomienda implementar una máquina de estados.

## Funcionamiento

```text
ABIERTO
    │
    │ EAR < Umbral durante N frames
    ▼
CERRADO
    │
    │ EAR > Umbral durante N frames
    ▼
PARPADEO DETECTADO
```

### Ventajas

- Evita contar ruido.
- Reduce falsos positivos.
- Elimina detecciones ocasionadas por pequeñas variaciones del rostro.
- Hace que el sistema sea mucho más estable.

---

# 2. Utilizar un Umbral Dinámico

Cada persona posee una anatomía ocular diferente.

Por esta razón no es recomendable utilizar un único valor como:

```text
EAR = 0.20
```

En su lugar, durante la calibración inicial se calcula el EAR promedio del usuario.

Ejemplo:

```text
EAR promedio = 0.31

Umbral = EAR_promedio × 0.75

Umbral = 0.2325
```

Otro usuario podría obtener:

```text
EAR promedio = 0.24

Umbral = 0.18
```

### Beneficios

- Mayor personalización.
- Menor cantidad de falsos positivos.
- Mejor adaptación a diferentes usuarios.

---

# 3. Aplicar un Filtro al EAR

El valor del EAR fluctúa naturalmente entre un frame y otro.

Estas pequeñas variaciones pueden provocar falsas detecciones.

Se recomienda utilizar un filtro de suavizado.

## Opción 1: Media móvil

```text
EAR_filtrado =
(EAR1 + EAR2 + EAR3 + EAR4 + EAR5) / 5
```

## Opción 2: Filtro exponencial

```text
EAR_filtrado =
0.8 × EAR_anterior +
0.2 × EAR_actual
```

### Beneficios

- Reduce ruido.
- Hace más estable la curva del EAR.
- Mejora la detección de parpadeos.

---

# 4. Analizar Ambos Ojos Independientemente

Muchos algoritmos únicamente utilizan el promedio:

```text
EAR = (EAR_izquierdo + EAR_derecho)/2
```

Una mejor alternativa consiste en calcular ambos ojos de manera independiente.

```text
EAR izquierdo

EAR derecho

↓

EAR promedio
```

Además, se puede verificar que ambos ojos se cierren prácticamente al mismo tiempo.

Si únicamente un ojo cambia significativamente, probablemente sea ruido o un error en la detección.

---

# 5. Validar la Calidad del Seguimiento Facial

Antes de calcular el EAR es recomendable verificar que MediaPipe detecte correctamente todos los landmarks necesarios.

```text
¿Landmarks válidos?

Sí
↓

Calcular EAR

No
↓

Ignorar frame
```

Esto evita errores cuando:

- El usuario sale parcialmente del cuadro.
- Existe poca iluminación.
- El rostro se encuentra parcialmente oculto.

---

# 6. Detectar la Orientación de la Cabeza

Cuando la cabeza rota demasiado, el EAR deja de representar correctamente la apertura del ojo.

Se recomienda calcular la inclinación mediante los landmarks faciales.

Por ejemplo:

```text
Rotación menor a 25°

Evaluación normal
```

```text
Rotación mayor a 30°

Mostrar mensaje:

"Mire hacia la cámara para continuar."
```

### Beneficios

- Mayor precisión.
- Menos falsos positivos.

---

# 7. Medir la Duración del Parpadeo

No solamente debe contarse el número de parpadeos.

También es importante medir cuánto tiempo permanecen cerrados los ojos.

Ejemplo:

```text
Parpadeo 1

170 ms

Parpadeo 2

220 ms

Parpadeo 3

480 ms
```

La duración suele aumentar conforme aparece la fatiga ocular.

---

# 8. Clasificar los Cierres Prolongados

Los cierres largos no deberían contabilizarse como parpadeos normales.

Una clasificación útil sería:

| Tiempo | Clasificación |
|---------|---------------|
| 100–300 ms | Parpadeo normal |
| 300–500 ms | Parpadeo lento |
| >500 ms | Cierre prolongado |

Esto proporciona información adicional sobre el estado del usuario.

---

# 9. Incorporar PERCLOS

Uno de los indicadores más utilizados en investigaciones científicas sobre fatiga es el **PERCLOS (Percentage of Eye Closure)**.

Se calcula mediante:

```text
PERCLOS =
Tiempo con ojos cerrados
-------------------------
Tiempo total
```

Ejemplo:

```text
Tiempo total = 60 segundos

Tiempo con ojos cerrados = 9 segundos

PERCLOS = 15%
```

### Ventajas

- Indicador ampliamente validado.
- Excelente predictor de fatiga y somnolencia.
- Complementa al EAR.

---

# 10. Analizar la Frecuencia de Parpadeo

Además del número total de parpadeos, puede calcularse:

- Parpadeos por minuto.
- Promedio de duración.
- Variabilidad.
- Tendencia temporal.

Ejemplo:

```text
Minuto 1

15 parpadeos

Minuto 2

18 parpadeos

Minuto 3

24 parpadeos
```

El incremento progresivo puede asociarse con fatiga visual.

---

# 11. Construir un Índice de Fatiga

En lugar de tomar decisiones únicamente con el EAR, se recomienda combinar varios indicadores.

Ejemplo:

| Indicador | Peso |
|-----------|------|
| PERCLOS | 30 % |
| Duración del parpadeo | 30 % |
| Frecuencia | 20 % |
| Cierres prolongados | 10 % |
| Variabilidad del EAR | 10 % |

Posteriormente se obtiene un índice global.

Ejemplo:

| Puntaje | Estado |
|----------|--------|
| 0–30 | Normal |
| 31–60 | Fatiga leve |
| 61–80 | Fatiga moderada |
| 81–100 | Fatiga alta |

Este enfoque ofrece una evaluación mucho más robusta.

---

# 12. Mostrar una Gráfica del EAR en Tiempo Real

Visualizar la evolución del EAR facilita la interpretación del sistema.

Ejemplo:

```text
0.32 ───────────────╲──────────╲────────────

0.28

0.24

0.20

0.16
```

Cada valle representa un parpadeo.

### Beneficios

- Facilita la validación del algoritmo.
- Permite observar tendencias.
- Mejora la presentación durante la defensa de la tesis.

---

# 13. Detectar Pérdida de Seguimiento

Cuando MediaPipe pierde el rostro o los ojos, el sistema debe detener temporalmente el análisis.

Ejemplo:

```text
No se detectan ojos

↓

Pausar evaluación

↓

Esperar recuperación
```

Esto evita registrar datos erróneos.

---

# 14. Retroalimentación Visual al Usuario

Es recomendable mostrar mensajes claros durante el monitoreo.

Ejemplos:

- Estado: Normal
- Fatiga leve
- Fatiga moderada
- Fatiga alta
- Cierre prolongado detectado
- Mire hacia la cámara
- Iluminación insuficiente

Esto mejora la experiencia del usuario.

---

# Arquitectura Recomendada

```text
               Webcam
                  │
                  ▼
         MediaPipe Face Mesh
                  │
                  ▼
      Detección de Landmarks
                  │
                  ▼
      EAR Izquierdo / Derecho
                  │
                  ▼
         Filtrado del EAR
                  │
                  ▼
      Máquina de Estados
                  │
                  ├───────────────┐
                  │               │
                  ▼               ▼
          Conteo de         Duración del
          Parpadeos          Parpadeo
                  │               │
                  ├───────────────┤
                  ▼
             Cálculo PERCLOS
                  │
                  ▼
       Frecuencia de Parpadeo
                  │
                  ▼
        Índice Global de Fatiga
                  │
                  ▼
      Alertas y Recomendaciones
                  │
                  ▼
      Historial y Base de Datos
```

---

# Conclusión

La incorporación de estas mejoras permitiría transformar un sistema basado únicamente en el EAR en una herramienta de monitoreo mucho más robusta y confiable para la detección de fatiga visual.

La combinación de un umbral dinámico, una máquina de estados, filtrado de señales, análisis de ambos ojos, detección de orientación de la cabeza, cálculo de PERCLOS y un índice global de fatiga incrementa significativamente la precisión del sistema y reduce la probabilidad de falsas detecciones.

Estas mejoras, además de fortalecer la implementación técnica, aportan mayor respaldo científico al proyecto de tesis al alinearse con metodologías utilizadas en investigaciones recientes sobre monitoreo de fatiga ocular y somnolencia mediante visión por computadora.