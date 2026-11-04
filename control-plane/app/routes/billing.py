import os
import json
import base64
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify,
)
from flask_login import login_required, current_user
from app import db
from app.models import Payment
from app.plans import PLANS, get_price

bp = Blueprint('billing', __name__, url_prefix='/billing')


# ============================================================
# M-PESA (Safaricom Daraja — STK Push / Lipa na M-Pesa Online)
# ============================================================

def _mpesa_base_url():
    env = os.getenv('MPESA_ENV', 'sandbox').lower()
    if env == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def _mpesa_token():
    """Get OAuth access token from Safaricom."""
    key = os.getenv('MPESA_CONSUMER_KEY')
    secret = os.getenv('MPESA_CONSUMER_SECRET')
    if not key or not secret:
        raise Exception('M-Pesa credentials not configured (MPESA_CONSUMER_KEY/SECRET)')

    encoded = base64.b64encode(f'{key}:{secret}'.encode()).decode()
    r = requests.get(
        f'{_mpesa_base_url()}/oauth/v1/generate?grant_type=client_credentials',
        headers={'Authorization': f'Basic {encoded}'},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()['access_token']


def _mpesa_stk_push(phone, amount_kes, account_ref, description):
    """
    Send STK Push prompt to the user's phone.
    Returns the full response dict (contains CheckoutRequestID).
    """
    token = _mpesa_token()
    shortcode = os.getenv('MPESA_SHORTCODE')
    passkey = os.getenv('MPESA_PASSKEY')
    callback_url = os.getenv('MPESA_CALLBACK_URL')

    if not all([shortcode, passkey, callback_url]):
        raise Exception('M-Pesa config incomplete (MPESA_SHORTCODE/PASSKEY/CALLBACK_URL)')

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    password = base64.b64encode(
        f'{shortcode}{passkey}{timestamp}'.encode()
    ).decode()

    # Normalize phone to 2547XXXXXXXX / 2541XXXXXXXX
    phone = phone.strip().replace(' ', '').replace('+', '').replace('-', '')
    if phone.startswith('0'):
        phone = '254' + phone[1:]
    elif phone.startswith('7') or phone.startswith('1'):
        phone = '254' + phone

    payload = {
        'BusinessShortCode': shortcode,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(amount_kes),
        'PartyA': phone,
        'PartyB': shortcode,
        'PhoneNumber': phone,
        'CallBackURL': callback_url,
        'AccountReference': account_ref,
        'TransactionDesc': description,
    }

    r = requests.post(
        f'{_mpesa_base_url()}/mpesa/stkpush/v1/processrequest',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ============================================================
# DPO PAY (Card — hosted checkout)
# ============================================================

def _dpo_api_url():
    env = os.getenv('DPO_ENV', 'sandbox').lower()
    if env == 'production':
        return 'https://secure.3gdirectpay.com/API/v6/'
    return 'https://secure1.sandbox.directpay.online/API/v6/'


def _dpo_pay_url():
    env = os.getenv('DPO_ENV', 'sandbox').lower()
    if env == 'production':
        return 'https://secure.3gdirectpay.com/payv3.php?ID='
    return 'https://secure1.sandbox.directpay.online/payv3.php?ID='


def _dpo_create_token(payment_id, plan_tier, amount_usd):
    """Create a DPO transaction token. Returns TransToken."""
    company_token = os.getenv('DPO_COMPANY_TOKEN')
    if not company_token:
        raise Exception('DPO company token not configured (DPO_COMPANY_TOKEN)')

    back_url = os.getenv('DPO_BACK_URL')
    if not back_url:
        raise Exception('DPO back URL not configured (DPO_BACK_URL)')

    service_type = os.getenv('DPO_SERVICE_TYPE', '5525')

    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{company_token}</CompanyToken>
  <Request>createToken</Request>
  <Transaction>
    <PaymentAmount>{amount_usd}</PaymentAmount>
    <PaymentCurrency>USD</PaymentCurrency>
    <CompanyRef>{payment_id}</CompanyRef>
    <RedirectURL>{back_url}</RedirectURL>
    <BackURL>{back_url}</BackURL>
    <CompanyRefUnique>0</CompanyRefUnique>
    <PTL>15</PTL>
  </Transaction>
  <Services>
    <Service>
      <ServiceType>{service_type}</ServiceType>
      <ServiceDescription>{plan_tier} plan — FABS Deploy</ServiceDescription>
      <ServiceDate>{datetime.utcnow().strftime('%Y/%m/%d %H:%M')}</ServiceDate>
    </Service>
  </Services>
</API3G>'''

    r = requests.post(
        _dpo_api_url(),
        data=xml.encode('utf-8'),
        headers={'Content-Type': 'application/xml; charset=utf-8'},
        timeout=30,
    )
    r.raise_for_status()

    root = ET.fromstring(r.text)
    result = root.findtext('Result')
    explanation = root.findtext('ResultExplanation')
    token = root.findtext('TransToken')

    if result != '000' or not token:
        raise Exception(f'DPO createToken failed: {result} — {explanation}')

    return token


def _dpo_verify_token(trans_token):
    """Verify a DPO transaction server-side. Returns dict with result."""
    company_token = os.getenv('DPO_COMPANY_TOKEN')
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<API3G>
  <CompanyToken>{company_token}</CompanyToken>
  <Request>verifyToken</Request>
  <TransactionToken>{trans_token}</TransactionToken>
</API3G>'''

    r = requests.post(
        _dpo_api_url(),
        data=xml.encode('utf-8'),
        headers={'Content-Type': 'application/xml; charset=utf-8'},
        timeout=30,
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)
    return {
        'result': root.findtext('Result'),
        'explanation': root.findtext('ResultExplanation'),
        'amount': root.findtext('TransactionAmount'),
        'currency': root.findtext('TransactionCurrency'),
    }


# ============================================================
# ROUTES
# ============================================================

@bp.route('/pay/<tier>')
@login_required
def pay(tier):
    """Show payment method selector for a paid plan."""
    tier = tier.lower()
    if tier not in PLANS or tier == 'hobby':
        flash('Invalid plan selected.')
        return redirect(url_for('main.dashboard'))

    plan = PLANS[tier]

    # If already active on this plan, don't double-charge
    if current_user.plan == tier and current_user.subscription_status == 'active':
        flash(f'You are already subscribed to {plan["name"]}.')
        return redirect(url_for('main.dashboard'))

    return render_template('billing/pay.html', tier=tier, plan=plan)


@bp.route('/mpesa/initiate', methods=['POST'])
@login_required
def mpesa_initiate():
    """Trigger STK Push to the user's phone."""
    tier = request.form.get('tier', '').strip().lower()
    if tier not in PLANS or tier == 'hobby':
        flash('Invalid plan.')
        return redirect(url_for('main.dashboard'))

    price_usd = get_price(tier)
    fx_rate = float(os.getenv('USD_TO_KES', '130'))
    amount_kes = int(price_usd * fx_rate)

    payment = Payment(
        user_id=current_user.id,
        plan_tier=tier,
        amount_usd=price_usd,
        amount_local=amount_kes,
        currency='KES',
        provider='mpesa',
        status='pending',
    )
    db.session.add(payment)
    db.session.commit()

    phone = current_user.phone or request.form.get('phone', '').strip()
    if not phone:
        flash('Please add a phone number before paying with M-Pesa.')
        return redirect(url_for('billing.pay', tier=tier))

    try:
        resp = _mpesa_stk_push(
            phone=phone,
            amount_kes=amount_kes,
            account_ref=f'FABS-{payment.id}',
            description=f'FABS {tier} plan',
        )
        payment.provider_ref = resp.get('CheckoutRequestID')
        payment.raw_response = json.dumps(resp)
        db.session.commit()

        flash(f'STK Push sent to {phone}. Enter your M-Pesa PIN to complete payment.')
        return redirect(url_for('billing.waiting', payment_id=payment.id))

    except Exception as e:
        payment.status = 'failed'
        payment.raw_response = str(e)
        payment.finished_at = datetime.utcnow()
        db.session.commit()
        flash(f'M-Pesa error: {e}')
        return redirect(url_for('billing.pay', tier=tier))


@bp.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    """
    Safaricom POSTs the STK Push result here. Public (no auth).
    Trust comes from matching CheckoutRequestID against a pending Payment.
    """
    data = request.get_json(silent=True) or {}
    stk = data.get('Body', {}).get('stkCallback', {})
    checkout_id = stk.get('CheckoutRequestID')
    result_code = stk.get('ResultCode')

    if not checkout_id:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    payment = Payment.query.filter_by(provider_ref=checkout_id).first()
    if not payment:
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    # Idempotency — already processed
    if payment.status == 'success':
        return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})

    payment.raw_response = json.dumps(data)

    if str(result_code) == '0':
        payment.status = 'success'
        payment.finished_at = datetime.utcnow()
        user = payment.user
        user.plan = payment.plan_tier
        user.subscription_status = 'active'
        db.session.commit()
    else:
        payment.status = 'failed'
        payment.finished_at = datetime.utcnow()
        db.session.commit()

    return jsonify({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@bp.route('/dpo/initiate', methods=['POST'])
@login_required
def dpo_initiate():
    """Create a DPO token and redirect the user to the hosted payment page."""
    tier = request.form.get('tier', '').strip().lower()
    if tier not in PLANS or tier == 'hobby':
        flash('Invalid plan.')
        return redirect(url_for('main.dashboard'))

    price_usd = get_price(tier)

    payment = Payment(
        user_id=current_user.id,
        plan_tier=tier,
        amount_usd=price_usd,
        currency='USD',
        provider='dpo',
        status='pending',
    )
    db.session.add(payment)
    db.session.commit()

    try:
        token = _dpo_create_token(payment.id, tier, price_usd)
        payment.provider_ref = token
        db.session.commit()
        return redirect(f'{_dpo_pay_url()}{token}')

    except Exception as e:
        payment.status = 'failed'
        payment.raw_response = str(e)
        payment.finished_at = datetime.utcnow()
        db.session.commit()
        flash(f'DPO error: {e}')
        return redirect(url_for('billing.pay', tier=tier))


@bp.route('/dpo/callback')
def dpo_callback():
    """
    DPO redirects the user here after payment.
    Always verify server-side with verifyToken — never trust the query string alone.
    """
    token = request.args.get('TransToken') or request.args.get('Token')
    if not token:
        flash('Payment verification failed: missing token.')
        return redirect(url_for('main.dashboard'))

    payment = Payment.query.filter_by(provider_ref=token).first()
    if not payment:
        flash('Payment record not found.')
        return redirect(url_for('main.dashboard'))

    if payment.status == 'success':
        flash('Payment already confirmed.')
        return redirect(url_for('main.dashboard'))

    try:
        result = _dpo_verify_token(token)
        payment.raw_response = json.dumps(result)

        if result['result'] == '000':
            payment.status = 'success'
            payment.finished_at = datetime.utcnow()
            user = payment.user
            user.plan = payment.plan_tier
            user.subscription_status = 'active'
            db.session.commit()
            flash(f'Payment successful! Your {payment.plan_tier.replace("_", " ").title()} plan is now active.')
        else:
            payment.status = 'failed'
            payment.finished_at = datetime.utcnow()
            db.session.commit()
            flash(f'Payment not confirmed: {result.get("explanation", "unknown error")}')

    except Exception as e:
        flash(f'Verification error: {e}')

    return redirect(url_for('main.dashboard'))


@bp.route('/waiting/<int:payment_id>')
@login_required
def waiting(payment_id):
    """Polling page while waiting for M-Pesa PIN entry."""
    payment = Payment.query.filter_by(
        id=payment_id, user_id=current_user.id
    ).first_or_404()
    return render_template('billing/waiting.html', payment=payment)


@bp.route('/status/<int:payment_id>')
@login_required
def status(payment_id):
    """JSON endpoint the waiting page polls."""
    payment = Payment.query.filter_by(
        id=payment_id, user_id=current_user.id
    ).first_or_404()
    return jsonify({'status': payment.status})


@bp.route('/history')
@login_required
def history():
    payments = Payment.query.filter_by(user_id=current_user.id)\
        .order_by(Payment.created_at.desc()).all()
    return render_template('billing/history.html', payments=payments)
