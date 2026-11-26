class TestClientDashboard:
    # Клиентский кабинет открывается для клиента
    def test_client_view(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.get('/client')
        assert response.status_code == 200 and 'Мой счётчик'.encode() in response.data

    # Админа перенаправляет из клиентского кабинета
    def test_admin_redirected_from_client(self, admin_client):
        assert admin_client.get('/client').status_code == 302

class TestProfile:
    # Страница профиля открывается
    def test_profile_get(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.get('/profile')
        assert response.status_code == 200 and 'Мой профиль'.encode() in response.data

    # Обновление ФИО и адреса сохраняется
    def test_profile_update_name(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.post('/profile', data={'full_name': 'Новое Имя', 'address': 'Новый адрес'}, follow_redirects=True)
        assert 'Профиль обновлён'.encode() in response.data and 'Новое Имя'.encode() in response.data

    # Успешная смена пароля
    def test_profile_change_password_success(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.post('/profile', data={'full_name': 'X', 'address': '', 'current_password': 'pass123', 'new_password': 'newpass1', 'new_password2': 'newpass1'}, follow_redirects=True)
        assert 'Профиль обновлён'.encode() in response.data

    # Неверный текущий пароль это ошибка
    def test_profile_wrong_current_password(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.post('/profile', data={'full_name': 'X', 'current_password': 'WRONG', 'new_password': 'newpass1', 'new_password2': 'newpass1'}, follow_redirects=True)
        assert 'Неверный текущий пароль'.encode() in response.data

    # Несовпадение новых паролей это ошибка
    def test_profile_password_mismatch(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.post('/profile', data={'full_name': 'X', 'current_password': 'pass123', 'new_password': 'newpass1', 'new_password2': 'different'}, follow_redirects=True)
        assert 'Пароли не совпадают'.encode() in response.data

    # Пустое ФИО это ошибка
    def test_profile_empty_full_name(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.post('/profile', data={'full_name': ''}, follow_redirects=True)
        assert 'Укажите ФИО'.encode() in response.data

    # Для промышленного счётчика организация обязательна
    def test_profile_industrial_requires_organization(self, client, make_user):
        make_user(username='prom_prof', password='pass123', meter_type='промышленный', model='G-6', organization='ООО «Пром»')
        client.post('/login', data={'username': 'prom_prof', 'password': 'pass123'}, follow_redirects=True)
        response = client.post('/profile', data={'full_name': 'ООО «Пром»', 'address': 'addr', 'organization': ''}, follow_redirects=True)
        assert 'рганизац'.encode() in response.data

    # Для промышленного счётчика организация обновляется
    def test_profile_industrial_updates_organization(self, client, make_user):
        make_user(username='prom_prof2', password='pass123', meter_type='промышленный', model='G-6', organization='ООО «Старое»')
        client.post('/login', data={'username': 'prom_prof2', 'password': 'pass123'}, follow_redirects=True)
        response = client.post('/profile', data={'full_name': 'ООО «Пром2»', 'address': 'addr', 'organization': 'ООО «НовоеПром»'}, follow_redirects=True)
        assert 'Профиль обновлён'.encode() in response.data and 'ООО «НовоеПром»'.encode() in response.data

    # Для бытового счётчика организация игнорируется
    def test_profile_household_ignores_organization(self, client_logged_in, app):
        logged_client, user_id = client_logged_in
        response = logged_client.post('/profile', data={'full_name': 'X', 'address': 'Y', 'organization': 'ООО «Игнор»'}, follow_redirects=True)
        assert 'Профиль обновлён'.encode() in response.data
        from app import User
        with app.app_context():
            assert not User.query.filter_by(username='user_a').first().organization