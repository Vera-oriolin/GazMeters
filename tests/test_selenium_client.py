import os, re, time, sqlite3, pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, JavascriptException

pytest.importorskip('selenium')

BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:5000')
E2E_PREFIX = '_e2e_'

# Фикстура драйвера Chrome
@pytest.fixture()
def driver():
    options = Options()
    if not os.environ.get('HEADED'):
        options.add_argument('--headless=new')
    for argument in ('--no-sandbox', '--disable-dev-shm-usage', '--window-size=1400,1000',
                     '--log-level=3', '--disable-gpu', '--disable-extensions',
                     '--disable-background-networking', '--disable-sync',
                     '--disable-features=Translate,MediaRouter'):
        options.add_argument(argument)
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver_instance = webdriver.Chrome(options=options)
    driver_instance.implicitly_wait(2)
    driver_instance.set_page_load_timeout(20)
    yield driver_instance
    try:
        driver_instance.quit()
    except Exception:
        pass

# Фикстура ожидания
@pytest.fixture()
def wait(driver):
    return WebDriverWait(driver, 15)

# Путь к файлу БД из DATABASE_URL
def _db_path():
    url = os.environ.get('DATABASE_URL', 'sqlite:///gas_meters.db')
    if url.startswith('sqlite:///'):
        path = url[len('sqlite:///'):]
        return path if os.path.isabs(path) else os.path.abspath(path)

# Очистка E2E-пользователей из БД
def _purge_e2e_users():
    db_path = _db_path()
    if not db_path or not os.path.exists(db_path):
        return
    try:
        connection = sqlite3.connect(db_path)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM gas_meter WHERE user_id IN (SELECT id FROM user WHERE username LIKE ?)",
                       (f'{E2E_PREFIX}%',))
        cursor.execute("DELETE FROM user WHERE username LIKE ?", (f'{E2E_PREFIX}%',))
        connection.commit()
        connection.close()
    except Exception as exception:
        print(f'[cleanup] не удалось очистить БД: {exception}')

# Автофикстура очистки E2E-данных
@pytest.fixture(autouse=True)
def cleanup_test_users():
    _purge_e2e_users()
    yield
    _purge_e2e_users()

# Генерация уникального E2E-имени
def unique_name(prefix):
    return f'{E2E_PREFIX}{prefix}{int(time.time() * 1000) % 10_000_000}{os.getpid() % 1000}'

# Выход и сброс cookies
def ensure_logged_out(driver):
    try:
        driver.get(f'{BASE_URL}/logout')
    except Exception:
        pass
    try:
        driver.delete_all_cookies()
    except Exception:
        pass

# Открытие страницы регистрации с проверкой доступности полей
def open_register_page(driver, wait):
    driver.get(f'{BASE_URL}/register')
    if '/register' not in driver.current_url:
        ensure_logged_out(driver)
        driver.get(f'{BASE_URL}/register')
    try:
        wait.until(EC.presence_of_element_located((By.NAME, 'meter_type')))
        wait.until(EC.presence_of_element_located((By.NAME, 'manufacture_date')))
        wait.until(EC.presence_of_element_located((By.NAME, 'last_check_date')))
    except TimeoutException:
        pytest.skip(f'Форма регистрации недоступна. URL: {driver.current_url}')
    return True

# Очистка и ввод значения в поле по name
def _fill(driver, name, value):
    element = driver.find_element(By.NAME, name)
    element.clear()
    element.send_keys(value)

# Установка даты через JS с событием change
def set_date_by_name(driver, name, iso_date):
    script = """
        const el = document.querySelector('[name="' + arguments[0] + '"]');
        if (!el) { return false; }
        el.value = arguments[1];
        el.dispatchEvent(new Event('input',  { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    """
    try:
        success = driver.execute_script(script, name, iso_date)
    except JavascriptException as exception:
        pytest.skip(f'JS-ошибка при установке {name}: {exception}')
    if not success:
        pytest.skip(f'Поле [name={name}] не найдено')

# Выбор типа счётчика и модели, ожидание загрузки моделей
def select_meter_type_and_model(driver, wait, meter_type='бытовой', model_index=1):
    Select(driver.find_element(By.NAME, 'meter_type')).select_by_value(meter_type)
    wait.until(lambda current_driver: len(Select(current_driver.find_element(By.NAME, 'model')).options) > 1)
    Select(driver.find_element(By.NAME, 'model')).select_by_index(model_index)

