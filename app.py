from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps

from database import db, User, Trek, Booking

app = Flask(__name__)
app.config['SECRET_KEY'] = 'trekking-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def role_required(*roles):
    """Restrict a route to one or more roles (admin / staff / trekker)."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('login'))
            if current_user.role not in roles:
                flash('You are not authorized to view that page.', 'danger')
                return redirect(url_for('dashboard_redirect'))
            return f(*args, **kwargs)
        return wrapped
    return decorator



# HOME / AUTH


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role')          # staff or trekker
        contact = request.form.get('contact', '').strip()

        if role not in ('staff', 'trekker'):
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('register'))

        if not name or not email or not password:
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please log in.', 'warning')
            return redirect(url_for('login'))

        status = 'pending' if role == 'staff' else 'approved'

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            role=role,
            contact=contact,
            status=status
        )
        db.session.add(user)
        db.session.commit()

        if role == 'staff':
            flash('Registration successful! Your account needs admin approval before you can log in.', 'info')
        else:
            flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid email or password.', 'danger')
            return redirect(url_for('login'))

        if user.status == 'blacklisted':
            flash('Your account has been blacklisted. Contact the admin.', 'danger')
            return redirect(url_for('login'))

        if user.role == 'staff' and user.status == 'pending':
            flash('Your staff account is awaiting admin approval.', 'warning')
            return redirect(url_for('login'))

        login_user(user)
        flash(f'Welcome back, {user.name}!', 'success')
        return redirect(url_for('dashboard_redirect'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard_redirect():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif current_user.role == 'staff':
        return redirect(url_for('staff_dashboard'))
    else:
        return redirect(url_for('user_dashboard'))



# ADMIN


@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    total_treks = Trek.query.count()
    total_users = User.query.filter_by(role='trekker').count()
    total_staff = User.query.filter_by(role='staff').count()
    total_bookings = Booking.query.count()
    pending_staff = User.query.filter_by(role='staff', status='pending').count()
    return render_template(
        'admin_dashboard.html',
        total_treks=total_treks,
        total_users=total_users,
        total_staff=total_staff,
        total_bookings=total_bookings,
        pending_staff=pending_staff
    )


@app.route('/admin/treks', methods=['GET', 'POST'])
@role_required('admin')
def manage_treks():
    if request.method == 'POST':
        trek_id = request.form.get('trek_id')
        name = request.form.get('name', '').strip()
        location = request.form.get('location', '').strip()
        difficulty = request.form.get('difficulty')
        duration = int(request.form.get('duration') or 0)
        total_slots = int(request.form.get('total_slots') or 0)
        status = request.form.get('status')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        assigned_staff_id = request.form.get('assigned_staff_id') or None

        if trek_id:
            trek = Trek.query.get(int(trek_id))
            if trek:
                slots_diff = total_slots - trek.total_slots
                trek.name = name
                trek.location = location
                trek.difficulty = difficulty
                trek.duration = duration
                trek.total_slots = total_slots
                trek.available_slots = max(0, trek.available_slots + slots_diff)
                trek.status = status
                trek.start_date = start_date
                trek.end_date = end_date
                trek.assigned_staff_id = int(assigned_staff_id) if assigned_staff_id else None
                db.session.commit()
                flash('Trek updated successfully.', 'success')
        else:
            trek = Trek(
                name=name, location=location, difficulty=difficulty,
                duration=duration, total_slots=total_slots,
                available_slots=total_slots, status=status or 'Open',
                start_date=start_date, end_date=end_date,
                assigned_staff_id=int(assigned_staff_id) if assigned_staff_id else None
            )
            db.session.add(trek)
            db.session.commit()
            flash('Trek created successfully.', 'success')
        return redirect(url_for('manage_treks'))

    q = request.args.get('q', '').strip()
    edit_id = request.args.get('edit', type=int)
    query = Trek.query
    if q:
        query = query.filter(db.or_(Trek.name.ilike(f'%{q}%'), Trek.location.ilike(f'%{q}%')))
    treks = query.order_by(Trek.id.desc()).all()
    staff_list = User.query.filter_by(role='staff', status='approved').all()
    edit_trek = Trek.query.get(edit_id) if edit_id else None
    return render_template('manage_treks.html', treks=treks, staff_list=staff_list, edit_trek=edit_trek, q=q)


@app.route('/admin/treks/delete/<int:trek_id>')
@role_required('admin')
def delete_trek(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    Booking.query.filter_by(trek_id=trek.id).delete()
    db.session.delete(trek)
    db.session.commit()
    flash('Trek removed.', 'info')
    return redirect(url_for('manage_treks'))


@app.route('/admin/staff')
@role_required('admin')
def manage_staffs():
    q = request.args.get('q', '').strip()
    query = User.query.filter_by(role='staff')
    if q:
        query = query.filter(db.or_(User.name.ilike(f'%{q}%'), User.email.ilike(f'%{q}%')))
    staff = query.order_by(User.id.desc()).all()
    return render_template('manage_staffs.html', staff=staff, q=q)


@app.route('/admin/staff/approve/<int:user_id>')
@role_required('admin')
def approve_staff(user_id):
    staff = User.query.get_or_404(user_id)
    staff.status = 'approved'
    db.session.commit()
    flash(f'{staff.name} has been approved.', 'success')
    return redirect(url_for('manage_staffs'))


@app.route('/admin/staff/blacklist/<int:user_id>')
@role_required('admin')
def blacklist_staff(user_id):
    staff = User.query.get_or_404(user_id)
    staff.status = 'blacklisted'
    db.session.commit()
    flash(f'{staff.name} has been blacklisted.', 'warning')
    return redirect(url_for('manage_staffs'))


@app.route('/admin/staff/unblacklist/<int:user_id>')
@role_required('admin')
def unblacklist_staff(user_id):
    staff = User.query.get_or_404(user_id)
    staff.status = 'approved'
    db.session.commit()
    flash(f'{staff.name} has been reinstated.', 'success')
    return redirect(url_for('manage_staffs'))


@app.route('/admin/users')
@role_required('admin')
def manage_users():
    q = request.args.get('q', '').strip()
    query = User.query.filter_by(role='trekker')
    if q:
        query = query.filter(db.or_(User.name.ilike(f'%{q}%'), User.email.ilike(f'%{q}%')))
    users = query.order_by(User.id.desc()).all()
    return render_template('manage_users.html', users=users, q=q)


@app.route('/admin/users/blacklist/<int:user_id>')
@role_required('admin')
def blacklist_user(user_id):
    user = User.query.get_or_404(user_id)
    user.status = 'blacklisted'
    db.session.commit()
    flash(f'{user.name} has been blacklisted.', 'warning')
    return redirect(url_for('manage_users'))


@app.route('/admin/users/unblacklist/<int:user_id>')
@role_required('admin')
def unblacklist_user(user_id):
    user = User.query.get_or_404(user_id)
    user.status = 'approved'
    db.session.commit()
    flash(f'{user.name} has been reinstated.', 'success')
    return redirect(url_for('manage_users'))



# STAFF


@app.route('/staff/dashboard')
@role_required('staff')
def staff_dashboard():
    treks = Trek.query.filter_by(assigned_staff_id=current_user.id).order_by(Trek.id.desc()).all()
    trek_counts = {t.id: Booking.query.filter_by(trek_id=t.id, status='Booked').count() for t in treks}
    return render_template('staff_dashboard.html', treks=treks, trek_counts=trek_counts)


@app.route('/staff/trek/<int:trek_id>', methods=['GET', 'POST'])
@role_required('staff')
def trek_detail(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    if trek.assigned_staff_id != current_user.id:
        flash('You are not assigned to this trek.', 'danger')
        return redirect(url_for('staff_dashboard'))

    if request.method == 'POST':
        available_slots = request.form.get('available_slots')
        status = request.form.get('status')
        if available_slots is not None and available_slots != '':
            trek.available_slots = max(0, min(trek.total_slots, int(available_slots)))
        if status:
            trek.status = status
        db.session.commit()
        flash('Trek updated.', 'success')
        return redirect(url_for('trek_detail', trek_id=trek.id))

    booked_count = Booking.query.filter_by(trek_id=trek.id, status='Booked').count()
    return render_template('trek_detail.html', trek=trek, booked_count=booked_count)


@app.route('/staff/trek/<int:trek_id>/participants')
@role_required('staff')
def participants(trek_id):
    trek = Trek.query.get_or_404(trek_id)
    if trek.assigned_staff_id != current_user.id:
        flash('You are not assigned to this trek.', 'danger')
        return redirect(url_for('staff_dashboard'))
    bookings = Booking.query.filter_by(trek_id=trek.id).order_by(Booking.booking_date.desc()).all()
    return render_template('participants.html', trek=trek, bookings=bookings)



# USER (TREKKER)


@app.route('/user/dashboard')
@role_required('trekker')
def user_dashboard():
    available_treks = Trek.query.filter_by(status='Open').count()
    my_active_bookings = Booking.query.filter_by(user_id=current_user.id, status='Booked').all()
    recent = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).limit(5).all()
    return render_template(
        'user_dashboard.html',
        available_treks=available_treks,
        my_bookings=my_active_bookings,
        recent=recent
    )


@app.route('/user/browse')
@role_required('trekker')
def browse_treks():
    difficulty = request.args.get('difficulty', '')
    location = request.args.get('location', '').strip()
    q = request.args.get('q', '').strip()

    query = Trek.query.filter_by(status='Open')
    if difficulty:
        query = query.filter_by(difficulty=difficulty)
    if location:
        query = query.filter(Trek.location.ilike(f'%{location}%'))
    if q:
        query = query.filter(Trek.name.ilike(f'%{q}%'))

    treks = query.order_by(Trek.start_date.asc()).all()
    my_booked_ids = {b.trek_id for b in Booking.query.filter_by(user_id=current_user.id, status='Booked').all()}
    return render_template(
        'browse_treks.html', treks=treks, difficulty=difficulty,
        location=location, q=q, my_booked_ids=my_booked_ids
    )


@app.route('/user/book/<int:trek_id>')
@role_required('trekker')
def book_trek(trek_id):
    trek = Trek.query.get_or_404(trek_id)

    if trek.status != 'Open':
        flash('This trek is not open for booking.', 'danger')
        return redirect(url_for('browse_treks'))

    if trek.available_slots <= 0:
        flash('Sorry, this trek is fully booked.', 'danger')
        return redirect(url_for('browse_treks'))

    existing = Booking.query.filter_by(user_id=current_user.id, trek_id=trek.id, status='Booked').first()
    if existing:
        flash('You have already booked this trek.', 'info')
        return redirect(url_for('browse_treks'))

    booking = Booking(user_id=current_user.id, trek_id=trek.id, status='Booked')
    trek.available_slots -= 1
    db.session.add(booking)
    db.session.commit()
    flash(f'Successfully booked "{trek.name}"!', 'success')
    return redirect(url_for('my_bookings'))


@app.route('/user/my_bookings')
@role_required('trekker')
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id, status='Booked').order_by(Booking.booking_date.desc()).all()
    return render_template('my_bookings.html', bookings=bookings)


@app.route('/user/cancel/<int:booking_id>')
@role_required('trekker')
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('my_bookings'))
    if booking.status == 'Booked':
        booking.status = 'Cancelled'
        booking.trek.available_slots += 1
        db.session.commit()
        flash('Booking cancelled.', 'info')
    return redirect(url_for('my_bookings'))


@app.route('/user/history')
@role_required('trekker')
def booking_history():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.booking_date.desc()).all()
    return render_template('booking_history.html', bookings=bookings)



# SHARED


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.name = request.form.get('name', '').strip()
        current_user.contact = request.form.get('contact', '').strip()
        new_password = request.form.get('password', '')
        if new_password:
            current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')



# DB INITIALISATION 


def create_default_admin():
    if not User.query.filter_by(role='admin').first():
        admin = User(
            name='Administrator',
            email='admin@trek.com',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            status='approved'
        )
        db.session.add(admin)
        db.session.commit()
        print('Default admin created -> email: admin@trek.com | password: admin123')
        
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_default_admin()
    app.run(debug=True)

