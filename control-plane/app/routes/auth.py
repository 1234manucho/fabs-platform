from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from app import db
from app.models import User
from app.plans import PLANS, PAID_TIERS

bp = Blueprint('auth', __name__)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # 1. Honeypot — real users never fill this hidden field
        if request.form.get('website', '').strip():
            flash('Registration failed. Please try again.')
            return redirect(url_for('auth.login'))

        # 2. Rate limiting: max 3 signups per IP per hour
        ip = (request.headers.get('X-Forwarded-For', '') or request.remote_addr or '').split(',')[0].strip()
        if ip:
            cutoff = datetime.utcnow() - timedelta(hours=1)
            recent = User.query.filter(
                User.signup_ip == ip,
                User.created_at >= cutoff,
            ).count()
            if recent >= 3:
                flash('Too many signups from your IP. Try again in one hour.')
                return redirect(url_for('auth.login'))

        # 3. Collect fields
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        country = request.form.get('country', '').strip().upper()
        password = request.form.get('password', '')
        plan_tier = request.form.get('plan_tier', 'hobby').strip().lower()

        # 4. Validate
        errors = []
        if len(name) < 2:
            errors.append('Full name is required (min 2 characters)')
        if '@' not in email or len(email) < 5:
            errors.append('Valid email is required')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters')
        if len(phone) < 8:
            errors.append('Valid phone number is required')
        if not country or len(country) != 2:
            errors.append('Country is required')
        if plan_tier not in PLANS:
            errors.append('Invalid plan')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered')

        if errors:
            for e in errors:
                flash(e)
            return redirect(url_for('auth.register'))

        # 5. Create user
        is_first = User.query.count() == 0
        initial_status = 'active' if plan_tier == 'hobby' else 'pending_payment'

        user = User(
            email=email,
            name=name,
            phone=phone,
            country=country,
            signup_ip=ip or None,
            plan=plan_tier,
            subscription_status=initial_status,
        )
        if is_first:
            user.is_admin = True
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)

        # 6. Route them to the right place
        if plan_tier in PAID_TIERS:
            plan_name = PLANS[plan_tier]['name']
            flash(f'Welcome! Complete your payment to activate your {plan_name} plan.')
            return redirect(url_for('billing.pay', tier=plan_tier))

        flash('Account created. Welcome to FABS Deploy!')
        return redirect(url_for('main.dashboard'))

    return render_template('register.html', plans=PLANS)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(
            email=request.form['email'].strip().lower()
        ).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            # If they have a paid plan but haven't paid, take them straight to checkout
            if user.plan in PAID_TIERS and user.subscription_status != 'active':
                flash(f'Welcome back. Complete your {PLANS[user.plan]["name"]} payment to unlock all features.')
                return redirect(url_for('billing.pay', tier=user.plan))
            return redirect(url_for('main.dashboard'))
        flash('Invalid credentials')
    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.home'))
