from datetime import date, timedelta
from app import add_years, parse_date, GasMeter

class TestAddYears:
    # Прибавление лет
    def test_simple(self):
        assert add_years(date(2020, 5, 10), 4) == date(2024, 5, 10)

    # 29 февраля при переходе на невисокосный год становится 28-м
    def test_leap_year_fallback(self):
        assert add_years(date(2020, 2, 29), 1) == date(2021, 2, 28)

    # Прибавление нуля лет не меняет дату
    def test_zero(self):
        assert add_years(date(2020, 1, 1), 0) == date(2020, 1, 1)

class TestParseDate:
    # Корректная дата преобразовывается
    def test_valid(self):
        assert parse_date('2024-03-15') == date(2024, 3, 15)

    # Пустая строка даёт None
    def test_empty(self):
        assert parse_date('') is None

    # Некорректная дата даёт None
    def test_invalid(self):
        assert parse_date('not-a-date') is None
        assert parse_date('2024-13-40') is None

class TestMeterStatus:
    # Вспомогательное создание счётчика с заданной датой следующей поверки
    def _make(self, next_check):
        return GasMeter(model='X', meter_type='бытовой', serial_number='S1', manufacture_date=date(2020, 1, 1), last_check_date=date(2020, 1, 1), next_check_date=next_check)

    # Просроченный статус
    def test_overdue(self):
        meter = self._make(date.today() - timedelta(days=5))
        assert meter.overdue is True and meter.status[0] == 'overdue' and meter.days == -5

    # Статус скоро
    def test_soon(self):
        meter = self._make(date.today() + timedelta(days=10))
        assert meter.overdue is False and meter.status[0] == 'soon'

    # Статус средне
    def test_mid(self):
        meter = self._make(date.today() + timedelta(days=60))
        assert meter.status[0] == 'mid'

    # Статус в норме
    def test_ok(self):
        meter = self._make(date.today() + timedelta(days=300))
        assert meter.status[0] == 'ok'