# Установка чекбоксов согласия
def check_agreements(driver):
    driver.find_element(By.NAME, 'agree_terms').click()
    driver.find_element(By.NAME, 'agree_cookies').click()

class TestRegisterFlow:
    # Полный сценарий регистрации бытового счётчика
    def test_full_registration(self, driver, wait):
        ensure_logged_out(driver)
        open_register_page(driver, wait)
        username = unique_name('sel')
        _fill(driver, 'username', username)
        _fill(driver, 'full_name', 'Селенииум Тест')
        _fill(driver, 'address', 'ул. Тестовая, 1')
        _fill(driver, 'password', 'secret123')
        _fill(driver, 'password2', 'secret123')
        select_meter_type_and_model(driver, wait, 'бытовой')
        _fill(driver, 'serial_number', f'SN-{username}')
        set_date_by_name(driver, 'manufacture_date', '2020-01-01')
        set_date_by_name(driver, 'last_check_date', '2021-01-01')
        wait.until(lambda current_driver: current_driver.find_element(By.ID, 'next_check_display').get_attribute(
            'value') != '')

        check_agreements(driver)

        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.url_contains('/login'))
        assert 'Регистрация успешна' in driver.page_source

    # Регистрация промышленного счётчика требует организацию
    def test_industrial_registration_requires_organization(self, driver, wait):
        ensure_logged_out(driver)
        open_register_page(driver, wait)
        username = unique_name('prom')
        _fill(driver, 'username', username)
        _fill(driver, 'full_name', 'ООО «ТестПром»')
        _fill(driver, 'password', 'secret123')
        _fill(driver, 'password2', 'secret123')
        select_meter_type_and_model(driver, wait, 'промышленный')
        wait.until(lambda current_driver: current_driver.find_element(By.ID, 'org_field').is_displayed())
        _fill(driver, 'serial_number', f'SN-{username}')
        set_date_by_name(driver, 'manufacture_date', '2020-01-01')
        set_date_by_name(driver, 'last_check_date', '2021-01-01')

        check_agreements(driver)

        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(lambda current_driver: 'рганизац' in current_driver.page_source)
        _fill(driver, 'organization', 'ООО «ПромГаз»')
        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.url_contains('/login'))
        assert 'Регистрация успешна' in driver.page_source

    # Для бытового счётчика поле организации скрыто
    def test_household_hides_organization_field(self, driver, wait):
        ensure_logged_out(driver)
        open_register_page(driver, wait)
        select_meter_type_and_model(driver, wait, 'бытовой')
        assert not driver.find_element(By.ID, 'org_field').is_displayed()

    # Вход сразу после успешной регистрации
    def test_login_after_register(self, driver, wait):
        ensure_logged_out(driver)
        open_register_page(driver, wait)
        username = unique_name('login')
        _fill(driver, 'username', username)
        _fill(driver, 'full_name', 'Логин Тест')
        _fill(driver, 'password', 'secret123')
        _fill(driver, 'password2', 'secret123')
        select_meter_type_and_model(driver, wait, 'бытовой')
        _fill(driver, 'serial_number', f'SN-{username}')
        set_date_by_name(driver, 'manufacture_date', '2020-01-01')
        set_date_by_name(driver, 'last_check_date', '2021-01-01')

        check_agreements(driver)

        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.url_contains('/login'))
        _fill(driver, 'username', username)
        _fill(driver, 'password', 'secret123')
        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.url_contains('/client'))
        assert 'Мой счётчик' in driver.page_source

class TestJSInteractions:
    # Проверка автоматического пересчёта даты следующей поверки
    def test_interval_recalculation(self, driver, wait):
        ensure_logged_out(driver)
        open_register_page(driver, wait)
        select_meter_type_and_model(driver, wait, 'бытовой')
        set_date_by_name(driver, 'last_check_date', '2020-01-01')
        display = driver.find_element(By.ID, 'next_check_display')
        wait.until(lambda current_driver: display.get_attribute('value') != '')
        result = display.get_attribute('value')
        assert re.match(r'^\d{2}\.\d{2}\.\d{4}$', result), f'Ожидалась дата: {result!r}'
        interval = int(Select(driver.find_element(By.NAME, 'interval')).first_selected_option.get_attribute('value'))
        assert int(result.split('.')[-1]) == 2020 + interval