class TestAdminAccess:
    # Анонимный пользователь перенаправляется со страницы админа
    def test_anonymous_redirected(self, client):
        assert client.get('/admin').status_code == 302

    # Не админ перенаправляется в клиентский кабинет
    def test_non_admin_redirected(self, client_logged_in):
        logged_client, _ = client_logged_in
        response = logged_client.get('/admin')
        assert response.status_code == 302 and '/client' in response.headers['Location']

    # Админ получает доступ к странице клиентов
    def test_admin_ok(self, admin_client):
        response = admin_client.get('/admin')
        assert response.status_code == 200 and 'Клиенты'.encode() in response.data

class TestAdminFilters:
    # Фильтр просроченных клиентов работает
    def test_filter_overdue(self, admin_client, make_user):
        make_user(username='ov1', last_offset_days=800, interval_years=1)
        assert admin_client.get('/admin?filter=overdue').status_code == 200

    # Фильтр ближайших 30 дней работает
    def test_filter_30(self, admin_client, make_user):
        make_user(username='f30', last_offset_days=340, interval_years=1)
        assert admin_client.get('/admin?filter=30').status_code == 200

    # Поиск по ФИО находит клиента
    def test_search_by_name(self, admin_client, make_user):
        make_user(username='srch', full_name='Уникальный Клиент')
        assert 'Уникальный Клиент'.encode() in admin_client.get('/admin?search=Уникальный').data

    # Поиск по заводскому номеру находит клиента
    def test_search_by_serial(self, admin_client, make_user):
        make_user(username='ser', serial='SN-FIND-ME')
        assert 'SN-FIND-ME'.encode() in admin_client.get('/admin?search=SN-FIND-ME').data

    # Некорректный фильтр не ломает страницу
    def test_invalid_filter_defaults(self, admin_client):
        assert admin_client.get('/admin?filter=bogus').status_code == 200

    # Фильтр ближайшая проверка работает
    def test_nearest(self, admin_client, make_user):
        make_user(username='n1', last_offset_days=0, interval_years=1)
        make_user(username='n2', last_offset_days=100, interval_years=1)
        assert admin_client.get('/admin?filter=nearest').status_code == 200

class TestAdminClientCard:
    # Карточка существующего клиента открывается
    def test_card_ok(self, admin_client, make_user):
        user_id = make_user(username='carduser')
        response = admin_client.get(f'/admin/client/{user_id}')
        assert response.status_code == 200 and 'Карточка клиента'.encode() in response.data

    # Несуществующий клиент сообщение об ошибке
    def test_card_missing(self, admin_client):
        response = admin_client.get('/admin/client/999999', follow_redirects=True)
        assert 'Клиент не найден'.encode() in response.data

    # Админ не может открыть карточку самого себя как клиента
    def test_card_admin_forbidden(self, admin_client, app):
        from app import User
        with app.app_context():
            user_id = User.query.filter_by(username='admin').first().id
        response = admin_client.get(f'/admin/client/{user_id}', follow_redirects=True)
        assert 'Клиент не найден'.encode() in response.data

class TestAdminEdit:
    # GET-форма редактирования открывается
    def test_edit_get(self, admin_client, make_user):
        user_id = make_user(username='edituser')
        response = admin_client.get(f'/admin/client/{user_id}/edit')
        assert response.status_code == 200 and 'Редактирование счётчика'.encode() in response.data

    # Успешное сохранение изменений счётчика
    def test_edit_post_success(self, admin_client, make_user):
        user_id = make_user(username='edituser2')
        form_data = {'meter_type': 'бытовой', 'model': 'СГМН-1', 'serial_number': 'SN-EDIT-0001', 'manufacture_date': '2020-01-01', 'last_check_date': '2022-01-01', 'interval': '6'}
        response = admin_client.post(f'/admin/client/{user_id}/edit', data=form_data, follow_redirects=True)
        assert 'Данные счётчика обновлены'.encode() in response.data

    # Интервал вне допустимого диапазона отклоняется
    def test_edit_interval_out_of_range(self, admin_client, make_user):
        user_id = make_user(username='edituser3')
        form_data = {'meter_type': 'бытовой', 'model': 'СГМ-1-1', 'serial_number': 'SN-EDIT-0002', 'manufacture_date': '2020-01-01', 'last_check_date': '2022-01-01', 'interval': '99'}
        response = admin_client.post(f'/admin/client/{user_id}/edit', data=form_data, follow_redirects=True)
        assert 'Интервал'.encode() in response.data

class TestAdminCheck:
    # Успешная отметка поверки
    def test_mark_check_success(self, admin_client, make_user):
        user_id = make_user(username='chk1')
        response = admin_client.post(f'/admin/client/{user_id}/check', data={'check_date': '2024-01-01', 'interval': '4'}, follow_redirects=True)
        assert 'Поверка отмечена'.encode() in response.data

    # Пустая дата поверки обрабатывается ошибкой
    def test_mark_check_no_date(self, admin_client, make_user):
        user_id = make_user(username='chk2')
        response = admin_client.post(f'/admin/client/{user_id}/check', data={'check_date': '', 'interval': '4'}, follow_redirects=True)
        assert 'Укажите дату поверки'.encode() in response.data

    # Будущая дата поверки запрещена
    def test_mark_check_future(self, admin_client, make_user):
        user_id = make_user(username='chk3')
        response = admin_client.post(f'/admin/client/{user_id}/check', data={'check_date': '2099-01-01', 'interval': '4'}, follow_redirects=True)
        assert 'будущем'.encode() in response.data

    # Некорректный интервал отклоняется
    def test_mark_check_bad_interval(self, admin_client, make_user):
        user_id = make_user(username='chk4')
        response = admin_client.post(f'/admin/client/{user_id}/check', data={'check_date': '2024-01-01', 'interval': '50'}, follow_redirects=True)
        assert 'Интервал'.encode() in response.data

    # Если интервал не указан, то берётся паспортный по модели
    def test_mark_check_default_interval_from_model(self, admin_client, make_user):
        user_id = make_user(username='chk5', model='СГМ-1-1')
        response = admin_client.post(f'/admin/client/{user_id}/check', data={'check_date': '2024-01-01'}, follow_redirects=True)
        assert 'Поверка отмечена'.encode() in response.data

class TestAdminDelete:
    # Успешное удаление клиента
    def test_delete_success(self, admin_client, make_user):
        user_id = make_user(username='del1', full_name='Удаляемый Клиент')
        response = admin_client.post(f'/admin/client/{user_id}/delete', follow_redirects=True)
        assert 'удалён'.encode() in response.data

    # Удаление несуществующего клиента даёт ошибку
    def test_delete_missing(self, admin_client):
        response = admin_client.post('/admin/client/999999/delete', follow_redirects=True)
        assert 'Клиент не найден'.encode() in response.data