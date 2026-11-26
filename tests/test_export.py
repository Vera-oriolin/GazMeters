class TestPDFExport:
    # Экспорт возвращает PDF-файл
    def test_export_ok(self, admin_client, make_user):
        make_user(username='pdf1')
        response = admin_client.get('/admin/export')
        assert response.status_code == 200 and response.mimetype == 'application/pdf'
        assert response.data[:4] == b'%PDF' and 'attachment' in response.headers.get('Content-Disposition', '')

    # Экспорт с фильтром просроченных работает
    def test_export_with_filter(self, admin_client, make_user):
        make_user(username='pdf2', last_offset_days=800, interval_years=1)
        response = admin_client.get('/admin/export?filter=overdue')
        assert response.status_code == 200 and response.data[:4] == b'%PDF'

    # Экспорт пустой выборки всё равно отдаёт PDF
    def test_export_empty(self, admin_client):
        response = admin_client.get('/admin/export?search=ZZZ_NO_MATCH')
        assert response.status_code == 200 and response.data[:4] == b'%PDF'

    # Экспорт с промышленным счётчиком работает
    def test_export_with_industrial(self, admin_client, make_user):
        make_user(username='pdfprom', meter_type='промышленный', model='G-6', organization='ООО «ПромЭкспорт»')
        response = admin_client.get('/admin/export')
        assert response.status_code == 200 and response.data[:4] == b'%PDF'

    # Не админ не может экспортировать
    def test_export_non_admin(self, client_logged_in):
        logged_client, _ = client_logged_in
        assert logged_client.get('/admin/export').status_code == 302