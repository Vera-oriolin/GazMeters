import io, os, re
from datetime import datetime, date, timedelta
from flask import Flask, render_template, redirect, url_for, request, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import event
from sqlalchemy.engine import Engine
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-secret-change-me'),
    SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///gas_meters.db'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
database = SQLAlchemy(app)
login_manager = LoginManager(app); login_manager.login_view = 'login'

INTERVAL_LIMITS = {'бытовой': (4, 12), 'промышленный': (1, 5)}
MODELS = [('бытовой', 'СГМ-1-1', 4), ('бытовой', 'ВК-G4', 4), ('бытовой', 'СГМН-1', 6), ('бытовой', 'Гранд-4', 8), ('бытовой', 'СГМ-1-1-2', 10), ('бытовой', 'МКМ-4', 12), ('промышленный', 'G-6', 1), ('промышленный', 'G-10', 2), ('промышленный', 'G-16', 3), ('промышленный', 'G-25', 4), ('промышленный', 'G-40', 5)]
USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_]{3,}$')
VALID_FILTERS = ('all', 'overdue', '30', 'year', 'nearest')

E2E_PREFIXES = ('_e2e_', 'lt_')
E2E_FULLNAME_MARKERS = ('Селенииум Тест', 'Логин Тест', 'ООО «ТестПром»', 'Нагрузочный Тест')

# Проверка, является ли пользователь E2E-тестовым
def is_e2e_user(user):
    return ((user.username and any(user.username.startswith(prefix) for prefix in E2E_PREFIXES)) or (user.full_name and any(marker in user.full_name for marker in E2E_FULLNAME_MARKERS)))

FONT_NORMAL, FONT_BOLD = 'Cyr', 'Cyr-Bold'
_font_available = False
for regular_path, bold_path in [('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'), ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'), ('/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf')]:
    if os.path.exists(regular_path):
        pdfmetrics.registerFont(TTFont(FONT_NORMAL, regular_path))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, bold_path if os.path.exists(bold_path) else regular_path))
        pdfmetrics.registerFontFamily(FONT_NORMAL, normal=FONT_NORMAL, bold=FONT_BOLD, italic=FONT_NORMAL, boldItalic=FONT_BOLD)
        _font_available = True
        break
if not _font_available:
    FONT_NORMAL, FONT_BOLD = 'Helvetica', 'Helvetica-Bold'

# Модель пользователя
class User(UserMixin, database.Model):
    id = database.Column(database.Integer, primary_key=True)
    username = database.Column(database.String(80), unique=True, nullable=False)
    password_hash = database.Column(database.String(200), nullable=False)
    full_name = database.Column(database.String(150), nullable=False)
    address = database.Column(database.String(250))
    organization = database.Column(database.String(200))
    is_admin = database.Column(database.Boolean, default=False)
    meter = database.relationship('GasMeter', backref='owner', uselist=False, cascade='all, delete-orphan')

# Модель газового счётчика
class GasMeter(database.Model):
    __table_args__ = (database.CheckConstraint("meter_type IN ('бытовой','промышленный')", name='ck_meter_type'),)
    id = database.Column(database.Integer, primary_key=True)
    user_id = database.Column(database.Integer, database.ForeignKey('user.id'), unique=True, nullable=False)
    model = database.Column(database.String(100), nullable=False)
    meter_type = database.Column(database.String(50), nullable=False)
    serial_number = database.Column(database.String(50), unique=True, nullable=False)
    manufacture_date = database.Column(database.Date, nullable=False)
    last_check_date = database.Column(database.Date, nullable=False)
    next_check_date = database.Column(database.Date, nullable=False)

    # Число дней до следующей поверки
    @property
    def days(self): return (self.next_check_date - date.today()).days

    # Просроченно
    @property
    def overdue(self): return self.days < 0

    # Статус счётчика
    @property
    def status(self):
        days_left = self.days
        return ('overdue', 'Просрочена') if days_left < 0 else ('soon', 'Скоро') if days_left <= 30 else ('mid', 'Средне') if days_left <= 90 else ('ok', 'В норме')

