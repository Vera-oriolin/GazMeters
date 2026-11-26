import os, sqlite3, time, pytest
selenium = pytest.importorskip('selenium')
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:5000')
ADMIN_USER, ADMIN_PASS = 'admin', 'admin123'
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
    driver_instance.implicitly_wait(3)
    yield driver_instance
    try:
        driver_instance.quit()
    except Exception:
        pass

# Фикстура явного ожидания
@pytest.fixture()
def wait(driver):
    return WebDriverWait(driver, 10)

# Определение пути к файлу БД из DATABASE_URL
def _db_path():
    url = os.environ.get('DATABASE_URL', 'sqlite:///gas_meters.db')
    if url.startswith('sqlite:///'):
        path = url[len('sqlite:///'):]
        return path if os.path.isabs(path) else os.path.abspath(path)

# Удаление E2E-пользователей и их счётчиков из БД
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

# Автофикстура очистки E2E-данных до и после теста
@pytest.fixture(autouse=True)
def cleanup_test_users():
    _purge_e2e_users()
    yield
    _purge_e2e_users()

# Выход из аккаунта и сброс cookies
def _logout(driver):
    try:
        driver.get(f'{BASE_URL}/logout')
    except Exception:
        pass
    try:
        driver.delete_all_cookies()
    except Exception:
        pass

# Генерация уникального имени с префиксом E2E
def _unique(prefix):
    return f'{E2E_PREFIX}{prefix}{int(time.time() * 1000) % 10_000_000}{os.getpid() % 1000}'

# Установка значения date-поля через JS с событием change
def _set_date(driver, name, iso_date):
    driver.execute_script("""
        const el = document.querySelector('[name="' + arguments[0] + '"]');
        if (!el) return false;
        el.value = arguments[1];
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        return true;
    """, name, iso_date)

# Вход в систему и проверка перехода в админку
def login(driver, wait, username, password):
    _logout(driver)
    driver.get(f'{BASE_URL}/login')
    username_field = driver.find_element(By.NAME, 'username')
    username_field.clear()
    username_field.send_keys(username)
    password_field = driver.find_element(By.NAME, 'password')
    password_field.clear()
    password_field.send_keys(password)
    driver.find_element(By.CSS_SELECTOR, 'form button').click()
    wait.until(EC.url_contains('/admin') or EC.url_contains('/client'))
    assert '/admin' in driver.current_url, (
        f'Ожидали /admin после входа под {username!r}, получили {driver.current_url}'
    )
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.metric')))

# Наличие хотя бы одного клиента для тестов карточки
def ensure_client_exists(driver, wait):
    login(driver, wait, ADMIN_USER, ADMIN_PASS)
    rows = driver.find_elements(By.CSS_SELECTOR, 'tbody tr')
    if rows and 'Нет записей' not in rows[0].text:
        return
    _logout(driver)
    driver.get(f'{BASE_URL}/register')
    wait.until(EC.presence_of_element_located((By.NAME, 'meter_type')))
    username = _unique('card')
    driver.find_element(By.NAME, 'username').send_keys(username)
    driver.find_element(By.NAME, 'full_name').send_keys('Селенииум Тест')
    driver.find_element(By.NAME, 'password').send_keys('secret123')
    driver.find_element(By.NAME, 'password2').send_keys('secret123')
    Select(driver.find_element(By.NAME, 'meter_type')).select_by_value('бытовой')
    wait.until(lambda current_driver: len(Select(current_driver.find_element(By.NAME, 'model')).options) > 1)
    Select(driver.find_element(By.NAME, 'model')).select_by_index(1)
    driver.find_element(By.NAME, 'serial_number').send_keys(f'SN-{username}')
    _set_date(driver, 'manufacture_date', '2020-01-01')
    _set_date(driver, 'last_check_date', '2021-01-01')
    wait.until(lambda current_driver: current_driver.find_element(By.ID, 'next_check_display').get_attribute('value') != '')
    driver.find_element(By.CSS_SELECTOR, 'form button').click()
    wait.until(EC.url_contains('/login'))

class TestSeleniumAuth:
    # На странице входа есть заголовок "Вход"
    def test_login_page_title(self, driver):
        driver.get(f'{BASE_URL}/login')
        assert 'Вход' in driver.title or 'Вход' in driver.page_source

    # Полный сценарий входа админа
    def test_admin_login_flow(self, driver, wait):
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        assert '/admin' in driver.current_url and 'Клиенты' in driver.page_source

    # Неверный вход показывает ошибку
    def test_wrong_login_shows_error(self, driver, wait):
        _logout(driver)
        driver.get(f'{BASE_URL}/login')
        username_field = driver.find_element(By.NAME, 'username')
        username_field.clear()
        username_field.send_keys('admin')
        password_field = driver.find_element(By.NAME, 'password')
        password_field.clear()
        password_field.send_keys('wrong')
        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.flash.error')))
        assert 'Неверный' in driver.page_source
        _logout(driver)

class TestSeleniumAdminDashboard:
    # На дашборде отображаются метрики
    def test_metrics_visible(self, driver, wait):
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        assert len(driver.find_elements(By.CSS_SELECTOR, '.metric')) >= 3

    # Работает фильтр по просроченным
    def test_filter_dropdown(self, driver, wait):
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        Select(driver.find_element(By.NAME, 'filter')).select_by_value('overdue')
        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.url_contains('filter=overdue'))

    # Поиск по несуществующему клиенту выдаёт: нет записей
    def test_search_field(self, driver, wait):
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        search_input = driver.find_element(By.NAME, 'search')
        search_input.clear()
        search_input.send_keys('НесуществующийКлиент123')
        driver.find_element(By.CSS_SELECTOR, 'form button').click()
        wait.until(EC.url_contains('search='))
        assert 'Нет записей' in driver.page_source

    # В таблице присутствует колонка Организация
    def test_organization_column_present(self, driver, wait):
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        headers = [(header.text or '').strip().lower() for header in driver.find_elements(By.CSS_SELECTOR, 'thead th')]
        assert any('организация' in header for header in headers), f'Заголовки: {headers}'

    # Ссылка PDF ведёт на экспорт
    def test_pdf_export_link(self, driver, wait):
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        link = driver.find_element(By.LINK_TEXT, 'PDF')
        assert '/admin/export' in link.get_attribute('href')

class TestSeleniumClientCard:
    # Открытие карточки первого клиента из списка
    def test_open_first_client_card(self, driver, wait):
        ensure_client_exists(driver, wait)
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        rows = driver.find_elements(By.CSS_SELECTOR, 'tbody tr')
        assert rows and 'Нет записей' not in rows[0].text, 'Нет клиентов в БД'
        rows[0].find_element(By.CSS_SELECTOR, 'a').click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.hero')))
        assert 'Карточка клиента' in driver.page_source

    # Возврат к списку по ссылке: Назад к списку
    def test_back_to_list(self, driver, wait):
        ensure_client_exists(driver, wait)
        login(driver, wait, ADMIN_USER, ADMIN_PASS)
        rows = driver.find_elements(By.CSS_SELECTOR, 'tbody tr')
        assert rows and 'Нет записей' not in rows[0].text, 'Нет клиентов в БД'
        rows[0].find_element(By.CSS_SELECTOR, 'a').click()
        wait.until(EC.presence_of_element_located((By.LINK_TEXT, 'Назад к списку')))
        driver.find_element(By.LINK_TEXT, 'Назад к списку').click()
        wait.until(EC.url_contains('/admin'))