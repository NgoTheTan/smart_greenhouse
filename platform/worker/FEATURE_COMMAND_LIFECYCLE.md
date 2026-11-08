# Feature: Command Service, Vòng đời Lệnh, ACK & Chế độ Manual (`platform/worker/commands.py`)

> Nguồn đặc tả: `docs/greenhub-spec.md` mục 5, 6.3, 6.5, 9, 15; `docs/DECISIONS.md`.

## 1. Mục tiêu & Phạm vi

Đảm bảo mọi lệnh điều khiển actuator (`pump_1`, `pump_2`, `fan`, `mist`) xuất phát từ người dùng (`source='manual'` qua API) hoặc Rule Engine (`source='auto'`) đều được theo dõi trọn vòng đời với kiểm soát hết hạn (`expires_at`), không gửi lại lệnh `on` đã quá hạn, ghi nhận đầy đủ `actuator_logs` (bao gồm cả tác dụng phụ interlock), và tự động hết hạn chế độ `manual` khi tới `until`.

## 2. Trạng thái hiện thực trong repo

- **Đã hoàn thiện (M2):**
  - `platform/api/routers/commands.py`: `POST /greenhouses/{id}/commands`, `GET /greenhouses/{id}/commands`, `PUT /greenhouses/{id}/modes`.
  - `platform/worker/commands.py`:
    - `dispatch_pending_commands`
    - `handle_ack` (bao gồm `_parse_side_effect`)
    - `expire_timed_out_commands`
    - `expire_manual_modes`
  - `platform/worker/scheduler.py`: chạy `expire_timed_out_commands`, `expire_manual_modes`, `dispatch_pending_commands` mỗi 5 s.
  - `platform/worker/main.py`: lắng nghe `worker_events` (`type="command_created"`) để phát lệnh tức thời (< 100 ms) thay vì đợi tick 5 s.
- **Tích hợp M3:**
  - `worker/rules.py` khi phát lệnh `auto` sẽ tạo bản ghi `Command(..., source='auto', status='pending', expires_at=now + 30s)` và gọi `dispatch_pending_commands` (hoặc `pg_notify` / flush trong worker). Lưu ý tôn trọng kiểm tra `gateway.online` và tránh spam lệnh khi đã có lệnh `pending`/`sent` chưa xử lý xong cho cùng actuator!

## 3. Máy trạng thái Lệnh (`commands.status`, MUST)

```
  [API / Rule Engine]
          │
          ▼
     ( pending ) ──[quá expires_at trước khi gửi]──► ( expired )
          │
          ├──[gateway offline]─────────────────────► ( rejected, reason="gateway_offline" )
          │
          ▼  [publish gh/{farm}/{gh}/cmd/{actuator}, QoS 1]
      ( sent ) ────[quá expires_at chưa có ACK]────► ( timeout )
          │
          ├──[nhận ack/{cmd_id} status="applied"]──► ( applied )  + ghi actuator_logs
          ├──[nhận ack/{cmd_id} status="rejected"]─► ( rejected ) + ghi reject_reason
          └──[nhận ack/{cmd_id} status="expired"]──► ( expired )
```

### Quy tắc bất biến:
1. **Không tự gửi lại lệnh `on` quá hạn:** Khi `pending` quá `expires_at` → `expired`; khi `sent` quá `expires_at` → `timeout`. Tuyệt đối không retry lệnh cũ (vì ngữ cảnh môi trường đã đổi; Rule Engine sẽ tự tạo lệnh mới nếu điều kiện vẫn còn).
2. **Gateway offline:**
   - Tại API (`POST /commands`): kiểm tra `gw is None or not gw.online` → từ chối ngay HTTP `409 Conflict` (`detail="gateway_offline"`), không tạo dòng `Command`.
   - Tại Worker (`dispatch_pending_commands`): nếu tới lúc phát lệnh mà gateway vừa offline → đánh dấu `status='rejected'`, `reject_reason='gateway_offline'`, phát WS `command_status`.
3. **Payload lệnh gửi MQTT (`CommandMqttPayload`):**
   - Topic: `gh/{farm_id}/{greenhouse_id}/cmd/{actuator}` (`qos=1`, `retain=False`).
   - JSON: `{"cmd_id":"...","actuator":"fan","action":"on","duration_s":120,"expires_at":"...Z","source":"auto"}`.
   - `expires_at` mặc định `created_at + Settings.command_expire_s` (**30 s**).

## 4. Xử lý ACK & Side Effects (`handle_ack`)

1. Kiểm tra `payload.cmd_id == cmd_id` từ topic và đối chiếu `(cmd_id, greenhouse_id, farm_id)` trong DB.
2. **Idempotency:** Nếu `cmd.status` đã là `'applied'`, `'rejected'` hoặc `'expired'` → bỏ qua (trả `False`), tránh ghi trùng `actuator_logs`.
3. Cập nhật `cmd.status = payload.status`, `cmd.reject_reason = payload.reason`, `cmd.acked_at = payload.applied_at or now`.
4. Cập nhật `DeviceState.reported["actuators"]` theo `payload.state` (nếu có).
5. Nếu `payload.status == "applied"`:
   - Ghi 1 dòng `ActuatorLog(greenhouse_id, actuator=cmd.actuator, action=cmd.action, source=cmd.source, cmd_id=cmd.id, duration_s=cmd.duration_s, reason=cmd.reason)`.
   - Duyệt `payload.side_effects` (ví dụ `["mist_off"]`): giải mã bằng `_parse_side_effect()` (`("mist", "off")`) và ghi thêm dòng `ActuatorLog(..., source=cmd.source, cmd_id=cmd.id, duration_s=None, reason="side_effect:mist_off")`.
   - *(M3 cần lưu ý)*: nếu xảy ra `mist_off` khi quạt tự bật vì rủi ro, Rule Engine đồng thời đặt khóa `mist.lockout_s` (xem `FEATURE_RULE_CONTROL_ENGINE.md`).
6. Gọi `pg_notify(CHANNEL_WS, ...)` phát sự kiện `command_status` kèm `side_effects` và `state`.

## 5. Chế độ `auto` / `manual` & Hết hạn (`expire_manual_modes`)

- Lưu tại `device_state.desired["modes"][actuator] = {"mode": "auto"|"manual", "until": "<ISO8601>|null"}`.
- Khi người dùng gọi `PUT /api/greenhouses/{id}/modes`: cập nhật mode cho actuator đó.
- Mỗi 5 s trong `scheduler.py`, `expire_manual_modes(session)` quét tất cả `DeviceState`: nếu `mode == "manual"` và `until` hợp lệ thỏa `until <= now`, tự động reset thành `{"mode": "auto", "until": None}`.
- Ghi chú quan hệ với Rule Engine: khi actuator ở `manual` còn hiệu lực, Rule Engine không gửi lệnh bình thường cho actuator đó, **NGOẠI TRỪ** ép tắt `mist` khi quạt tự bật vì rủi ro (an toàn thắng thủ công).

## 6. Kiểm tra & Xác nhận

- Unit tests (`platform/tests/test_worker_and_routers_unit.py`):
  - `test_rbac_and_gateway_offline_409`
  - `test_handle_ack_records_side_effects_and_updates_shadow`
  - `test_expire_manual_modes_resets_past_until`
- Integration test (`test_m2_end_to_end_pipeline`): gửi `mist on` rồi `fan on`, xác nhận `cmd` thành `applied` và `reported.actuators == {"fan": "on", "mist": "off"}`.