# Справочник межповерочных интервалов по моделям
class MeterInterval(database.Model):
    id = database.Column(database.Integer, primary_key=True)
    meter_type = database.Column(database.String(50), nullable=False)
    model = database.Column(database.String(100), unique=True, nullable=False)
    years = database.Column(database.Integer, nullable=False)

# Загрузка пользователя для Flask-Login
@login_manager.user_loader
def load_user(user_id): return database.session.get(User, int(user_id))

# Парсинг даты из ISO-строки
def parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date() if value else None
    except ValueError:
        return None

# Прибавление лет к дате с обработкой 29 февраля
def add_years(source_date, years_count):
    try:
        return source_date.replace(year=source_date.year + years_count)
    except ValueError:
        return source_date.replace(year=source_date.year + years_count, day=28)

# Валидация данных счётчика, возвращает список ошибок
def validate_meter(form_data, manufacture_date, last_check_date, interval_years, exclude_user_id=None):
    errors = []
    if form_data['meter_type'] not in INTERVAL_LIMITS:
        errors.append('Выберите тип счётчика'); min_interval, max_interval = 1, 12
    else:
        min_interval, max_interval = INTERVAL_LIMITS[form_data['meter_type']]
    if not form_data['model']:
        errors.append('Выберите модель')
    if not form_data['serial_number']:
        errors.append('Укажите заводской номер')
    else:
        duplicate = GasMeter.query.filter(database.func.lower(GasMeter.serial_number) == form_data['serial_number'].strip().lower()).first()
        if duplicate and duplicate.user_id != exclude_user_id:
            errors.append('Заводской номер занят')
    organization_value = (form_data.get('organization') or '').strip()
    if form_data['meter_type'] == 'промышленный' and not organization_value:
        errors.append('Укажите организацию для промышленного счётчика')
    if form_data['meter_type'] == 'бытовой' and organization_value:
        errors.append('Организация указывается только для промышленного счётчика')
    if not manufacture_date: errors.append('Укажите дату изготовления')
    if not last_check_date: errors.append('Укажите дату прошлой поверки')
    if not interval_years:
        errors.append('Выберите интервал')
    elif not (min_interval <= interval_years <= max_interval):
        errors.append(f'Интервал {min_interval}–{max_interval} лет')
    if manufacture_date and manufacture_date > date.today(): errors.append('Дата изготовления в будущем')
    if manufacture_date and last_check_date and last_check_date < manufacture_date: errors.append('Поверка раньше изготовления')
    if last_check_date and last_check_date > date.today(): errors.append('Поверка в будущем')
    return errors

# Создание/обновление счётчика и организации пользователя
def save_meter(client_user, form_data, manufacture_date, last_check_date, interval_years):
    meter = client_user.meter or GasMeter(user_id=client_user.id)
    database.session.add(meter)
    meter.model = form_data['model']
    meter.meter_type = form_data['meter_type']
    meter.serial_number = form_data['serial_number'].strip().upper()
    meter.manufacture_date = manufacture_date
    meter.last_check_date = last_check_date
    meter.next_check_date = add_years(last_check_date, interval_years)
    client_user.organization = (form_data.get('organization') or '').strip() or None
    return meter

