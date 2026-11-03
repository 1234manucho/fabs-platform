import os
from redis import Redis
from rq import Worker, Connection

if __name__ == '__main__':
    conn = Redis.from_url(os.getenv('REDIS_URL'))
    with Connection(conn):
        Worker(['default']).work()