# Prompt de diseño — Fatiga Ocular EAR (estilo "health app / reloj")

## Concepto
No una app de fitness genérica (pasos, calorías). Esto ser un **monitor de
vigilancia/somnolencia** — más cerca de un panel de instrumentos de auto o un
monitor de laboratorio de sueño que de una app de conteo de pasos. La estética
debe transmitir "instrumento de precisión en vivo", no "bienestar y colores
pastel".

## Paleta (fondo oscuro nocturno, con versión clara)
- Fondo: `#0A0E17` (azul-negro nocturno, no negro puro)
- Superficie/tarjetas: `#131A2A`
- Texto principal: `#E8ECF4`
- Texto secundario: `#8A93A8`
- Acento primario ("en vigilancia"): `#37D6C6` (teal/cian, ligado al recuadro
  verde de detección que ya tiene la app)
- Escalada semántica de fatiga (Normal → Alta): `#37D6C6` → `#F5B942` (ámbar)
  → `#F2884B` (naranja) → `#F0496A` (carmesí) — coincide con tus 4
  clasificaciones reales (Normal/Leve/Moderada/Alta)

## Tipografía
- Números/lecturas en vivo: **monoespaciada** (Cascadia Code / Consolas) —
  sensación de instrumento, números tabulares alineados
- Títulos y etiquetas: Segoe UI (nativa de Windows, honesto para una app de
  escritorio Windows, no una tipografía "de moda" génerica)

## Layout
- Panel lateral izquierdo: perfil activo + navegación (calcado de la UI real)
- Centro: **medidor radial grande** (arco, no anillo completo) para el Índice
  de Fatiga, con el color semántico
- Tarjetas secundarias: EAR en vivo + mini-gráfico, PERCLOS (arco chico),
  frecuencia de parpadeo, desglose Parpadeos/Prolongados/Falsos
- Panel de cámara: placeholder oscuro con el recuadro verde + letra de fase
  (igual a como ya funciona hoy)
- Franja inferior: resumen de la última prueba guiada (5/5, 3/3, etc.)

## Qué evitar (para no caer en "diseño genérico de IA")
- Nada de gradiente violeta-a-azul
- Nada de Inter/Space Grotesk como tipografía "seguridad"
- Nada de `rounded-lg` en todo, ni tarjetas con barra de acento redondeada
- Nada de emojis como marcadores decorativos de sección
