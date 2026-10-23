# Plan de implementación — Productividad en astronomía en Centroamérica y el Caribe

## 1. Qué se está replicando

**Paper ancla:** Morales-Alvarado, Quevedo, Ramos-Hamud y Restrepo (2025), *Statistical Analysis
of Scientific Metrics in High Energy, Cosmology, and Astroparticle Physics in Latin America*
([arXiv:2503.05658](https://arxiv.org/abs/2503.05658)). Analiza 70 años (1946–2023) de producción
en 18 países latinoamericanos usando INSPIRE-HEP, con 8 preguntas guía: producción regional vs.
mundial, investigadores activos, comparación entre países de distinto tamaño, citas e índice h,
correlación con I+D e IDH, brecha de género y redes de colaboración.

**Nuestra adaptación:** mismas preguntas, pero en **astronomía/astrofísica**, con **NASA ADS**
como fuente, y sobre **Centroamérica (7 países) + Caribe (13)** según la hoja
`Institutos de Estadística` de `Bases de datos.xlsx`.

**Metodología complementaria:** Sierra-Flores et al. (2009), *The productivity of Mexican
astronomers in the field of outflows from young stars* (Scientometrics 81(3)). Es el referente de
cómo hacer bibliometría **sobre ADS específicamente**: construcción de queries por keywords,
comparación ADS vs. ISI (~10% de diferencia), índice h por autor, grado de especialización
(producción en el campo / producción total del autor), tamaño de los grupos de coautoría e
impacto por revista.

**Contexto regional:** Pineda de Carías (1998, IAU Highlights of Astronomy 11B) y
*The Status of Astronomy in Central America and the Caribbean* (Springer Nature Communities).
Sirven para la discusión, no para los datos.

## 2. La brecha crítica: INSPIRE-HEP no es ADS

Esto define qué es replicable y qué no. Hay que decidirlo antes de escribir código.

| Métrica del paper | INSPIRE-HEP | NASA ADS | Veredicto |
|---|---|---|---|
| Publicaciones, citas, índice h | Nativo | Search API + Metrics API | Replicable |
| País por afiliación | ~11k instituciones curadas | `aff` (texto libre), `aff_id` (curado, con país), `inst` | Replicable, **es el trabajo duro** |
| Autores activos (≥1 publicación en 5 años) | Perfiles desambiguados | Desambiguación parcial + ORCID | Replicable con normalización de nombres |
| **Rangos académicos** (Senior/Staff/Postdoc/PhD/Máster/Pregrado) | Declarados por el autor en su perfil | **No existe** | **No replicable.** Proxy sugerido: antigüedad = años desde la primera publicación, en cuartiles |
| Género | genderize.io sobre nombres de pila | Igual | Replicable |
| Colaboración entre países | Coautoría por afiliación | Igual | Replicable |
| Filtro de hiper-autoría | Filtro nativo ≤10 autores | Se aplica en post-proceso sobre la lista de autores | Replicable |
| Normalización por población / I+D / IDH | ONU, Banco Mundial | Igual | Replicable, **con huecos en el Caribe** |

## 3. El riesgo de fondo: masa crítica

El propio paper ancla concluye que *"los países pequeños (Centroamérica, Bolivia) no alcanzan masa
crítica de investigadores"*. Es muy probable que el universo sea de cientos de publicaciones y
decenas de autores, no miles. Consecuencias de diseño, no detalles:

- Las normalizaciones per cápita (PMI) son inestables con N pequeño: un solo autor mueve el
  indicador de un país entero. Hay que reportar conteos absolutos **junto a** los normalizados.
- El análisis de género con decenas de autores no soporta la lectura de "efecto tijera" del paper.
  Se reporta como conteo con intervalos, no como tendencia.
- Agregación por **década**, no por año, para las series de tiempo.
- Conviene un **grupo de comparación** (México, Chile, Brasil, o la LatAm del paper) para que los
  números de la región tengan escala de referencia.

Esto no invalida el estudio — un resultado de "la región produce X publicaciones en 70 años y
estas son las instituciones y colaboraciones que las sostienen" es en sí el hallazgo. Pero hay que
encuadrarlo así desde el inicio.

## 4. Arquitectura

Convención de los otros repos de Erick: Poetry + `Makefile` + `src/`.

```
astro-productivity-ca/
├── pyproject.toml              # poetry
├── Makefile                    # install, shell, extract, transform, lint
├── .env.example                # ADS_DEV_KEY=
├── config/
│   ├── countries.yml           # 20 países: ISO3, región, variantes de nombre, gentilicios, TLD
│   ├── institutions.yml        # instituciones semilla (USAC, UNAH/OAUNAH, UCR, UNA, UTP, UES…)
│   └── query.yml               # ventana temporal, filtros, umbral de autores
├── src/astroca/
│   ├── config.py               # settings con pydantic
│   ├── ads/
│   │   ├── client.py           # auth, rate limit, reintentos, cursorMark, caché en disco
│   │   ├── queries.py          # construcción de queries por país e institución
│   │   └── metrics.py          # Metrics API: citas, índice h
│   ├── extract/
│   │   ├── publications.py     # → data/raw/publications_<fecha>.parquet
│   │   ├── authors.py          # → data/raw/authors_<AAAAMMDD>.csv
│   │   └── indicators.py       # población, I+D %PIB, IDH
│   ├── transform/
│   │   ├── affiliations.py     # afiliación → país  (núcleo del módulo)
│   │   ├── authors.py          # normalización y desambiguación de nombres
│   │   ├── gender.py           # genderize.io con caché local
│   │   └── collaboration.py    # matriz país × país
│   ├── metrics/
│   │   ├── productivity.py     # conteos, PMI, por autor
│   │   ├── impact.py           # citas, índice h, especialización (Sierra-Flores)
│   │   └── correlations.py     # R² contra I+D e IDH
│   └── cli.py                  # typer: astroca extract | transform | build
├── notebooks/
├── data/                       # gitignored
│   ├── raw/                    # inmutable, con fecha de extracción
│   ├── interim/
│   └── processed/              # tablas analíticas que consumen los notebooks
├── outputs/                    # gitignored: figures/, tables/
└── drive/                      # gitignored: material fuente
```

**Regla de reproducibilidad:** los notebooks **nunca** llaman a la API. Solo leen
`data/processed/`. La extracción es un paso con fecha, cacheado y versionado por separado. Esto
protege contra los rate limits y hace que los resultados sean reproducibles sin credenciales.

**Formato:** CSV con la fecha en el nombre (`publications_20261023.csv`), para poder abrirlos en
Excel o Sheets. Las columnas que ADS devuelve como lista se guardan como JSON y se reconstruyen al
leer con `DataStore.read_csv()`.

## 5. El problema central: afiliación → país

Es donde se va a ir la mayor parte del esfuerzo y donde se decide la credibilidad del estudio.
Cascada propuesta, de mayor a menor confianza:

1. **`aff_id`** — identificadores canónicos de ADS, que traen país asociado. Mejor señal.
2. **`inst`** — para las instituciones semilla de `config/institutions.yml`; devuelve todas las
   variantes que ADS mapeó a la misma institución.
3. **Regex sobre `aff` cruda** — nombres de país, capitales, siglas institucionales y TLD de correo
   (`.gt`, `.hn`, `.cr`, `.pa`, `.ni`, `.sv`, `.bz`, `.cu`, `.do`, `.jm`…).
4. **Revisión manual** de los no resueltos, que con este volumen debería ser viable.

**Trampas conocidas que hay que resolver explícitamente:**

- Ambigüedad geográfica: "San José" (Costa Rica) vs. otras; "Santiago" (Rep. Dominicana vs. Chile).
- Un autor de la región afiliado a una institución de EE.UU. o Europa. **Decisión necesaria:** el
  paper ancla mide por afiliación (dónde se hace la ciencia). La alternativa —seguir al
  investigador por origen— es un estudio distinto y mucho más caro. Recomiendo afiliación, y
  documentar la limitación.
- Afiliaciones múltiples en un mismo autor: se cuenta la publicación una vez por país (conteo
  fraccional opcional como análisis de sensibilidad).

**Validación:** el notebook `01` toma una muestra estratificada etiquetada a mano y reporta
precisión/cobertura del mapeo. Sin ese número, el resto de las cifras no son defendibles.

## 6. Notebooks

| Notebook | Produce | Equivalente en el paper / presentación |
|---|---|---|
| `00_exploracion_ads.ipynb` | Sondeo de queries, volumen esperado | — |
| `01_cobertura_y_afiliaciones.ipynb` | Precisión del mapeo país, cobertura | Sec. 2 (metodología) |
| `02_produccion_regional.ipynb` | Serie temporal, % de producción mundial | Slide 4 / Sec. 4 |
| `03_paises_volumen_vs_percapita.ipynb` | Absolutos vs. PMI por país | Slide 5 / Sec. 6 |
| `04_citas_h_index.ipynb` | Citas, índice h, especialización | Sec. 7 + Sierra-Flores |
| `05_correlaciones_idh_id.ipynb` | R² contra I+D e IDH | Slide 6 / Sec. 8 |
| `06_genero.ipynb` | Fracción de autoras por década | Slide 7 / Sec. 9 |
| `07_colaboracion.ipynb` | Matriz y red de coautoría | Slide 7 / Sec. 10 |
| `08_figuras_finales.ipynb` | Figuras y tablas para el documento | — |

## 7. Fases

| Fase | Entregable | Dependencia |
|---|---|---|
| 0 | Scaffolding: poetry, estructura, Makefile, `.env.example`, configs de países | — |
| 1 | Cliente ADS con caché + extracción cruda + notebook `00` | Token de ADS |
| 2 | **Mapeo afiliación → país + validación** (notebook `01`) | Fase 1 |
| 3 | Indicadores externos (población, I+D, IDH) | — (paralelizable) |
| 4 | Módulo de métricas | Fases 2 y 3 |
| 5 | Notebooks `02`–`07` | Fase 4 |
| 6 | Figuras finales y redacción | Fase 5 |

La fase 2 es la más larga y la de mayor riesgo. Vale la pena hacer la fase 1 con un solo país
(Guatemala) de punta a punta antes de extraer los 20.

## 8. Decisiones pendientes

1. **Alcance:** ¿Centroamérica (7) o Centroamérica + Caribe (20)? Cuba y República Dominicana
   tienen tradición astronómica mayor que el resto y pueden dominar los agregados.
2. **Ventana temporal:** ¿1950–2025 fijo, o desde la primera publicación de cada país?
3. **Definición del campo:** ¿todo lo indexado en `database:astronomy` de ADS, o por keywords al
   estilo Sierra-Flores? Lo primero es más amplio y más fiel al paper ancla.
4. **Filtros:** ¿solo *refereed*? ¿Se aplica el corte de ≤10 autores del paper?
5. **Grupo de comparación:** ¿se incluye México/Chile/Brasil como referencia de escala?

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Masa crítica insuficiente | Agregación por década, conteos absolutos junto a normalizados, grupo de comparación |
| Rate limits de ADS | Caché en disco, extracción por lotes con fecha, nunca desde notebooks |
| genderize.io: cuota gratuita limitada | Caché de nombres ya resueltos; un nombre se consulta una sola vez |
| Sin datos de I+D para varios países del Caribe | Reportar N de la correlación; usar IDH como variable principal (en el paper ancla correlaciona mejor: R² 0.62–0.72 vs. 0.53–0.57) |
| Rangos académicos no replicables | Proxy por antigüedad, documentado como desviación del paper |
| Afiliaciones mal mapeadas | Validación con muestra etiquetada; reportar precisión |

## Fuentes de datos

| Dato | Fuente |
|---|---|
| Publicaciones, citas, índice h | [NASA ADS API](https://ui.adsabs.harvard.edu/help/api/) (token gratuito) |
| Población | [UN Data](http://data.un.org) |
| I+D como % del PIB | [Banco Mundial, GB.XPD.RSDV.GD.ZS](https://datos.bancomundial.org/indicador/GB.XPD.RSDV.GD.ZS) |
| IDH | PNUD |
| Género | [genderize.io](https://genderize.io) |
