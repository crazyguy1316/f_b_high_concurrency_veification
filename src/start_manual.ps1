$ErrorActionPreference = "Stop"

Write-Host "============================================="
Write-Host "Starting Ticketing System for Manual Testing"
Write-Host "============================================="

# Clean up old containers
docker-compose -f src/docker-compose.yml down -v

# Start database and cache
Write-Host "Starting MySQL and Redis..."
docker-compose -f src/docker-compose.yml up --build -d db_mysql redis

# Wait for MySQL to become fully healthy
Write-Host "Waiting for MySQL container to become healthy (executing DDL)..."
& .venv\Scripts\python -c @"
import subprocess, time, json
for i in range(40):
    try:
        out = subprocess.check_output(['docker', 'inspect', '--format={{json .State.Health}}', 'ticketing_mysql'])
        health = json.loads(out.strip().decode('utf-8'))
        if health.get('Status') == 'healthy':
            print('MySQL is healthy and ready!')
            break
    except Exception as e:
        pass
    time.sleep(2)
else:
    raise TimeoutError('MySQL container failed to become healthy.')
"@

# Start the application services
Write-Host "Starting application server, worker, and Nginx gateway..."
docker-compose -f src/docker-compose.yml up --build -d

# Seed the initial data
Write-Host "Seeding Redis cache state (Initial stock: 200)..."
& .venv\Scripts\python -c @"
import redis
r = redis.Redis(host='localhost', port=6379)
r.set('ticket:stock:concert_a', 200)
r.delete('ticket:success:concert_a')
r.delete('ticket:request:queue')
print('Redis seeding completed successfully.')
"@

Write-Host "============================================="
Write-Host "System is ready for manual testing!"
Write-Host "Navigate to http://localhost to access the ticketing gateway."
Write-Host "============================================="
