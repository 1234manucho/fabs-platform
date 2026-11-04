PLANS = {
    'hobby': {
        'name': 'Hobby',
        'price_usd': 0,
        'memory_mb': 256,
        'cpu_cores': 0.25,
        'sleep_after_minutes': 5,
        'max_databases': 0,
        'description': 'Free demo. Apps sleep after 5 minutes.',
        'features': [
            'Unlimited projects',
            'Auto-deploy from GitHub',
            'Free SSL',
            'Live logs',
            'Apps sleep after 5 minutes',
        ],
    },
    'basic': {
        'name': 'Basic',
        'price_usd': 25,
        'memory_mb': 512,
        'cpu_cores': 0.5,
        'sleep_after_minutes': 0,
        'max_databases': 1,
        'description': 'For small production applications.',
        'features': [
            'No sleeping',
            '1 managed PostgreSQL database',
            'Environment variables',
            'Priority email support',
        ],
    },
    'pro': {
        'name': 'Pro',
        'price_usd': 50,
        'memory_mb': 1024,
        'cpu_cores': 1.0,
        'sleep_after_minutes': 0,
        'max_databases': 3,
        'description': 'For growing apps and small teams.',
        'features': [
            '3 managed PostgreSQL databases',
            'Custom domains per project',
            'Priority support',
        ],
    },
    'pro_plus': {
        'name': 'Pro Plus',
        'price_usd': 75,
        'memory_mb': 2048,
        'cpu_cores': 2.0,
        'sleep_after_minutes': 0,
        'max_databases': 5,
        'description': 'For high-traffic apps.',
        'features': [
            '5 managed PostgreSQL databases',
            '2 vCPU per project',
            'Priority support',
        ],
    },
    'ultimate': {
        'name': 'Ultimate',
        'price_usd': 100,
        'memory_mb': 4096,
        'cpu_cores': 4.0,
        'sleep_after_minutes': 0,
        'max_databases': 10,
        'description': 'Full power, dedicated support.',
        'features': [
            '10 managed PostgreSQL databases',
            '4 vCPU per project',
            'Named support engineer',
        ],
    },
}

PAID_TIERS = ('basic', 'pro', 'pro_plus', 'ultimate')
ALL_TIERS = list(PLANS.keys())


def get_plan(tier):
    return PLANS.get(tier, PLANS['hobby'])


def get_price(tier):
    return PLANS.get(tier, {}).get('price_usd', 0)
