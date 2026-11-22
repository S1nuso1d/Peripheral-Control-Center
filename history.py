"""История заряда: оценка времени работы и определение «заряжается».

Чистый Python (без Qt и Windows API), поэтому логику легко тестировать отдельно.
Windows не сообщает Bluetooth-устройствам статус зарядки, поэтому он выводится
из истории: если уровень за последние минуты вырос — устройство заряжается.
"""
import json
import logging
import time
from pathlib import Path

from i18n import tr

log = logging.getLogger("BatteryTray")

KEEP_SEC = 7 * 24 * 3600     # сколько хранить историю (7 дней)
MIN_STEP_SEC = 600           # одинаковый уровень пишем не чаще, чем раз в 10 минут
CHARGE_WINDOW_SEC = 45 * 60  # окно для определения зарядки
CHARGE_MIN_RISE = 2          # минимальный рост (в %), чтобы считать это зарядкой
GAP_SEC = 3 * 3600           # разрыв в данных: приложение или устройство было выключено
MIN_SPAN_SEC = 30 * 60       # для оценки нужно хотя бы 30 минут разряда
MIN_DROP = 2                 # и падение хотя бы на 2%


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.data: dict[str, list[list[float]]] = {}
        self._dirty = False
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = {k: [[float(t), int(v)] for t, v in pts] for k, pts in raw.items()}
        except Exception:
            self.data = {}

    def add(self, name: str, level: int, now: float | None = None):
        now = time.time() if now is None else now
        pts = self.data.setdefault(name, [])
        if pts and pts[-1][1] == level and now - pts[-1][0] < MIN_STEP_SEC:
            return
        pts.append([now, int(level)])
        self._dirty = True
        cutoff = now - KEEP_SEC
        while len(pts) > 1 and pts[0][0] < cutoff:
            pts.pop(0)

    def charging(self, name: str, now: float | None = None) -> bool:
        """Уровень вырос за последние минуты => идёт зарядка (вывод, не точный факт)."""
        now = time.time() if now is None else now
        pts = [p for p in self.data.get(name, []) if p[0] >= now - CHARGE_WINDOW_SEC]
        if len(pts) < 2:
            return False
        return pts[-1][1] - min(p[1] for p in pts[:-1]) >= CHARGE_MIN_RISE

    def hours_left(self, name: str):
        """Сколько часов осталось при текущей скорости разряда, либо None."""
        pts = self.data.get(name, [])
        if len(pts) < 2:
            return None
        i = len(pts) - 1
        # идём назад, пока уровень не рос и нет большого разрыва во времени
        while i > 0 and pts[i - 1][1] >= pts[i][1] and pts[i][0] - pts[i - 1][0] <= GAP_SEC:
            i -= 1
        seg = pts[i:]
        if len(seg) < 2:
            return None
        span = seg[-1][0] - seg[0][0]
        drop = seg[0][1] - seg[-1][1]
        if span < MIN_SPAN_SEC or drop < MIN_DROP:
            return None
        rate = drop / (span / 3600)  # % в час
        return min(seg[-1][1] / rate, 999.0)

    def series(self, name: str, hours: float = 24.0, now: float | None = None):
        """Точки (время, уровень) за последние hours часов — для мини-графика."""
        now = time.time() if now is None else now
        cutoff = now - hours * 3600
        return [(t, lv) for t, lv in self.data.get(name, []) if t >= cutoff]

    def save(self):
        if not self._dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            tmp.replace(self.path)
            self._dirty = False
        except Exception:
            log.warning("cannot save history", exc_info=True)


def format_hours(h: float) -> str:
    if h < 1:
        return tr("left_min", max(int(h * 60), 1))
    if h < 48:
        return tr("left_h", round(h))
    return tr("left_d", round(h / 24))
