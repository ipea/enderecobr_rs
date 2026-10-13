import collections
from pathlib import Path
from typing import Annotated

import sklearn_crfsuite
import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def main(
    tagger: Annotated[Path, typer.Argument(help="Path do tagger treinado")] = Path(
        "./tagger.crf"
    ),
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Path do resultado")
    ] = None,
):
    crf = sklearn_crfsuite.CRF(model_filename=str(tagger))
    features = collections.Counter(crf.state_features_).most_common()

    if output is None:
        for (attr, label), weight in features:
            print("%0.6f %-8s %s" % (weight, label, attr))
    else:
        with open(output, "w") as f:
            for (attr, label), weight in features:
                f.write("%0.6f %-8s %s\n" % (weight, label, attr))


if __name__ == "__main__":
    app()
