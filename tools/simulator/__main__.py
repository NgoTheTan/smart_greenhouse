"""CLI simulator (spec 11): chạy gateway MQTT TLS và sinh dữ liệu `synth-yield`."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from pathlib import Path

import httpx

from tools.simulator.gateway_client import SimulatedGateway

SCENARIOS = ("normal", "humid_spike", "dry_down", "sensor_fault")
REGIONS = ("dalat", "hanoi_winter", "hanoi_summer", "hcm", "mekong", "central_coast")
EQUIPMENT_LEVELS = ("basic", "standard", "full")
REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_GW_FILE = REPO_ROOT / ".dev-gateway.json"
DEFAULT_CA = REPO_ROOT / "deploy" / "certs" / "ca.crt"


def _ensure_platform_on_path() -> None:
    platform_dir = str(REPO_ROOT / "platform")
    if platform_dir not in sys.path:
        sys.path.insert(0, platform_dir)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "synth-yield":
        sp = argparse.ArgumentParser(
            prog="tools.simulator synth-yield",
            description="Sinh dữ liệu huấn luyện tổng hợp cho mô hình dự đoán năng suất",
        )
        sp.add_argument("--greenhouses", type=int, default=200, help="Số nhà kính giả lập")
        sp.add_argument("--cycles-per-gh", type=int, default=5, help="Số vụ mỗi nhà kính")
        sp.add_argument("--seed", type=int, default=42, help="Seed ngẫu nhiên cố định")
        sp.add_argument(
            "--out",
            default="data/synthetic_yield.csv",
            help="Đường dẫn file CSV đầu ra",
        )
        ns = sp.parse_args(args_list[1:])
        ns.command = "synth-yield"
        return ns

    p = argparse.ArgumentParser(prog="tools.simulator", description="GreenHub device simulator")
    p.add_argument("--api", default="https://localhost/api", help="Base URL API")
    p.add_argument("--email", default="owner@greenhub.vn", help="Email owner dùng đăng ký")
    p.add_argument("--password", default="greenhub123", help="Mật khẩu owner")
    p.add_argument("--farms", type=int, default=1)
    p.add_argument("--gateways", type=int, default=1, help="số gateway mỗi farm")
    p.add_argument("--nodes-per-gw", type=int, default=2)
    p.add_argument("--interval", type=float, default=10.0, help="chu kỳ gửi (giây)")
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--region", choices=REGIONS, default=None, help="Vùng khí hậu mô phỏng")
    p.add_argument("--equipment-level", choices=EQUIPMENT_LEVELS, default="standard")
    p.add_argument("--insecure", action="store_true", help="bỏ kiểm tra chứng chỉ (dev tự ký)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="chỉ kiểm tra tham số CLI mà không mở kết nối mạng",
    )
    ns = p.parse_args(args_list)
    ns.command = "simulate"
    return ns


async def _provision_or_load_gateways(args: argparse.Namespace) -> list[dict]:
    """Dùng credential `.dev-gateway.json` nếu có sẵn 1 gateway, hoặc đăng ký mới qua API."""
    if args.farms == 1 and args.gateways == 1 and DEV_GW_FILE.exists():
        return [json.loads(DEV_GW_FILE.read_text(encoding="utf-8"))]

    verify_ssl = not args.insecure
    location = args.region or "Simulator"
    provisioned: list[dict] = []
    async with httpx.AsyncClient(base_url=args.api, verify=verify_ssl, timeout=15.0) as http:
        resp = await http.post(
            "/auth/login", json={"email": args.email, "password": args.password}
        )
        resp.raise_for_status()
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        total = args.farms * args.gateways
        for idx in range(1, total + 1):
            gh_resp = await http.post(
                "/greenhouses",
                headers=headers,
                json={"name": f"Nhà kính Sim #{idx}", "location": location},
            )
            gh_resp.raise_for_status()
            gh = gh_resp.json()

            gw_resp = await http.post(
                "/gateways",
                headers=headers,
                json={"greenhouse_id": gh["id"], "is_simulated": True},
            )
            gw_resp.raise_for_status()
            provisioned.append(gw_resp.json())
    return provisioned


async def _run_all(args: argparse.Namespace) -> None:
    gw_creds = await _provision_or_load_gateways(args)
    tasks = []
    for cred in gw_creds:
        sim = SimulatedGateway(
            farm_id=uuid.UUID(str(cred["farm_id"])),
            greenhouse_id=uuid.UUID(str(cred["greenhouse_id"])),
            mqtt_host=str(cred["host"]),
            mqtt_port=int(cred["port"]),
            mqtt_username=str(cred["mqtt_username"]),
            mqtt_password=str(cred["mqtt_password"]),
            nodes_per_gw=args.nodes_per_gw,
            interval_s=args.interval,
            scenario=args.scenario,
            ca_cert=DEFAULT_CA,
            insecure=args.insecure,
        )
        tasks.append(asyncio.create_task(sim.run()))
    await asyncio.gather(*tasks)


def _run_synth_yield(args: argparse.Namespace) -> None:
    _ensure_platform_on_path()
    from tools.simulator.growth import generate_synthetic_yield_dataset, write_synthetic_yield_csv

    records = generate_synthetic_yield_dataset(
        greenhouses=args.greenhouses,
        cycles_per_gh=args.cycles_per_gh,
        seed=args.seed,
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    saved = write_synthetic_yield_csv(records, out_path)
    print(
        f"[synth-yield] Đã sinh {len(records)} mẫu "
        f"({args.greenhouses} nhà kính x {args.cycles_per_gh} vụ, seed={args.seed}) -> {saved}"
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    args = parse_args(argv)
    if getattr(args, "command", "simulate") == "synth-yield":
        _run_synth_yield(args)
        return
    if args.dry_run:
        print(f"[simulator] dry-run ok: {vars(args)}")
        return
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_run_all(args), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
