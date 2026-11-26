class TestLogin:
    # Страница входа открывается
    def test_login_page(self, client):
        response = client.get('/login')
        assert response.status_code == 200 and 'Вход'.encode() in response.data

    # Успешный вход администратора
    def test_login_success_admin(self, client):
        response = client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
        assert response.status_code == 200 and 'Клиенты'.encode() in response.data

    # Неверный пароль даёт сообщение об ошибке
    def test_login_wrong_password(self, client):
        response = client.post('/login', data={'username': 'admin', 'password': 'wrong'}, follow_redirects=True)
        assert 'Неверный логин или пароль'.encode() in response.data

    # Корень перенаправляет неавторизованного на логин
    def test_index_redirects_to_login(self, client):
        response = client.get('/')
        assert response.status_code == 302 and '/login' in response.headers['Location']

class TestRegister:
    PAYLOAD = {'username': 'newuser', 'full_name': 'Петров Пётр Петрович', 'address': 'ул. Мира, 2', 'organization': '', 'password': 'secret123', 'password2': 'secret123', 'meter_type': 'бытовой', 'model': 'СГМ-1-1', 'serial_number': 'SN-NEW-0001', 'manufacture_date': '2020-01-01', 'last_check_date': '2021-01-01', 'interval': '4', 'agree_terms': 'on', 'agree_cookies': 'on'}
    INDUSTRIAL = {'username': 'promuser', 'full_name': 'ООО «ПромГаз»', 'address': 'г. Москва, ул. Заводская, 1', 'organization': 'ООО «ПромГаз»', 'password': 'secret123', 'password2': 'secret123', 'meter_type': 'промышленный', 'model': 'G-6', 'serial_number': 'SN-PROM-0001', 'manufacture_date': '2020-01-01', 'last_check_date': '2021-01-01', 'interval': '1', 'agree_terms': 'on', 'agree_cookies': 'on'}

    # Страница регистрации доступна
    def test_register_page(self, client):
        assert client.get('/register').status_code == 200

    # Успешная регистрация бытового счётчика
    def test_register_success(self, client):
        response = client.post('/register', data=self.PAYLOAD, follow_redirects=True)
        assert 'Регистрация успешна'.encode() in response.data

    # Успешная регистрация промышленного счётчика с организацией
    def test_register_industrial_success(self, client, app):
        response = client.post('/register', data=self.INDUSTRIAL, follow_redirects=True)
        assert 'Регистрация успешна'.encode() in response.data
        from app import User
        with app.app_context():
            client_user = User.query.filter_by(username='promuser').first()
            assert client_user is not None and client_user.organization == 'ООО «ПромГаз»'

    # Промышленный счётчик без организации — ошибка
    def test_register_industrial_without_organization(self, client):
        payload = {**self.INDUSTRIAL, 'username': 'noorgan', 'serial_number': 'SN-NOORG-0001', 'organization': ''}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'организация' in response.data.decode().lower()

    # Бытовой счётчик с организацией — ошибка
    def test_register_household_with_organization(self, client):
        payload = {**self.PAYLOAD, 'username': 'householder', 'serial_number': 'SN-HOUSE-0001', 'organization': 'ООО «Нельзя»'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'организация' in response.data.decode().lower()

    # Несовпадение паролей это ошибка
    def test_register_password_mismatch(self, client):
        payload = {**self.PAYLOAD, 'username': 'u2', 'password2': 'different'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'Пароли не совпадают'.encode() in response.data

    # Слишком короткий пароль это ошибка
    def test_register_short_password(self, client):
        payload = {**self.PAYLOAD, 'username': 'u3', 'password': '123', 'password2': '123'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'Пароль минимум 6 символов'.encode() in response.data

    # Некорректный логин это ошибка
    def test_register_bad_username(self, client):
        payload = {**self.PAYLOAD, 'username': 'кириллица'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'Логин'.encode() in response.data

    # Занятый логин это ошибка
    def test_register_duplicate_username(self, client):
        payload = {**self.PAYLOAD, 'username': 'admin'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'Логин занят'.encode() in response.data

    # Занятый заводской номер это ошибка
    def test_register_duplicate_serial(self, client, make_user):
        make_user(username='exists', serial='SN-DUP-0001')
        payload = {**self.PAYLOAD, 'username': 'fresh', 'serial_number': 'SN-DUP-0001'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'Заводской номер занят'.encode() in response.data

    # Будущая дата изготовления это ошибка
    def test_register_future_manufacture(self, client):
        payload = {**self.PAYLOAD, 'username': 'u4', 'manufacture_date': '2099-01-01'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'будущем'.encode() in response.data

    # Поверка раньше изготовления это ошибка
    def test_register_check_before_manufacture(self, client):
        payload = {**self.PAYLOAD, 'username': 'u5', 'manufacture_date': '2022-01-01', 'last_check_date': '2020-01-01'}
        response = client.post('/register', data=payload, follow_redirects=True)
        assert 'раньше изготовления'.encode() in response.data

class TestLogout:
    # Выход из аккаунта возвращает на страницу входа
    def test_logout(self, admin_client):
        response = admin_client.get('/logout', follow_redirects=True)
        assert 'Вход'.encode() in response.data

    # Выход требует авторизации
    def test_logout_requires_auth(self, client):
        assert client.get('/logout').status_code == 302