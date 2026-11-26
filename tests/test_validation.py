from datetime import date
from app import validate_meter

class TestMeterValidation:
    # Базовые валидные данные с возможностью переопределения
    def _base(self, **overrides):
        data = {'meter_type': 'бытовой', 'model': 'СГМ-1-1', 'serial_number': 'SN-UNIQUE-1', 'organization': ''}
        data.update(overrides)
        return data

    # Корректные данные не дают ошибок
    def test_valid(self, app):
        with app.app_context():
            assert validate_meter(self._base(), date(2020, 1, 1), date(2021, 1, 1), 4) == []

    # Некорректный тип счётчика это ошибка
    def test_invalid_type(self, app):
        with app.app_context():
            errors = validate_meter(self._base(meter_type='unknown'), date(2020, 1, 1), date(2021, 1, 1), 4)
            assert any('тип' in error.lower() for error in errors)

    # Пустая модель это ошибка
    def test_no_model(self, app):
        with app.app_context():
            errors = validate_meter(self._base(model=''), date(2020, 1, 1), date(2021, 1, 1), 4)
            assert any('модель' in error.lower() for error in errors)

    # Интервал вне допустимого диапазона это ошибка
    def test_interval_out_of_range(self, app):
        with app.app_context():
            errors = validate_meter(self._base(), date(2020, 1, 1), date(2021, 1, 1), 100)
            assert any('Интервал' in error for error in errors)

    # Для промышленного типа допустимы 1–5 лет
    def test_industrial_limits(self, app):
        form_data = self._base(meter_type='промышленный', model='G-6', organization='ООО «Пром»')
        with app.app_context():
            assert validate_meter(form_data, date(2020, 1, 1), date(2021, 1, 1), 3) == []
            errors = validate_meter(form_data, date(2020, 1, 1), date(2021, 1, 1), 7)
            assert any('Интервал' in error for error in errors)

    # Дата изготовления в будущем это ошибка
    def test_manufacture_in_future(self, app):
        with app.app_context():
            errors = validate_meter(self._base(), date(2099, 1, 1), date(2099, 1, 2), 4)
            assert any('будущем' in error for error in errors)

    # Поверка раньше изготовления это ошибка
    def test_check_before_manufacture(self, app):
        with app.app_context():
            errors = validate_meter(self._base(), date(2022, 1, 1), date(2020, 1, 1), 4)
            assert any('раньше' in error for error in errors)

    # Поверка в будущем это ошибка
    def test_check_in_future(self, app):
        with app.app_context():
            errors = validate_meter(self._base(), date(2020, 1, 1), date(2099, 1, 1), 4)
            assert any('будущем' in error for error in errors)

    # Промышленный без организации — ошибка
    def test_industrial_requires_organization(self, app):
        form_data = self._base(meter_type='промышленный', model='G-6', organization='')
        with app.app_context():
            errors = validate_meter(form_data, date(2020, 1, 1), date(2021, 1, 1), 3)
            assert any('организацию' in error.lower() for error in errors)

    # Бытовой с организацией — ошибка
    def test_household_forbids_organization(self, app):
        form_data = self._base(organization='ООО «Лишнее»')
        with app.app_context():
            errors = validate_meter(form_data, date(2020, 1, 1), date(2021, 1, 1), 4)
            assert any('организация' in error.lower() for error in errors)

    # Промышленный с организацией это без ошибок
    def test_industrial_with_organization_ok(self, app):
        form_data = self._base(meter_type='промышленный', model='G-6', organization='ООО «ПромГаз»')
        with app.app_context():
            assert validate_meter(form_data, date(2020, 1, 1), date(2021, 1, 1), 3) == []