# Выбор клиентов и статистики с учётом поиска и фильтра
def get_clients(search_query, filter_type):
    query = User.query.options(database.joinedload(User.meter)).filter_by(is_admin=False).join(GasMeter)
    if search_query:
        pattern = f'%{search_query}%'
        query = query.filter(User.username.ilike(pattern) | User.full_name.ilike(pattern) | User.address.ilike(pattern) | User.organization.ilike(pattern) | GasMeter.serial_number.ilike(pattern))
    clients_list = [user for user in query.all() if user.meter and not is_e2e_user(user)]
    if filter_type == 'overdue':
        clients_list = [user for user in clients_list if user.meter.days < 0]
    elif filter_type in ('30', 'year'):
        days_limit = {'30': 30, 'year': 365}[filter_type]
        clients_list = [user for user in clients_list if 0 <= user.meter.days <= days_limit]
    elif filter_type == 'nearest':
        clients_list = sorted((user for user in clients_list if user.meter.days >= 0), key=lambda user: user.meter.days)[:1]
    if filter_type != 'nearest':
        clients_list.sort(key=lambda user: user.meter.next_check_date)
    all_clients = [user for user in User.query.filter_by(is_admin=False).all() if user.meter and not is_e2e_user(user)]
    statistics = {'total': len(all_clients), 'overdue': sum(1 for user in all_clients if user.meter.days < 0), 'in_30': sum(1 for user in all_clients if 0 <= user.meter.days <= 30)}
    return clients_list, statistics

# Получение клиента по id с исключением админа
def get_client(user_id):
    client_user = database.session.get(User, user_id)
    return None if (not client_user or client_user.is_admin) else client_user

# Вычисление интервала в годах по датам прошлой и следующей поверки
def get_interval_from_dates(last_check_date, next_check_date):
    if not last_check_date or not next_check_date: return ''
    year_difference = next_check_date.year - last_check_date.year
    if (next_check_date.month, next_check_date.day) < (last_check_date.month, last_check_date.day): year_difference -= 1
    return str(year_difference) if year_difference > 0 else ''

# Корневой маршрут: редирект по роли или на логин
@app.route('/')
def index():
    if not current_user.is_authenticated: return redirect(url_for('login'))
    return redirect(url_for('admin' if current_user.is_admin else 'client'))

# Маршрут входа
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin' if current_user.is_admin else 'client'))
    if request.method == 'POST':
        client_user = User.query.filter_by(username=request.form.get('username', '').strip()).first()
        if client_user and check_password_hash(client_user.password_hash, request.form.get('password', '')):
            login_user(client_user)
            return redirect(url_for('admin' if client_user.is_admin else 'client'))
        flash('Неверный логин или пароль', 'error')
    return render_template('login.html')

# Маршрут регистрации с созданием пользователя и счётчика
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('index'))
    intervals_list = MeterInterval.query.order_by(MeterInterval.meter_type, MeterInterval.model).all()
    intervals_data = [{'type': interval.meter_type, 'model': interval.model, 'years': interval.years} for interval in intervals_list]
    today_iso = date.today().isoformat()
    if request.method == 'GET':
        return render_template('register.html', intervals=intervals_list, intervals_data=intervals_data, today=today_iso)
    form_keys = ('username full_name address organization model meter_type serial_number manufacture_date last_check_date interval').split()
    form_data = {key: request.form.get(key, '').strip() for key in form_keys}
    password, password_repeat = request.form.get('password', ''), request.form.get('password2', '')
    manufacture_date, last_check_date = parse_date(form_data['manufacture_date']), parse_date(form_data['last_check_date'])
    interval_years = int(form_data['interval']) if form_data['interval'].isdigit() else 0
    errors = []
    if not request.form.get('agree_terms'):
        errors.append('Необходимо согласие на обработку персональных данных')
    if not request.form.get('agree_cookies'):
        errors.append('Необходимо согласие на использование файлов Cookies')
    if not USERNAME_PATTERN.match(form_data['username']): errors.append('Логин: минимум 3 символа, только латиница, цифры, _')
    if not form_data['full_name']: errors.append('Укажите ФИО')
    if len(password) < 6: errors.append('Пароль минимум 6 символов')
    if password != password_repeat: errors.append('Пароли не совпадают')
    if User.query.filter_by(username=form_data['username']).first(): errors.append('Логин занят')
    errors += validate_meter(form_data, manufacture_date, last_check_date, interval_years)
    if errors:
        for error_text in errors: flash(error_text, 'error')
        return render_template('register.html', intervals=intervals_list, intervals_data=intervals_data, today=today_iso, **form_data)
    try:
        client_user = User(username=form_data['username'], password_hash=generate_password_hash(password), full_name=form_data['full_name'], address=form_data['address'])
        database.session.add(client_user)
        database.session.flush()
        save_meter(client_user, form_data, manufacture_date, last_check_date, interval_years)
        database.session.commit()
        flash('Регистрация успешна. Войдите.', 'success')
        return redirect(url_for('login'))
    except Exception as error:
        database.session.rollback()
        if 'UNIQUE constraint failed: user.username' in str(error):
            flash('Этот логин уже занят. Попробуйте другой.', 'error')
        else:
            flash('Произошла ошибка при сохранении данных. Попробуйте ещё раз.', 'error')
        return render_template('register.html', intervals=intervals_list, intervals_data=intervals_data, today=today_iso, **form_data)

