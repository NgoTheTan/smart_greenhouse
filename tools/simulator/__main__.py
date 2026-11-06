"""CLI simulator (spec 11): chạy gateway giả lập qua MQTT TLS sử dụng credential đã cấp phát."""

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
REPO_ROOT = Path(__file__).resolve().parents[2]
DEV_GW_FILE = REPO_ROOT / ".dev-gateway.json"
DEFAULT_CA = REPO_ROOT / "deploy" / "certs" / "ca.crt"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="tools.simulator", description="GreenHub device simulator")
    p.add_argument("--api", default="https://localhost/api", help="Base URL API")
    p.add_argument("--email", default="owner@greenhub.vn", help="Email owner dùng đăng ký")
    p.add_argument("--password", default="greenhub123", help="Mật khẩu owner")
    p.add_argument("--farms", type=int, default=1)
    p.add_argument("--gateways", type=int, default=1, help="số gateway mỗi farm")
    p.add_argument("--nodes-per-gw", type=int, default=2)
    p.add_argument("--interval", type=float, default=10.0, help="chu kỳ gửi (giây)")
    p.add_argument("--scenario", choices=SCENARIOS, default="normal")
    p.add_argument("--insecure", action="store_true", help="bỏ kiểm tra chứng chỉ (dev tự ký)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="chỉ kiểm tra tham số CLI mà không mở kết nối mạng",
    )
    return p.parse_args(argv)


async def _provision_or_load_gateways(args: argparse.Namespace) -> list[dict]:
    """Dùng credential `.dev-gateway.json` nếu có sẵn 1 gateway, hoặc đăng ký mới qua API."""
    if args.farms == 1 and args.gateways == 1 and DEV_GW_FILE.exists():
        return [json.loads(DEV_GW_FILE.read_text(encoding="utf-8"))]

    verify_ssl = not args.insecure
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
                json={"name": f"Nhà kính Sim #{idx}", "location": "Simulator"},
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


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    args = parse_args(argv)
    if args.dry_run:
        print(f"[simulator] dry-run ok: {vars(args)}")
        return
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(_run_all(args), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
