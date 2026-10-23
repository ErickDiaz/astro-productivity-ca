# astro-productivity-ca

Estudio bibliométrico de la producción científica en **astronomía en Centroamérica**, a partir de
[NASA ADS](https://ui.adsabs.harvard.edu/).

Replica, para astronomía y para la región, el análisis de Morales-Alvarado, Quevedo et al. (2025),
*Statistical Analysis of Scientific Metrics in High Energy, Cosmology, and Astroparticle Physics in
Latin America* ([arXiv:2503.05658](https://arxiv.org/abs/2503.05658)), que cubre 70 años de física
en 18 países usando INSPIRE-HEP.

El plan completo —qué se replica, qué no es replicable con ADS y por qué— está en
[`docs/PLAN.md`](docs/PLAN.md).

---

## Instalación

Requisitos: **Python 3.9+** y [Poetry](https://python-poetry.org/docs/#installation).

```bash
git clone https://github.com/ErickDiaz/astro-productivity-ca.git
cd astro-productivity-ca

make install        # instala dependencias en un entorno virtual de poetry
make env            # crea .env a partir de .env.example
```

### Token de NASA ADS

La API de ADS necesita un token personal, gratuito:

1. Entra a <https://ui.adsabs.harvard.edu/user/settings/token> (requiere cuenta de ADS).
2. Genera el token y cópialo.
3. Pégalo en el archivo `.env`, en la línea `ADS_DEV_KEY=`:

```dotenv
ADS_DEV_KEY=tu_token_aqui
```

`.env` está en `.gitignore` y nunca se versiona. Lo que sí se versiona es `.env.example`, que
documenta las variables disponibles.

Verifica que quedó bien:

```bash
poetry run astroca config show
```

Debe mostrar `Token de ADS: configurado` y la query exacta que se va a ejecutar.

---

## Uso

El pipeline son dos pasos, en orden:

```bash
make extract        # 1. descarga de NASA ADS        -> data/raw/
make transform      # 2. resuelve afiliación -> país -> data/processed/
make all            # ambos
```

Ambos comandos imprimen el avance en pantalla y guardan el detalle completo en `logs/`.

### Antes de descargar: cuántos resultados hay

```bash
poetry run astroca extract publications --dry-run
```

Cuenta los resultados por país sin descargarlos. Útil para dimensionar la corrida antes de gastar
cuota de la API.

### Otras opciones

```bash
poetry run astroca extract publications --verbose     # muestra las queries completas
poetry run astroca extract publications --no-cache    # ignora la caché y vuelve a pedir todo
poetry run astroca transform affiliations --verbose
make notebooks                                        # levanta JupyterLab
make test                                             # corre los tests
make lint                                             # revisa estilo
make clean-cache                                      # borra la caché de la API
```

---

## Configuración

Todo lo que define *qué* se estudia vive en `config/`, en YAML. No hay que tocar código para
ampliar el estudio.

### `config/search.yml` — el universo de búsqueda

Parte de `database:astronomy`, es decir, toda la literatura que ADS clasifica como astronomía:

```yaml
field:
  database: astronomy
  refereed_only: true
  keywords: []          # vacío = todo el campo
```

Para acotar el campo a un tema específico (como hace Sierra-Flores et al. 2009 con los objetos
Herbig-Haro), se agregan keywords:

```yaml
field:
  keywords:
    - "herbig-haro"
    - "molecular outflows"
    - "t tauri"
  keyword_logic: OR     # OR = unión, AND = intersección
  keyword_fields:
    - abs               # abs busca en título + resumen + keywords
```

También se configuran ahí el período (`period`), el corte anti hiper-autoría
(`authors.max_authors`, en 10 como el paper original) y los campos que se le piden a la API.

> Cambiar los campos pedidos invalida la caché automáticamente: la huella de la query los incluye.

### `config/countries.yml` — países y pistas de afiliación

Los 20 países del estudio (7 de Centroamérica, 13 del Caribe) con las variantes de nombre,
gentilicios, ciudades y dominio de correo que sirven para reconocerlos en una afiliación.

`scope` controla cuáles se extraen:

```yaml
scope: centroamerica    # centroamerica | caribe | all
```

### `config/foreign.yml` — marcadores de fuera de la región

Nombres de países e instituciones de fuera de la región (Oxford, JPL, CNRS, USA…). **No** se usan
para asignar país: sirven para que el reporte de calidad distinga un coautor internacional —que es
lo normal y justamente lo que el estudio mide— de una afiliación que no se pudo clasificar.

Sin esa separación la cobertura se ve artificialmente baja: en la primera corrida real daba 33,6%,
cuando en realidad el 100% de las publicaciones estaban bien resueltas y lo "no resuelto" eran
coautores de Harvard, Princeton y el JPL.

### `config/institutions.yml` — instituciones semilla

Instituciones conocidas por país. Sirven para dos cosas: ampliar la búsqueda en ADS (muchas
afiliaciones no nombran al país) y resolver el país a partir del nombre de la institución.

**Esta lista crece con el uso.** Al terminar, `make transform` imprime las afiliaciones que no
pudo clasificar, ordenadas por frecuencia: esas son las candidatas a agregar aquí (si son de la
región) o a `config/foreign.yml` (si son extranjeras).

---

## Estructura

```
astro-productivity-ca/
├── config/                  qué se estudia (YAML, versionado)
│   ├── search.yml           campo, período, keywords, filtros
│   ├── countries.yml        países y pistas de afiliación
│   ├── institutions.yml     instituciones semilla por país
│   └── foreign.yml          marcadores de fuera de la región
├── src/astroca/
│   ├── config.py            carga y valida la configuración
│   ├── storage.py           lectura/escritura de las tres capas de datos
│   ├── ads/
│   │   ├── client.py        cliente HTTP: paginación, rate limits, caché, reintentos
│   │   └── queries.py       construcción de queries de ADS
│   ├── extract/             de la API a data/raw
│   ├── transform/           de data/raw a data/processed
│   └── cli.py               ensamblaje de los comandos
├── notebooks/               análisis (ver docs/PLAN.md)
├── tests/
├── data/                    generado, no versionado
├── logs/                    generado, no versionado
└── drive/                   material fuente, no versionado
```

### Las tres capas de datos

```
data/raw/          respuestas de ADS tal como llegaron, fechadas e inmutables
data/interim/      resultados intermedios
data/processed/    tablas analíticas — lo único que leen los notebooks
```

Los archivos llevan la fecha de extracción en el nombre:

```
data/raw/publications_20261023.csv
data/processed/author_affiliations_20261023.csv
```

Así una extracción nueva no pisa la anterior y cualquier análisis se puede repetir exactamente
como se corrió.

> **Formato CSV.** Se eligió CSV para poder abrir los archivos en Excel o Google Sheets sin
> herramientas extra. ADS devuelve listas (autores, afiliaciones) y una lista escrita tal cual en
> un CSV no se puede volver a leer de forma fiable, así que esas columnas se guardan como JSON y se
> reconstruyen al leer. Para que el ida y vuelta funcione, usa `DataStore.read_csv()` en vez de
> `pd.read_csv()` directo:
>
> ```python
> from astroca.config import get_loader
> from astroca.storage import DataStore
>
> store = DataStore(get_loader().settings().data_dir)
> df = store.read_latest_processed("author_affiliations")
> ```

### Regla de reproducibilidad

**Los notebooks nunca llaman a la API.** Solo leen `data/processed/`. La extracción es un paso
aparte, fechado y cacheado. Esto hace que los resultados se puedan reproducir sin credenciales y
que iterar sobre el análisis no gaste cuota de ADS.

---

## Cómo funciona la resolución afiliación → país

Es la pieza crítica: si una afiliación se asigna al país equivocado, todas las métricas heredan el
error. Se aplica una cascada de estrategias, de mayor a menor confianza, y **se registra cuál
resolvió cada fila** para poder auditarlo después.

| Orden | Estrategia | Confianza | Qué usa |
|---|---|---|---|
| 1 | `aff_id` | 0.99 | Identificadores curados de ADS |
| 2 | `institution` | 0.95 | Instituciones de `config/institutions.yml` |
| 3 | `country_name` | 0.90 | Nombre del país o gentilicio |
| 4 | `city` | 0.70 | Ciudades conocidas |
| 5 | `email_tld` | 0.60 | Dominio de correo (`.gt`, `.hn`, `.cr`…) |

Lo que ninguna resuelve queda con `iso3 = None`.

### Cómo leer el reporte de calidad

Al final de `make transform` se imprime algo así:

```
publicaciones:                 273
con >=1 autor de la region:    273/273 (100.0%)
filas autor-afiliacion:        1233
  afiliaciones de la region:    412
  coautores en el extranjero:   746
  SIN CLASIFICAR (revisar):      68
por estrategia: {'institution': 241, 'country_name': 170, 'city': 1}
```

La métrica que valida el estudio es **`con >=1 autor de la región`**: toda publicación traída por
la búsqueda debe tener al menos un autor de la región. Si baja de 100%, la query está trayendo
cosas que no corresponden.

**`SIN CLASIFICAR` es la lista de trabajo**, no un error: son afiliaciones que no se reconocieron
ni como regionales ni como extranjeras. Se revisan en el log y se reparten entre
`config/institutions.yml` y `config/foreign.yml`.

El porcentaje de afiliaciones resueltas al total **no** es una medida útil: la mayoría de las
afiliaciones de una publicación son de coautores internacionales y nunca van a resolverse a un
país del estudio.

### Agregar una estrategia nueva

Hereda de `ResolutionStrategy`, define `name`, `confidence` y `resolve()`, y agrégala en
`AffiliationResolver.from_config()`. La cascada se ordena sola por confianza.

---

## Logs

Cada corrida escribe un archivo en `logs/astroca_<fecha>_<hora>.log` con el detalle completo en
nivel DEBUG —incluidas las queries exactas enviadas a ADS—, mientras la pantalla muestra solo el
avance. Si algo sale raro en una extracción, ese archivo dice exactamente qué se pidió y qué llegó.

---

## Fuentes de datos

| Dato | Fuente |
|---|---|
| Publicaciones, citas, índice h | [NASA ADS API](https://ui.adsabs.harvard.edu/help/api/) |
| Población | [UN Data](http://data.un.org) |
| I+D como % del PIB | [Banco Mundial](https://datos.bancomundial.org/indicador/GB.XPD.RSDV.GD.ZS) |
| IDH | PNUD |
| Género | [genderize.io](https://genderize.io) |
