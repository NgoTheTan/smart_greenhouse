"""Unit tests cho bảo mật, crop templates, schemas, ACL Dynamic Security và ngân sách bộ nhớ API."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.provisioning import build_gateway_dynsec_commands
from core.crop_templates import SYSTEM_CROP_TEMPLATES, CropParameters
from core.schemas import CommandCreateRequest, normalize_mac
from core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from worker.commands import _parse_side_effect
from worker.main import parse_gh_topic


def test_password_hash_and_jwt_roundtrip() -> None:
    uid = uuid.uuid4()
    fid = uuid.uuid4()
    pw_hash = hash_password("secret-123")
    assert verify_password("secret-123", pw_hash)
    assert not verify_password("wrong", pw_hash)

    token = create_access_token(uid, fid, "owner")
    claims = decode_access_token(token)
    assert claims["sub"] == str(uid)
    assert claims["farm_id"] == str(fid)
    assert claims["role"] == "owner"


def test_system_crop_templates_valid() -> None:
    assert len(SYSTEM_CROP_TEMPLATES) == 10
    varieties = {(t["crop_code"], t["variety"]) for t in SYSTEM_CROP_TEMPLATES}
    assert varieties == {
        ("tomato_cherry", "real"),
        ("tomato_cherry", "demo"),
        ("strawberry", "real"),
        ("strawberry", "demo"),
        ("lettuce", "real"),
        ("lettuce", "demo"),
        ("cucumber", "real"),
        ("cucumber", "demo"),
        ("bell_pepper", "real"),
        ("bell_pepper", "demo"),
    }
    for tpl in SYSTEM_CROP_TEMPLATES:
        parsed = CropParameters.model_validate(tpl["parameters_json"])
        assert parsed.schema_version == 2
        assert len(parsed.light.dli_optimal) == 2
        assert parsed.cycle.days > 0
        assert parsed.yield_info.reference_kg_m2 > 0
        assert parsed.ai.inference_interval_s > 0


def test_mac_normalization_and_command_validation() -> None:
    assert normalize_mac("aa-bb-cc-dd-ee-01") == "AA:BB:CC:DD:EE:01"
    with pytest.raises(ValueError):
        normalize_mac("invalid-mac")

    with pytest.raises(ValidationError):
        CommandCreateRequest(actuator="fan", action="on", duration_s=None)

    ok_off = CommandCreateRequest(actuator="fan", action="off")
    assert ok_off.duration_s is None


def test_dynsec_acl_topic_isolation_and_topic_parser() -> None:
    farm_id = uuid.uuid4()
    gh_id = uuid.uuid4()
    cmds = build_gateway_dynsec_commands(farm_id, gh_id, "gw_test", "pw123")
    create_role = next(c for c in cmds if c["command"] == "createRole")
    prefix = f"gh/{farm_id}/{gh_id}/"
    for acl in create_role["acls"]:
        assert acl["topic"].startswith(prefix)

    parsed = parse_gh_topic(f"gh/{farm_id}/{gh_id}/telemetry/2")
    assert parsed == (farm_id, gh_id, ["telemetry", "2"])
    assert parse_gh_topic("other/topic") is None
    assert _parse_side_effect("mist_off") == ("mist", "off")
    assert _parse_side_effect("pump_1_off") == ("pump_1", "off")


def test_api_process_does_not_import_heavy_ml_libraries() -> None:
    """Bảo vệ RAM trên VPS 2 GB: tiến trình `api` không nạp LightGBM/sklearn/pandas/joblib."""
    repo_root = Path(__file__).resolve().parents[2]
    platform_dir = repo_root / "platform"
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{platform_dir}{os.pathsep}{repo_root}"
    code = (
        "import sys, api.main\n"
        "heavy = ('lightgbm', 'sklearn', 'pandas', 'joblib')\n"
        "loaded = [p for p in heavy if p in sys.modules]\n"
        "assert not loaded, f'api.main imported heavy ML packages: {loaded}'\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Subprocess failed: {res.stderr or res.stdout}"
