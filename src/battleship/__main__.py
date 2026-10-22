from app.cli import main


def cli() -> int:
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
