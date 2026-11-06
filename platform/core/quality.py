"""Đánh giá chất lượng dữ liệu tầng 1 (luật A1 – spec mục 8.2)."""

from collections import deque
from dataclasses import dataclass

# Bit cờ lỗi trong TelemetryPkt.flags (khớp firmware/common/gh_common/src/gh_packets.h)
FLAG_AHT_ERR = 1 << 0
FLAG_SOIL_ERR = 1 << 1
FLAG_BH_ERR = 1 << 2


@dataclass(frozen=True)
class QualityConfig:
    air_t_min: float = -10.0
    air_t_max: float = 60.0
    air_rh_min: float = 0.0
    air_rh_max: float = 100.0
    soil_m_min: float = 0.0
    soil_m_max: float = 100.0
    lux_min: float = 0.0
    lux_max: float = 65535.0
    # Cảm biến điện dung trên ADC 12-bit (0..4095): sát 0 hoặc 4095 là đứt/chập dây (Test T7)
    soil_raw_min: int = 50
    soil_raw_max: int = 4090
    # Ngưỡng nhảy vọt giữa 2 chu kỳ liên tiếp
    spike_air_t_c: float = 5.0
    spike_air_rh_pct: float = 25.0
    spike_soil_m_pct: float = 20.0
    # Số chu kỳ y hệt liên tiếp bị coi là kẹt
    stuck_soil_cycles: int = 60
    stuck_air_cycles: int = 30
    # Ngưỡng chênh lệch nghi ngờ giữa 2 zone cùng khối không khí
    neighbor_air_t_diff_c: float = 8.0
    neighbor_air_rh_diff_pct: float = 35.0


@dataclass(frozen=True)
class ReadingSample:
    ts_epoch: float
    air_t: float | None
    air_rh: float | None
    soil_m: float | None
    soil_raw: int | None
    lux: float | None = None
    flags: int = 0


class ZoneQualityTracker:
    """Theo dõi lịch sử ngắn hạn trong RAM của 1 zone để gắn nhãn quality cho từng mẫu mới."""

    def __init__(self, config: QualityConfig | None = None) -> None:
        self.cfg = config or QualityConfig()
        max_len = max(self.cfg.stuck_soil_cycles, self.cfg.stuck_air_cycles)
        self._history: deque[ReadingSample] = deque(maxlen=max_len)

    @property
    def last_sample(self) -> ReadingSample | None:
        return self._history[-1] if self._history else None

    def warm_up(self, samples_chronological: list[ReadingSample]) -> None:
        """Dựng lại cửa sổ trạng thái từ DB khi worker khởi động."""
        self._history.clear()
        for s in samples_chronological[-self._history.maxlen :]:  # type: ignore[misc]
            self._history.append(s)

    def evaluate(self, sample: ReadingSample, sample_interval_s: float = 60.0) -> str:
        """Trả về nhãn quality ∈ {'ok', 'dropout', 'out_of_range', 'spike', 'stuck'} và lưu mẫu."""
        label = self._classify(sample, sample_interval_s)
        self._history.append(sample)
        return label

    def _classify(self, s: ReadingSample, sample_interval_s: float) -> str:
        c = self.cfg

        # 1. Dropout phần cứng hoặc thiếu trường thiết yếu
        if s.flags & (FLAG_AHT_ERR | FLAG_SOIL_ERR):
            return "dropout"
        if s.air_t is None or s.air_rh is None or s.soil_m is None:
            return "dropout"

        # 2. Ngoài dải vật lý (bao gồm đứt/chập dây ADC đất đọc gần 0 hoặc 4095)
        if not (c.air_t_min <= s.air_t <= c.air_t_max):
            return "out_of_range"
        if not (c.air_rh_min <= s.air_rh <= c.air_rh_max):
            return "out_of_range"
        if not (c.soil_m_min <= s.soil_m <= c.soil_m_max):
            return "out_of_range"
        if s.soil_raw is not None and not (c.soil_raw_min <= s.soil_raw <= c.soil_raw_max):
            return "out_of_range"
        if s.lux is not None and not (c.lux_min <= s.lux <= c.lux_max):
            return "out_of_range"

        prev = self.last_sample
        if prev is not None:
            # 3. Spike: chỉ xét khi khoảng cách thời gian không quá 3 chu kỳ
            dt = s.ts_epoch - prev.ts_epoch
            max_gap = max(3.0 * sample_interval_s, 1.0)
            if 0 <= dt <= max_gap:
                if prev.air_t is not None and abs(s.air_t - prev.air_t) > c.spike_air_t_c:
                    return "spike"
                if prev.air_rh is not None and abs(s.air_rh - prev.air_rh) > c.spike_air_rh_pct:
                    return "spike"
                if prev.soil_m is not None and abs(s.soil_m - prev.soil_m) > c.spike_soil_m_pct:
                    return "spike"

        # 4. Stuck: giá trị y hệt qua >= N chu kỳ (tính cả mẫu hiện tại => cần N-1 mẫu trước đó)
        if s.soil_raw is not None and len(self._history) >= c.stuck_soil_cycles - 1:
            tail_soil = list(self._history)[-(c.stuck_soil_cycles - 1) :]
            if all(p.soil_raw == s.soil_raw for p in tail_soil):
                return "stuck"

        if len(self._history) >= c.stuck_air_cycles - 1:
            tail_air = list(self._history)[-(c.stuck_air_cycles - 1) :]
            if all(p.air_t == s.air_t and p.air_rh == s.air_rh for p in tail_air):
                return "stuck"

        return "ok"


def is_neighbor_divergent(
    a: ReadingSample,
    b: ReadingSample,
    sample_interval_s: float = 60.0,
    config: QualityConfig | None = None,
) -> bool:
    """Đối chiếu 2 zone cùng khối không khí trong nhà kính (spec 8.2)."""
    cfg = config or QualityConfig()
    if abs(a.ts_epoch - b.ts_epoch) > 3.0 * sample_interval_s:
        return False
    if a.air_t is None or b.air_t is None or a.air_rh is None or b.air_rh is None:
        return False
    return (
        abs(a.air_t - b.air_t) > cfg.neighbor_air_t_diff_c
        or abs(a.air_rh - b.air_rh) > cfg.neighbor_air_rh_diff_pct
    )

