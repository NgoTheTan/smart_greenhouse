"""CLI huấn luyện (spec 8.3): python -m ml.train --task <task> --zone <id|all> [--from --to]."""

import argparse

TASKS = ("risk_forecast", "irrigation_eta", "pump_response", "fan_response")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ml.train", description="GreenHub model training")
    p.add_argument("--task", required=True, choices=TASKS)
    p.add_argument("--zone", default="all", help="zone UUID hoặc 'all'")
    p.add_argument("--from", dest="date_from", help="ISO 8601 UTC")
    p.add_argument("--to", dest="date_to", help="ISO 8601 UTC")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    # TODO(M5): tải dữ liệu -> chia theo thời gian -> train -> metrics vs baseline -> lưu model
    print(f"[ml.train] task={args.task} zone={args.zone} (chưa hiện thực - M5)")


if __name__ == "__main__":
    main()

