"""Estilo compartido de las figuras.

Centralizar el estilo aqui evita que cada notebook invente su propia paleta y
que las figuras del documento final se vean como de estudios distintos.

La paleta es la instancia de referencia del sistema de visualizacion: solo se
usan los tres primeros colores categoricos, que son los unicos validados para
todos los pares bajo deficiencias de vision cromatica. Con mas de tres
categorias no se agregan colores: se ordena por magnitud y se usa un solo tono,
o se separa en varias figuras.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

# -- Tokens de color --------------------------------------------------------- #
SERIE_1 = "#2a78d6"  # azul
SERIE_2 = "#eb6834"  # naranja
SERIE_3 = "#1baf7a"  # aqua
SERIES = (SERIE_1, SERIE_2, SERIE_3)

SUPERFICIE = "#fcfcfb"
TINTA_PRIMARIA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
TINTA_TENUE = "#8a8a85"
REJILLA = "#e5e4e0"

#: Rampa secuencial de un solo tono, para magnitudes (mapas de calor).
RAMPA_AZUL = LinearSegmentedColormap.from_list("azul_secuencial", ["#eef4fc", SERIE_1])


def aplicar_estilo() -> None:
    """Configura matplotlib: rejilla discreta, sin marcos, texto en tinta."""
    plt.rcParams.update(
        {
            "figure.facecolor": SUPERFICIE,
            "axes.facecolor": SUPERFICIE,
            "savefig.facecolor": SUPERFICIE,
            "figure.dpi": 120,
            "savefig.dpi": 120,
            "font.size": 10,
            "text.color": TINTA_PRIMARIA,
            "axes.labelcolor": TINTA_SECUNDARIA,
            "axes.edgecolor": REJILLA,
            "axes.linewidth": 0.8,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.titlepad": 14,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": REJILLA,
            "grid.linewidth": 0.8,
            "xtick.color": TINTA_SECUNDARIA,
            "ytick.color": TINTA_SECUNDARIA,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2,
            "lines.markersize": 8,
        }
    )


def limpiar_ejes(ax, ejes: Sequence[str] = ("top", "right")) -> None:
    """Quita los marcos que no aportan informacion."""
    for lado in ejes:
        ax.spines[lado].set_visible(False)


def barras_horizontales(
    ax,
    etiquetas: Sequence[str],
    valores: Sequence[float],
    color: str = SERIE_1,
    formato: str = "{:,.0f}",
    destacar: Optional[str] = None,
) -> None:
    """Barras horizontales ordenadas, con el valor rotulado al final.

    Un solo tono: la longitud ya codifica la magnitud, agregar color por
    categoria seria redundante y rompe la legibilidad con mas de tres series.
    ``destacar`` pinta una barra en el segundo color para senalarla.
    """
    colores: List[str] = [SERIE_2 if e == destacar else color for e in etiquetas]
    barras = ax.barh(list(etiquetas), list(valores), color=colores, height=0.68)

    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    limpiar_ejes(ax, ("top", "right", "left"))
    ax.tick_params(axis="y", length=0)

    tope = max(valores) if len(valores) else 0
    for barra, valor in zip(barras, valores):
        ax.annotate(
            formato.format(valor),
            (barra.get_width(), barra.get_y() + barra.get_height() / 2),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=TINTA_SECUNDARIA,
        )
    ax.set_xlim(0, tope * 1.15 if tope else 1)


def titulo(ax, texto: str, subtitulo: Optional[str] = None) -> None:
    """Titulo a la izquierda, con subtitulo opcional en tinta tenue.

    El subtitulo se ancla al borde superior de los ejes y el titulo se
    desplaza hacia arriba para dejarle lugar; sin ese desplazamiento los dos
    textos se enciman.
    """
    ax.set_title(texto, color=TINTA_PRIMARIA, pad=28 if subtitulo else 12)
    if subtitulo:
        ax.annotate(
            subtitulo,
            xy=(0, 1),
            xycoords="axes fraction",
            xytext=(0, 7),
            textcoords="offset points",
            fontsize=9,
            color=TINTA_TENUE,
            va="bottom",
        )


def indice_h(citas: Sequence[int]) -> int:
    """Indice h de un conjunto de publicaciones.

    El mayor h tal que h publicaciones tienen al menos h citas cada una.
    """
    ordenadas = sorted((int(c) for c in citas if c is not None), reverse=True)
    h = 0
    for posicion, c in enumerate(ordenadas, start=1):
        if c >= posicion:
            h = posicion
        else:
            break
    return h
