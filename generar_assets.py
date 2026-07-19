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


def _lienzo(size, escala=4):
    """Lienzo RGBA supersampleado (dibujar grande, reducir = líneas suaves)."""
    S = size * escala
    return Image.new("RGBA", (S, S), (0, 0, 0, 0)), S


def _reducir(img, size):
    return img.resize((size, size), Image.LANCZOS)


def icono_logout(size=24, color=(255, 255, 255, 255)):
    """Puerta con flecha de salida (reemplaza el emoji 🚪, que no renderiza
    bien en Tkinter/Windows)."""
    img, S = _lienzo(size)
    d = ImageDraw.Draw(img)
    w = max(2, S // 14)
    # Marco de puerta (rectángulo abierto a la derecha)
    d.rounded_rectangle([S*0.12, S*0.14, S*0.52, S*0.86], radius=S*0.05, outline=color, width=w)
    # Flecha saliendo
    y = S * 0.5
    d.line([S*0.42, y, S*0.88, y], fill=color, width=w)
    d.line([S*0.68, y - S*0.18, S*0.88, y], fill=color, width=w)
    d.line([S*0.68, y + S*0.18, S*0.88, y], fill=color, width=w)
    return _reducir(img, size)


def icono_nav(nombre, size=20, color=(176, 184, 199, 255)):
    img, S = _lienzo(size)
    d = ImageDraw.Draw(img)
    w = max(2, S // 12)
    if nombre == "control":
        d.ellipse([S*0.1, S*0.1, S*0.9, S*0.9], outline=color, width=w)
        d.line([S*0.5, S*0.5, S*0.5, S*0.22], fill=color, width=w)
        d.line([S*0.5, S*0.5, S*0.72, S*0.6], fill=color, width=w)
    elif nombre == "calib":
        for i, x in enumerate([0.3, 0.6, 0.42]):
            yy = S * (0.22 + i * 0.28)
            d.line([S*0.08, yy, S*0.92, yy], fill=color, width=max(2, w-1))
            d.ellipse([S*x-S*0.07, yy-S*0.07, S*x+S*0.07, yy+S*0.07], fill=color)
    elif nombre == "stats":
        base = S * 0.86
        for x, h in [(0.18, 0.35), (0.44, 0.6), (0.7, 0.45)]:
            d.rectangle([S*x, base - S*h, S*x + S*0.16, base], fill=color)
    elif nombre == "chart":
        d.line([S*0.1, S*0.65, S*0.35, S*0.4, S*0.55, S*0.55, S*0.9, S*0.15],
               fill=color, width=w, joint="curve")
        r = S * 0.06
        d.ellipse([S*0.9-r, S*0.15-r, S*0.9+r, S*0.15+r], fill=color)
    elif nombre == "about":
        d.ellipse([S*0.1, S*0.1, S*0.9, S*0.9], outline=color, width=w)
        r = S * 0.06
        d.ellipse([S*0.5-r, S*0.27-r, S*0.5+r, S*0.27+r], fill=color)
        d.line([S*0.5, S*0.42, S*0.5, S*0.72], fill=color, width=w)
    return _reducir(img, size)


def main():
    os.makedirs(ASSETS, exist_ok=True)

    logo = dibujar_ojo(256, 1.0)
    logo.save(os.path.join(ASSETS, "logo_ojo.png"))
    logo.save(os.path.join(ASSETS, "logo_ojo.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])

    for nombre, ap in [("ojo_abierto", 1.0), ("ojo_semi", 0.45), ("ojo_cerrado", 0.05)]:
        dibujar_ojo(160, ap).save(os.path.join(ASSETS, f"{nombre}.png"))

    icono_logout().save(os.path.join(ASSETS, "icon_logout.png"))
    for nombre in ("control", "calib", "stats", "chart", "about"):
        icono_nav(nombre).save(os.path.join(ASSETS, f"icon_nav_{nombre}.png"))

    print("Assets generados en:", ASSETS)
    for f in sorted(os.listdir(ASSETS)):
        print("  ", f)


if __name__ == "__main__":
    main()
