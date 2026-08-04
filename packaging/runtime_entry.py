import os

os.environ["PYANNOTE_METRICS_ENABLED"] = "0"

from transcriber.web import main


if __name__ == "__main__":
    raise SystemExit(main())