# Маршрут выхода из аккаунта
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Клиентский кабинет
@app.route('/client')
@login_required
def client():
    if current_user.is_admin: return redirect(url_for('admin'))
    return render_template('client_dashboard.html', user=current_user)

# Профиль клиента: обновление данных и пароля
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if current_user.is_admin: return redirect(url_for('admin'))
    if request.method == 'POST':
        new_full_name = request.form.get('full_name', '').strip()
        new_address = request.form.get('address', '').strip()
        is_industrial = bool(current_user.meter and current_user.meter.meter_type == 'промышленный')
        new_organization = request.form.get('organization', '').strip() if is_industrial else ''
        current_password, new_password, new_password_repeat = (request.form.get(key, '') for key in ('current_password', 'new_password', 'new_password2'))
        errors = []
        if not new_full_name: errors.append('Укажите ФИО')
        if is_industrial and not new_organization: errors.append('Укажите организацию')
        if current_password or new_password or new_password_repeat:
            if not check_password_hash(current_user.password_hash, current_password): errors.append('Неверный текущий пароль')
            if len(new_password) < 6: errors.append('Новый пароль минимум 6 символов')
            if new_password != new_password_repeat: errors.append('Пароли не совпадают')
        if errors:
            for error_text in errors: flash(error_text, 'error')
        else:
            current_user.full_name = new_full_name
            current_user.address = new_address
            current_user.organization = new_organization or None
            if new_password: current_user.password_hash = generate_password_hash(new_password)
            database.session.commit(); flash('Профиль обновлён', 'success')
            return redirect(url_for('profile'))
    return render_template('profile.html', user=current_user)

# Админ-панель со списком клиентов
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin: return redirect(url_for('client'))
    search_query = request.args.get('search', '').strip()
    filter_type = request.args.get('filter', 'all')
    if filter_type not in VALID_FILTERS: filter_type = 'all'
    clients_list, statistics = get_clients(search_query, filter_type)
    return render_template('admin_dashboard.html', users=clients_list, stats=statistics, search=search_query, filter_type=filter_type)

# Карточка клиента для админа
@app.route('/admin/client/<int:user_id>')
@login_required
def admin_client(user_id):
    if not current_user.is_admin: return redirect(url_for('client'))
    client_user = get_client(user_id)
    if not client_user:
        flash('Клиент не найден', 'error'); return redirect(url_for('admin'))
    return render_template('client_card.html', user=client_user, max_date=date.today().isoformat(), today_str=date.today().isoformat())

