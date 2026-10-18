bind = '127.0.0.1:5001'
workers = 2
threads = 2
worker_class = 'gthread'
timeout = 30
accesslog = '-'
errorlog = '-'
# The application, not Gunicorn, handles forwarded headers when explicitly enabled.
forwarded_allow_ips = ''
