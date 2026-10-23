"""Interfaz de linea de comandos.

Es la capa de ensamblaje: construye los objetos y los conecta. Toda la logica
vive en ``astroca.extract`` y ``astroca.transform``; aqui solo se cablea.

    astroca extract publications
    astroca transform affiliations
    astroca config show
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from astroca.ads.client import ADSClient, ADSError, ResponseCache
from astroca.ads.queries import QueryBuilder
from astroca.config import PROJECT_ROOT, ConfigLoader, get_loader
from astroca.extract.publications import PublicationExtractor
from astroca.storage import DataStore
from astroca.transform.affiliations import (
    AffiliationResolver,
    AffiliationTransformer,
    ForeignAffiliationDetector,
)

app = typer.Typer(
    help="Bibliometria de astronomia en Centroamerica y el Caribe", no_args_is_help=True
)
extract_app = typer.Typer(
    help="Descarga datos de NASA ADS hacia data/raw", no_args_is_help=True
)
transform_app = typer.Typer(
    help="Construye tablas analiticas en data/processed", no_args_is_help=True
)
config_app = typer.Typer(help="Inspecciona la configuracion activa", no_args_is_help=True)

app.add_typer(extract_app, name="extract")
app.add_typer(transform_app, name="transform")
app.add_typer(config_app, name="config")

console = Console()


def _configurar_logging(verbose: bool = False) -> Path:
    """Configura el log en pantalla y en archivo.

    La pantalla muestra el avance; el archivo guarda la corrida completa en
    DEBUG, con las queries exactas, para poder auditar despues de que se
    descargo cada cosa.
    """
    directorio = PROJECT_ROOT / "logs"
    directorio.mkdir(parents=True, exist_ok=True)
    archivo = directorio / f"astroca_{datetime.now():%Y%m%d_%H%M%S}.log"

    consola_handler = RichHandler(console=console, rich_tracebacks=True, show_path=False)
    consola_handler.setLevel(logging.DEBUG if verbose else logging.INFO)

    archivo_handler = logging.FileHandler(archivo, encoding="utf-8")
    archivo_handler.setLevel(logging.DEBUG)
    archivo_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )

    raiz = logging.getLogger()
    raiz.setLevel(logging.DEBUG)
    raiz.handlers.clear()
    raiz.addHandler(consola_handler)
    raiz.addHandler(archivo_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger(__name__).debug("Log de esta corrida: %s", archivo)
    return archivo


def _construir_cliente(loader: ConfigLoader) -> ADSClient:
    settings = loader.settings()
    return ADSClient(
        token=settings.require_token(),
        cache=ResponseCache(settings.cache_dir),
        request_delay=settings.astroca_request_delay,
    )


def _construir_builder(loader: ConfigLoader) -> QueryBuilder:
    return QueryBuilder(
        config=loader.search(),
        institutions=loader.institutions().institutions,
    )


def _store(loader: ConfigLoader) -> DataStore:
    return DataStore(loader.settings().data_dir)


# --------------------------------------------------------------------------- #
#  extract
# --------------------------------------------------------------------------- #
@extract_app.command("publications")
def extract_publications(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Muestra las queries completas"),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="Ignora la cache y vuelve a pedir todo"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Solo cuenta resultados, no descarga"),
) -> None:
    """Descarga las publicaciones de los paises en scope."""
    log = _configurar_logging(verbose)
    loader = get_loader()
    paises = loader.countries().in_scope()

    if not paises:
        console.print("[red]No hay paises en scope. Revisa `scope` en config/countries.yml[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Scope:[/bold] {loader.countries().scope} ({len(paises)} paises)")

    try:
        cliente = _construir_cliente(loader)
        builder = _construir_builder(loader)

        if dry_run:
            _contar(cliente, builder, paises)
            return

        if no_cache:
            cliente._cache = None  # noqa: SLF001 - opcion explicita del usuario

        ruta = PublicationExtractor(_store(loader), cliente, builder, paises).run()
        console.print(f"[green]✓[/green] {ruta}")
        console.print(f"[dim]{cliente.rate_limit}[/dim]")
        console.print(f"[dim]log completo: {log}[/dim]")
    except (ADSError, RuntimeError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1) from exc


def _contar(cliente: ADSClient, builder: QueryBuilder, paises) -> None:
    """Cuenta resultados por pais sin descargarlos."""
    tabla = Table(title="Resultados en ADS (sin descargar)")
    tabla.add_column("Pais")
    tabla.add_column("ISO3")
    tabla.add_column("Publicaciones", justify="right")

    total = 0
    for pais in paises:
        n = cliente.count(builder.for_country(pais))
        total += n
        tabla.add_row(pais.name, pais.iso3, f"{n:,}")

    tabla.add_section()
    tabla.add_row("[bold]Total (con duplicados)", "", f"[bold]{total:,}")
    console.print(tabla)
    console.print(f"[dim]{cliente.rate_limit}[/dim]")


# --------------------------------------------------------------------------- #
#  transform
# --------------------------------------------------------------------------- #
@transform_app.command("affiliations")
def transform_affiliations(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Resuelve afiliacion -> pais y escribe la tabla autor x afiliacion."""
    log = _configurar_logging(verbose)
    loader = get_loader()

    resolver = AffiliationResolver.from_config(
        countries=loader.countries().in_scope(),
        institutions=loader.institutions().flatten(),
    )

    detector = ForeignAffiliationDetector(loader.foreign().foreign_markers)

    try:
        ruta = AffiliationTransformer(_store(loader), resolver, detector).run()
        console.print(f"[green]✓[/green] {ruta}")
        console.print(f"[dim]log completo: {log}[/dim]")
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1) from exc


# --------------------------------------------------------------------------- #
#  config
# --------------------------------------------------------------------------- #
@config_app.command("show")
def config_show() -> None:
    """Muestra la configuracion activa y la query que se va a ejecutar."""
    loader = get_loader()
    search = loader.search()
    countries = loader.countries()
    settings = loader.settings()

    tabla = Table(title="Configuracion activa", show_header=False)
    tabla.add_column(style="bold")
    tabla.add_column()
    tabla.add_row("Campo", f"database:{search.field.database}")
    tabla.add_row("Solo con referato", "si" if search.field.refereed_only else "no")
    tabla.add_row("Keywords", ", ".join(search.field.keywords) or "[dim](todo el campo)[/dim]")
    tabla.add_row("Periodo", f"{search.period.start_year}-{search.period.end_year}")
    tabla.add_row("Maximo de autores", str(search.authors.max_authors or "sin limite"))
    tabla.add_row("Scope", f"{countries.scope} ({len(countries.in_scope())} paises)")
    tabla.add_row("Paises", ", ".join(c.iso3 for c in countries.in_scope()))
    tabla.add_row("Datos", str(settings.data_dir))
    tabla.add_row(
        "Token de ADS",
        "[green]configurado[/green]" if settings.ads_dev_key else "[red]falta[/red]",
    )
    console.print(tabla)

    paises = countries.in_scope()
    if paises:
        builder = _construir_builder(loader)
        console.print("\n[bold]Query de ejemplo[/bold] ({}):".format(paises[0].name))
        console.print(f"[dim]{builder.for_country(paises[0]).q}[/dim]")


if __name__ == "__main__":
    app()
