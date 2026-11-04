from functools import wraps
from flask import redirect, url_for, flash, request, jsonify
from flask_login import current_user


def paid_required(f):
    """
    Decorator to enforce payment gating on premium routes.

    Logic:
      - Hobby users: always pass (apps sleep, that's the trade-off — no payment needed)
      - Paid-plan users with active subscription: always pass
      - Paid-plan users with any other status (pending_payment, inactive, past_due):
          * API routes → 402 Payment Required (JSON)
          * Web routes → redirect to /billing/pay/<tier> with a flash message

    Usage:
        @bp.route('/projects/<int:project_id>/deploy', methods=['POST'])
        @login_required
        @paid_required
        def deploy(project_id):
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user

        # Hobby is free — always allowed
        if user.plan == 'hobby':
            return f(*args, **kwargs)

        # Paid plan with active subscription — allowed
        if user.subscription_status == 'active':
            return f(*args, **kwargs)

        # Paid plan but payment not complete
        if request.path.startswith('/api/'):
            return jsonify({
                'error': 'payment_required',
                'hint': (
                    f'Your {user.plan} plan is pending payment. '
                    f'Complete payment to deploy apps and create databases.'
                ),
                'pay_url': f'/billing/pay/{user.plan}',
            }), 402

        flash(
            f'Your {user.plan.replace("_", " ").title()} plan is pending payment. '
            f'Complete payment to deploy apps and create databases.'
        )
        return redirect(url_for('billing.pay', tier=user.plan))

    return decorated