# Редактирование счётчика клиента админом
@app.route('/admin/client/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_client_edit(user_id):
    if not current_user.is_admin: return redirect(url_for('client'))
    client_user = get_client(user_id)
    if not client_user:
        flash('Клиент не найден', 'error'); return redirect(url_for('admin'))
    intervals_list = MeterInterval.query.order_by(MeterInterval.meter_type, MeterInterval.model).all()
    intervals_data = [{'type': interval.meter_type, 'model': interval.model, 'years': interval.years} for interval in intervals_list]
    today_iso = date.today().isoformat()
    if request.method == 'GET':
        meter = client_user.meter
        form_data = dict(model=meter.model if meter else '', meter_type=meter.meter_type if meter else '', serial_number=meter.serial_number if meter else '', manufacture_date=meter.manufacture_date.strftime('%Y-%m-%d') if meter else '', last_check_date=meter.last_check_date.strftime('%Y-%m-%d') if meter else '', interval=get_interval_from_dates(meter.last_check_date if meter else None, meter.next_check_date if meter else None), organization=client_user.organization or '')
        return render_template('client_edit.html', user=client_user, intervals=intervals_list, intervals_data=intervals_data, today=today_iso, **form_data)
    form_data = {key: request.form.get(key, '').strip() for key in ('model meter_type serial_number manufacture_date last_check_date interval organization').split()}
    manufacture_date, last_check_date = parse_date(form_data['manufacture_date']), parse_date(form_data['last_check_date'])
    interval_years = int(form_data['interval']) if form_data['interval'].isdigit() else 0
    errors = validate_meter(form_data, manufacture_date, last_check_date, interval_years, exclude_user_id=client_user.id)
    if errors:
        for error_text in errors: flash(error_text, 'error')
        return render_template('client_edit.html', user=client_user, intervals=intervals_list, intervals_data=intervals_data, today=today_iso, **form_data)
    save_meter(client_user, form_data, manufacture_date, last_check_date, interval_years); database.session.commit()
    flash('Данные счётчика обновлены', 'success')
    return redirect(url_for('admin_client', user_id=client_user.id))

# Отметка поверки счётчика админом
@app.route('/admin/client/<int:user_id>/check', methods=['POST'])
@login_required
def admin_client_check(user_id):
    if not current_user.is_admin: return redirect(url_for('client'))
    client_user = get_client(user_id)
    if not client_user or not client_user.meter:
        flash('Счётчик не найден', 'error'); return redirect(url_for('admin'))
    check_date = parse_date(request.form.get('check_date', ''))
    if not check_date:
        flash('Укажите дату поверки', 'error'); return redirect(url_for('admin_client', user_id=user_id))
    if check_date > date.today():
        flash('Дата поверки не может быть в будущем', 'error'); return redirect(url_for('admin_client', user_id=user_id))
    interval_value = request.form.get('interval', '').strip()
    min_interval, max_interval = INTERVAL_LIMITS.get(client_user.meter.meter_type, (1, 12))
    if interval_value.isdigit():
        interval_years = int(interval_value)
        if not (min_interval <= interval_years <= max_interval):
            flash(f'Интервал для типа «{client_user.meter.meter_type}» — {min_interval}–{max_interval} лет', 'error'); return redirect(url_for('admin_client', user_id=user_id))
    else:
        model_interval = MeterInterval.query.filter_by(model=client_user.meter.model).first()
        interval_years = model_interval.years if model_interval else min_interval
    client_user.meter.last_check_date = check_date
    client_user.meter.next_check_date = add_years(check_date, interval_years)
    database.session.commit()
    flash(f'Поверка отмечена. Следующая — {client_user.meter.next_check_date.strftime("%d.%m.%Y")}', 'success')
    return redirect(url_for('admin_client', user_id=user_id))

# Удаление клиента админом
@app.route('/admin/client/<int:user_id>/delete', methods=['POST'])
@login_required
def admin_client_delete(user_id):
    if not current_user.is_admin: return redirect(url_for('client'))
    client_user = get_client(user_id)
    if not client_user:
        flash('Клиент не найден', 'error'); return redirect(url_for('admin'))
    client_name = client_user.full_name
    database.session.delete(client_user); database.session.commit()
    flash(f'Клиент «{client_name}» удалён', 'success')
    return redirect(url_for('admin'))

# Экспорт списка клиентов в PDF
@app.route('/admin/export')
@login_required
def admin_export():
    if not current_user.is_admin: return redirect(url_for('client'))
    search_query = request.args.get('search', '').strip()
    filter_type = request.args.get('filter', 'all')
    if filter_type not in VALID_FILTERS: filter_type = 'all'
    clients_list, _ = get_clients(search_query, filter_type)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm, title='Клиенты')
    styles = getSampleStyleSheet()
    cell_style = ParagraphStyle('Cell', fontName=FONT_NORMAL, fontSize=7, leading=8, textColor=colors.HexColor('#0f172a'))
    header_style = ParagraphStyle('Head', fontName=FONT_BOLD, fontSize=7.5, leading=9, textColor=colors.HexColor('#1e40af'))
    title_style = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=15, fontName=FONT_NORMAL, textColor=colors.HexColor('#0b2545'), spaceAfter=8)
    subtitle_style = ParagraphStyle('Sub', parent=styles['Normal'], fontSize=9.5, fontName=FONT_NORMAL, textColor=colors.HexColor('#64748b'), spaceAfter=12)
    story = [Paragraph('Учёт газовых счётчиков — список клиентов', title_style), Paragraph(f'Дата: {date.today().strftime("%d.%m.%Y")} · Фильтр: {filter_type} · Найдено: {len(clients_list)}', subtitle_style)]
    if clients_list:
        headers = ['ФИО', 'Логин', 'Адрес', 'Организация', 'Модель', 'Тип', 'Заводской номер', 'Изготовлен', 'Прошлая', 'Следующая', 'Статус']
        data = [[Paragraph(header, header_style) for header in headers]]
        for client_user in clients_list:
            meter = client_user.meter
            row = [client_user.full_name, client_user.username, client_user.address or '—', (client_user.organization or '—') if meter.meter_type == 'промышленный' else '—', meter.model, meter.meter_type, meter.serial_number, meter.manufacture_date.strftime('%d.%m.%Y'), meter.last_check_date.strftime('%d.%m.%Y'), meter.next_check_date.strftime('%d.%m.%Y'), meter.status[1]]
            data.append([Paragraph(str(value), cell_style) for value in row])
        widths = [2.4, 1.3, 2.2, 2.4, 1.8, 1.4, 2.1, 1.5, 1.5, 1.5, 1.1]
        table = Table(data, repeatRows=1, colWidths=[width * cm for width in widths])
        table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eff6ff')), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cbd5e1')), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fbff')]), ('LEFTPADDING', (0, 0), (-1, -1), 3), ('RIGHTPADDING', (0, 0), (-1, -1), 3), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
        story.append(table)
    else:
        story.append(Paragraph('Нет записей', subtitle_style))
    document.build(story)
    pdf_data = buffer.getvalue(); buffer.close()
    return Response(pdf_data, mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename=clients_{date.today().isoformat()}.pdf'})

# Включение поддержки внешних ключей для SQLite при подключении
@event.listens_for(Engine, 'connect')
def enable_foreign_keys(connection, _):
    cursor = connection.cursor(); cursor.execute('PRAGMA foreign_keys=ON'); cursor.close()

with app.app_context():
    database.create_all()
    try:
        with database.engine.connect() as connection:
            columns = [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(user)").fetchall()]
            if 'organization' not in columns:
                connection.exec_driver_sql("ALTER TABLE user ADD COLUMN organization VARCHAR(200)")
                connection.commit()
    except Exception:
        pass
    if not User.query.filter_by(username='admin').first():
        database.session.add(User(username='admin', full_name='Администратор', is_admin=True, password_hash=generate_password_hash('admin123')))
        database.session.commit()
    if not MeterInterval.query.first():
        database.session.add_all([MeterInterval(meter_type=meter_type, model=model, years=years) for meter_type, model, years in MODELS])
        database.session.commit()

if __name__ == '__main__':
    app.run(debug=True)