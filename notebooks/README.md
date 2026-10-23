# Notebooks de análisis

Los notebooks **no llaman a la API**: leen `data/processed/`, que produce `make transform`. Para
regenerarlos con datos nuevos:

```bash
make all        # extract + transform
make notebooks  # JupyterLab
```

Todos quedan ejecutados en el repo, con sus resultados y figuras guardados. El estilo de las
figuras vive en `src/astroca/viz.py`, no en cada notebook.

## Estado

| Notebook | Sección del paper ancla | Estado |
|---|---|---|
| `01_cobertura_y_afiliaciones` | Metodología (sec. 2) | ✅ ejecutado |
| `02_produccion_regional` | Producción colectiva (sec. 4) | ✅ ejecutado |
| `03_paises` | Publicaciones (sec. 6) | ⚠️ ejecutado, sin per cápita |
| `04_citas_e_impacto` | Citas e índice h (sec. 7) | ✅ ejecutado |
| `07_colaboracion` | Colaboración (sec. 10) | ✅ ejecutado |
| `05_correlaciones_idh_id` | Correlaciones con I+D e IDH (sec. 8) | ⛔ bloqueado |
| `06_genero` | Brecha de género (sec. 9) | ⛔ bloqueado |

### Qué falta y por qué

**`03` sin normalización per cápita.** Las publicaciones por millón de habitantes (PMI) necesitan
los datos de población de UN Data. Falta implementar `extract/indicators.py`.

**`05` correlaciones con I+D e IDH.** Mismo bloqueo: hacen falta los indicadores del Banco Mundial
(I+D como % del PIB) y del PNUD (IDH). Además, con 7 países la correlación tendría n=7, muy por
debajo de los 18 del paper ancla: conviene reportar el n junto al R².

**`06` análisis de género.** Requiere una llave de [genderize.io](https://genderize.io) y el módulo
`transform/gender.py`. Advertencia de método: con este volumen de autores, la lectura de "efecto
tijera" por rango académico del paper ancla no es sostenible. Debe reportarse como conteo con
intervalos, no como tendencia.

## Hallazgos que condicionan el resto del estudio

1. **El mapeo afiliación → país funciona:** 273/273 publicaciones (100%) tienen al menos un autor
   de la región. Quedan 68 afiliaciones sin clasificar (5,5%) como lista de trabajo.
2. **Falta masa crítica**, como anticipaba el plan: 273 publicaciones en 67 años, mediana de 7 por
   año desde 1990, y 32 años sin ninguna publicación. Belice tiene 1.
3. **El 39% de las publicaciones son de ciencias de la Tierra** (ver `04`). `database:astronomy` de
   ADS incluye geofísica y geoquímica. **Es una decisión de método pendiente**, documentada en
   `docs/PLAN.md`.
4. **La colaboración intrarregional es casi inexistente:** solo 6 publicaciones (2,2%) tienen
   autores de más de un país de la región, mientras que 217 (79%) tienen al menos un coautor
   extranjero.
