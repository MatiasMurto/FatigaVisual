"""
Genera los recursos del logo de Argos (ojo) a partir del diseño de Ojo.svg,
redibujándolo con Pillow (Tkinter no renderiza SVG).

Produce en assets/:
  logo_ojo.png        256px, ojo abierto — logo en ventanas
  logo_ojo.ico        multi-size (16/32/48/64/256) — ícono de ventana
  ojo_abierto.png     160px \
  ojo_semi.png        160px  } frames de la animación de parpadeo (carga)
  ojo_cerrado.png     160px /

Se ejecuta una sola vez (o cuando cambie el diseño):  python generar_assets.py
"""
import os
from PIL import Image, ImageDraw, ImageChops

AZUL  = (56, 182, 255, 255)   # #38b6ff — fondo
NEGRO = (16, 15, 13, 255)     # #100f0d — ojo
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _almendra(S, cx, cy, W, H):
    """Máscara (L) de la forma de ojo: intersección de dos círculos iguales
    desplazados verticalmente → lente de ancho W y alto H."""
    H = max(H, S * 0.03)
    dy = (W * W - H * H) / (4 * H)
    R = dy + H / 2
    m1 = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m1).ellipse([cx - R, (cy + dy) - R, cx + R, (cy + dy) + R], fill=255)
    m2 = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m2).ellipse([cx - R, (cy - dy) - R, cx + R, (cy - dy) + R], fill=255)
    return ImageChops.multiply(m1, m2)


def dibujar_ojo(S, apertura=1.0):
    """apertura ∈ [0,1]: 1 = ojo abierto, 0 = cerrado."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Fondo: rectángulo redondeado azul (como el SVG)
    m = int(S * 0.03)
    d.rounded_rectangle([m, m, S - m, S - m], radius=int(S * 0.19), fill=AZUL)

    cx = cy = S / 2
    W = S * 0.72
    H = S * 0.42 * apertura
    mask = _almendra(S, cx, cy, W, H)

    # Blanco del ojo (negro en este diseño)
    capa = Image.new("RGBA", (S, S), NEGRO)
    img.paste(capa, (0, 0), mask)

    # Iris (azul) + pupila (negra), recortados a la forma del ojo
    if apertura > 0.35:
        esc = min(1.0, (apertura - 0.35) / 0.55)
        r_iris = S * 0.135 * (0.5 + 0.5 * esc)
        r_pup  = S * 0.065 * (0.5 + 0.5 * esc)
        capa_iris = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        di = ImageDraw.Draw(capa_iris)
        di.ellipse([cx - r_iris, cy - r_iris, cx + r_iris, cy + r_iris], fill=AZUL)
        di.ellipse([cx - r_pup, cy - r_pup, cx + r_pup, cy + r_pup], fill=NEGRO)
        capa_iris.putalpha(ImageChops.multiply(capa_iris.getchannel("A"), mask))
        img.alpha_composite(capa_iris)

    return img


def main():
    os.makedirs(ASSETS, exist_ok=True)

    logo = dibujar_ojo(256, 1.0)
    logo.save(os.path.join(ASSETS, "logo_ojo.png"))
    logo.save(os.path.join(ASSETS, "logo_ojo.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])

    for nombre, ap in [("ojo_abierto", 1.0), ("ojo_semi", 0.45), ("ojo_cerrado", 0.05)]:
        dibujar_ojo(160, ap).save(os.path.join(ASSETS, f"{nombre}.png"))

    print("Assets generados en:", ASSETS)
    for f in sorted(os.listdir(ASSETS)):
        print("  ", f)


if __name__ == "__main__":
    main()
