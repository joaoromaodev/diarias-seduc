# -*- coding: utf-8 -*-
"""Gera um ícone (.ico) moderno para o sistema de Diárias SEDUC."""
from PIL import Image, ImageDraw

S = 1024  # render em alta resolução, depois reduz


def lerp(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


# ── 1) fundo com gradiente azul (cor do app) ──────────────────────────────────
TOP = (83, 109, 254)     # #536DFE-ish (mais claro)
BOT = (48, 70, 200)      # azul mais profundo
base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    gd.line([(0, y), (S, y)], fill=lerp(TOP, BOT, y / S) + (255,))
# máscara arredondada estilo "app icon"
base.paste(grad, (0, 0), rounded_mask(S, int(S * 0.225)))

# brilho diagonal sutil no topo
gloss = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gdl = ImageDraw.Draw(gloss)
gdl.ellipse([-S * 0.3, -S * 0.65, S * 1.1, S * 0.35], fill=(255, 255, 255, 28))
base = Image.alpha_composite(base, Image.composite(
    gloss, Image.new("RGBA", (S, S), (0, 0, 0, 0)), rounded_mask(S, int(S * 0.225))))

draw = ImageDraw.Draw(base)

# ── 2) folha/documento branco ─────────────────────────────────────────────────
from PIL import ImageFilter
# sombra suave do documento
sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
shd = ImageDraw.Draw(sh)
shd.rounded_rectangle([S*0.30, S*0.27, S*0.755, S*0.81], radius=int(S*0.045),
                      fill=(15, 25, 80, 120))
sh = sh.filter(ImageFilter.GaussianBlur(S*0.018))
base = Image.alpha_composite(base, sh)
draw = ImageDraw.Draw(base)

doc_l, doc_t, doc_r, doc_b = S*0.285, S*0.245, S*0.730, S*0.775
fold = S * 0.085  # canto dobrado
# corpo do documento (com canto sup. direito recortado)
draw.polygon([
    (doc_l, doc_t),
    (doc_r - fold, doc_t),
    (doc_r, doc_t + fold),
    (doc_r, doc_b),
    (doc_l, doc_b),
], fill=(255, 255, 255, 255))
# dobra do canto
draw.polygon([
    (doc_r - fold, doc_t),
    (doc_r - fold, doc_t + fold),
    (doc_r, doc_t + fold),
], fill=(206, 216, 245, 255))

# linhas de texto no documento
line_color = (150, 165, 210, 255)
lx = doc_l + S*0.045
lw = doc_r - S*0.045
ys = [0.37, 0.45, 0.53, 0.61]
for i, yy in enumerate(ys):
    y = S * yy
    end = lw if i != len(ys) - 1 else lx + (lw - lx) * 0.55
    draw.rounded_rectangle([lx, y, end, y + S*0.028], radius=S*0.014,
                           fill=line_color)

# ── 3) selo verde de "validado" (check) ───────────────────────────────────────
cx, cy, cr = S*0.690, S*0.715, S*0.135
# anel branco em volta do selo
draw.ellipse([cx-cr-S*0.022, cy-cr-S*0.022, cx+cr+S*0.022, cy+cr+S*0.022],
             fill=(255, 255, 255, 255))
# selo verde com gradiente simples (dois círculos)
draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=(34, 197, 94, 255))
draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr*0.2], fill=(46, 210, 105, 255))
# check branco
cw = S*0.030
draw.line([(cx-cr*0.45, cy+cr*0.02),
           (cx-cr*0.08, cy+cr*0.40),
           (cx+cr*0.52, cy-cr*0.42)],
          fill=(255, 255, 255, 255), width=int(cw), joint="curve")

# ── 4) exporta como .ico multi-resolução ──────────────────────────────────────
out = r"C:\Users\SEDUC\Desktop\DIARIAS_ERGON\webapp\diarias.ico"
sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = [base.resize((s, s), Image.LANCZOS) for s in sizes]
imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
# também um PNG de preview
base.resize((256, 256), Image.LANCZOS).save(
    r"C:\Users\SEDUC\Desktop\DIARIAS_ERGON\webapp\diarias_preview.png")
print("ICO salvo em:", out)
