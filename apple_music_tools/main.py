import typer

from apple_music_tools import proxy

app = typer.Typer(
    help=(
        "A collection of tools for reverse engineering and defeating the DRM of Apple Music. For"
        " educational use only."
    )
)
app.add_typer(proxy.app, name="proxy")
