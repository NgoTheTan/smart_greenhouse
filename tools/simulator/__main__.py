"""CLI simulator (spec 11): python -m tools.simulator --farms 2 --gateways 5 --interval 10."""

import argparse

SCENARIOS = ("normal", "humid_spike", "dry_down", "sensor_fault")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="tools.simulator", description="GreenHub device simulator")
    p.add_argument("--api", default="https://localhost/api", help="Base URL API")
    p.add_argument("--farms", type=int, default=1)
    p.add_argument("--gateways", type=int, default=1, help="số gateway mỗi farm")
    p.add_argument("--nodes-per-gw", type=int, default=2)
    p.add_argument("--interval", type=int, default=10, help="chu kỳ gửi (giây)")
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--insecure", action="store_true", help="bỏ kiểm tra chứng chỉ (dev tự ký)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    # TODO(M4): provisioning qua API -> MQTT TLS -> telemetry/status, nhận cmd trả ack
    print(f"[simulator] {vars(args)} (chưa hiện thực - M4)")


if __name__ == "__main__":
    main()

