import os, sys, pytest
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('SECRET_KEY', 'test-secret')

from app import app as flask_app, database, User, GasMeter, MeterInterval, MODELS
from werkzeug.security import generate_password_hash

# Фикстура приложения на всю сессию тестов
@pytest.fixture(scope='session')
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SERVER_NAME='localhost')
    with flask_app.app_context():
        database.drop_all(); database.create_all()
        if not User.query.filter_by(username='admin').first():
            database.session.add(User(username='admin', full_name='Администратор', is_admin=True, password_hash=generate_password_hash('admin123')))
        if not MeterInterval.query.first():
            database.session.add_all([MeterInterval(meter_type=meter_type, model=model, years=years) for meter_type, model, years in MODELS])
        database.session.commit()
    yield flask_app

# Фикстура тестового HTTP-клиента Flask
@pytest.fixture()
def client(app): return app.test_client()

# Фикстура сессии БД с откатом после теста
@pytest.fixture()
def db_session(app):
    with app.app_context():
        yield database
        database.session.rollback()

# Фикстура клиента авторизованного как админ
@pytest.fixture()
def admin_client(client):
    client.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    return client

# Фабрика пользователей и счётчиков для тестов
@pytest.fixture()
def make_user(app):
    created = []
    def _make(username='client1', password='pass123', full_name='Иванов Иван Иванович', address='ул. Ленина, 1', organization=None, with_meter=True, last_offset_days=0, interval_years=4, meter_type='бытовой', model='СГМ-1-1', serial=None):
        if meter_type == 'промышленный' and with_meter and not organization:
            organization = 'ООО «ТестПром»'
        with app.app_context():
            client_user = User(username=username, full_name=full_name, address=address, organization=organization, password_hash=generate_password_hash(password))
            database.session.add(client_user); database.session.flush()
            if with_meter:
                last_check_date = date.today() - timedelta(days=last_offset_days)
                next_check_date = last_check_date.replace(year=last_check_date.year + interval_years)
                database.session.add(GasMeter(user_id=client_user.id, model=model, meter_type=meter_type, serial_number=serial or f'SN-{username.upper()}-0001', manufacture_date=last_check_date - timedelta(days=365), last_check_date=last_check_date, next_check_date=next_check_date))
            database.session.commit()
            created.append(client_user.id)
            return client_user.id
    yield _make
    with app.app_context():
        for user_id in created:
            client_user = database.session.get(User, user_id)
            if client_user: database.session.delete(client_user)
        database.session.commit()

# Фикстура клиента вошедшего под обычным пользователем
@pytest.fixture()
def client_logged_in(client, make_user):
    user_id = make_user(username='user_a', password='pass123')
    client.post('/login', data={'username': 'user_a', 'password': 'pass123'}, follow_redirects=True)
    return client, user_id