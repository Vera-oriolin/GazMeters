from locust import HttpUser, task, between

# Пользователь, имитирующий клиента с бытовым счётчиком
class GasMeterUser(HttpUser):
    wait_time = between(1, 3)

    # При старте логин; при неудаче регистрация
    def on_start(self):
        self.username = "lt_loadtest"
        self.password = "loadtest123"
        response = self.client.post("/login", data={"username": self.username, "password": self.password}, allow_redirects=True)
        if "Неверный" in response.text:
            self._register()

    # Регистрация нагрузочного пользователя
    def _register(self):
        self.client.post("/register", data={"username": self.username, "full_name": "Нагрузочный Тест", "address": "ул. Тестовая, 1", "organization": "", "password": self.password, "password2": self.password, "meter_type": "бытовой", "model": "СГМ-1-1", "serial_number": "SN-LT-LOADTEST", "manufacture_date": "2020-01-01", "last_check_date": "2021-01-01", "interval": "4"}, allow_redirects=True)
        self.client.post("/login", data={"username": self.username, "password": self.password}, allow_redirects=True)

    # Просмотр клиентского кабинета
    @task(5)
    def view_dashboard(self):
        self.client.get("/client", name="/client")

    # Просмотр профиля
    @task(3)
    def view_profile(self):
        self.client.get("/profile", name="/profile")

    # Попытка открыть админку
    @task(2)
    def view_admin(self):
        self.client.get("/admin", name="/admin")

    # Попытка экспорта PDF
    @task(1)
    def export_pdf(self):
        self.client.get("/admin/export", name="/admin/export")

# Пользователь имитирующий администратора
class AdminUser(HttpUser):
    wait_time = between(2, 5)

    # При старте вход под админом
    def on_start(self):
        self.client.post("/login", data={"username": "admin", "password": "admin123"}, allow_redirects=True)

    # Просмотр списка клиентов
    @task(4)
    def admin_list(self):
        self.client.get("/admin", name="/admin")

    # Просмотр фильтра просроченные
    @task(2)
    def admin_filter_overdue(self):
        self.client.get("/admin?filter=overdue", name="/admin?filter=overdue")

    # Экспорт PDF
    @task(1)
    def admin_export(self):
        self.client.get("/admin/export", name="/admin/export")