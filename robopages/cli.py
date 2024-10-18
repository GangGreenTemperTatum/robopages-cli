import pathlib
import typing as t
import os

import typer
from rich import box, print
from rich.prompt import Prompt
from rich.table import Table

from robopages.defaults import (
    DEFAULT_ADDRESS,
    DEFAULT_PAGE_FILE_NAME,
    DEFAULT_PATH,
    DEFAULT_PORT,
    DEFAULT_REPO,
)
from robopages.models import FunctionCall, Robocall, Robook, Robopage
import robopages.api as api

cli = typer.Typer(no_args_is_help=True, help="Man pages but for robots!")


@cli.command(help="Install pages from a given repository.")
def install(
    repo: t.Annotated[
        str,
        typer.Argument(
            help="Repository user/name, URL or ZIP archive path.",
        ),
    ] = DEFAULT_REPO,
    path: t.Annotated[
        pathlib.Path,
        typer.Option(
            "--path",
            "-p",
            help="Destination path.",
            file_okay=False,
            resolve_path=True,
        ),
    ] = DEFAULT_PATH,
) -> None:
    try:
        if path.exists():
            print(f":cross_mark: path {path} already exists.")
            return

        import zipfile

        if ".zip" in repo and os.path.exists(repo):
            print(f":coffee: extracting to {path} ...")
            with zipfile.ZipFile(repo, "r") as zip_ref:
                zip_ref.extractall(path)
        else:
            # allow for github shorthand
            if "://" not in repo:
                repo = f"https://github.com/{repo}"

            archive_url = f"{repo}/archive/refs/heads/main.zip"

            import httpx
            import tempfile

            with tempfile.NamedTemporaryFile(delete=True) as tmp_file:
                print(f":coffee: downloading {archive_url} ...")
                with httpx.stream("GET", archive_url) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        tmp_file.write(chunk)

                print(f":coffee: extracting to {path} ...")
                with zipfile.ZipFile(tmp_file.name, "r") as zip_ref:
                    zip_ref.extractall(path)

    except Exception as e:
        print(f":cross_mark: {e}")


@cli.command(help="Create a new robopage file.")
def create(
    path: t.Annotated[
        pathlib.Path,
        typer.Argument(
            help="File name.",
            file_okay=True,
            resolve_path=True,
        ),
    ] = DEFAULT_PAGE_FILE_NAME,
) -> None:
    if path.exists():
        if (
            Prompt.ask(f":axe: overwrite {path.name}?", choices=["y", "n"], default="n")
            == "n"
        ):
            return

    Robopage.create_example_in_path(path)


@cli.command(help="View robopages.")
def view(
    path: t.Annotated[
        pathlib.Path,
        typer.Argument(
            help="Base path to search for robopages.",
            file_okay=True,
            resolve_path=True,
        ),
    ] = DEFAULT_PATH,
    filter: t.Annotated[
        str | None,
        typer.Option(
            "--filter",
            "-f",
            help="Filter results by this string.",
        ),
    ] = None,
) -> None:
    book = Robook.from_path(path, filter)

    print()

    table = Table(box=box.ROUNDED)
    table.add_column("page")
    table.add_column("function")
    table.add_column("description")

    for page in book.pages.values():
        first_page = True
        for function_name, function in page.functions.items():
            if first_page:
                first_page = False
                table.add_row(
                    f'[dim]{" > ".join(page.categories)}[/] > {page.name}',
                    function.to_string(function_name),
                    function.description,
                )
            else:
                table.add_row(
                    "", function.to_string(function_name), function.description
                )

    print(table)


@cli.command(
    help="Print an OpenAI / OLLAMA compatible JSON schema for tool calling from the robopages."
)
def to_json(
    path: t.Annotated[
        pathlib.Path,
        typer.Option(
            "--path",
            "-p",
            help="Robopage or directory containing multiple robopages.",
            file_okay=True,
            resolve_path=True,
        ),
    ] = DEFAULT_PATH,
    output: t.Annotated[
        pathlib.Path,
        typer.Option(
            "--output",
            "-o",
            help="Output file.",
            file_okay=True,
            resolve_path=True,
        ),
    ]
    | None = None,
    filter: t.Annotated[
        str | None,
        typer.Option(
            "--filter",
            "-f",
            help="Filter results by this string.",
        ),
    ] = None,
) -> None:
    import json

    data = json.dumps(Robook.from_path(path, filter).to_openai(), indent=2)
    if output:
        output.write_text(data)
        print(f":file_folder: saved to {output}")
    else:
        print(data)


@cli.command(help="Serve the robopages as a local API.")
def serve(
    path: t.Annotated[
        pathlib.Path,
        typer.Option(
            "--path",
            "-p",
            help="Robopage or directory containing multiple robopages.",
            file_okay=True,
            resolve_path=True,
        ),
    ] = DEFAULT_PATH,
    filter: t.Annotated[
        str,
        typer.Option(
            "--filter",
            "-f",
            help="Filter by this string.",
        ),
    ]
    | None = None,
    address: t.Annotated[
        str,
        typer.Option(
            "--address",
            "-a",
            help="Address to bind to.",
        ),
    ] = DEFAULT_ADDRESS,
    port: t.Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
            help="Port to bind to.",
        ),
    ] = DEFAULT_PORT,
) -> None:
    import uvicorn

    api.book = Robook.from_path(path, filter)

    if address not in ("127.0.0.1", "localhost"):
        print(
            "[bold red]:warning: external address specified, this is an unsafe configuration as no authentication is provided.[/]"
        )

    uvicorn.run(api.app, host=address, port=port)


@cli.command(help="Execute a function from the robopages.")
def run(
    path: t.Annotated[
        pathlib.Path,
        typer.Option(
            "--path",
            "-p",
            help="Robopage or directory containing multiple robopages.",
            file_okay=True,
            resolve_path=True,
        ),
    ] = DEFAULT_PATH,
    auto: t.Annotated[
        bool,
        typer.Option(
            "--auto",
            help="Execute the function without user interaction.",
        ),
    ] = False,
    function_name: str = typer.Argument(
        help="Name of the function to execute.",
    ),
) -> None:
    try:
        book = Robook.from_path(path)
        function = book.find_function(function_name)
        if not function:
            raise Exception(f"function {function_name} not found")

        arguments = {}

        if function.parameters:
            print()

        for param_name, parameter in function.parameters.items():
            while True:
                value = Prompt.ask(f"Enter value for [yellow]${{{param_name}}}[/]")
                if value:
                    arguments[param_name] = value
                    break
                elif not parameter.required:
                    break

        call = Robocall(function=FunctionCall(name=function_name, arguments=arguments))
        print(book.process([call], interactive=not auto))
    except Exception as e:
        print(f":cross_mark: {e}")
