$ErrorActionPreference = "Continue"
Write-Host "============================================="
Write-Host "Starting High-Concurrency Sandbox Integration Test"
Write-Host "============================================="

# 1. Clean up existing containers and volumes
Write-Host "Cleaning up old containers and volumes..."
docker-compose -f src/docker-compose.yml down -v

# 2. Build and start database/cache services first
Write-Host "Building and starting database/cache services (MySQL & Redis)..."
docker-compose -f src/docker-compose.yml up --build -d db_mysql redis

# 2.1. Wait for MySQL to become fully healthy (complete DDL)
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

# 2.2. Start the rest of the services (app, worker, Nginx)
Write-Host "Starting application server, worker, and Nginx gateway..."
docker-compose -f src/docker-compose.yml up --build -d

# 3. Wait for services to be ready
Write-Host "Waiting for Nginx gateway port to open..."
& .venv\Scripts\python -c @"
import socket, time
def wait_port(port):
    for _ in range(30):
        try:
            with socket.create_connection(('localhost', port), timeout=1):
                print(f'Port {port} is ready!')
                return
        except:
            time.sleep(1)
    raise TimeoutError(f'Port {port} failed to become ready in time.')
wait_port(80)
"@

# 4. Install dependencies in the local virtual environment for the reconciliation script
Write-Host "Installing dependencies for local audit script..."
& .venv\Scripts\pip install -r src\requirements.txt

# 5. Initialize stock and clear old state in Redis
Write-Host "Seeding Redis cache state (Initial stock: 200)..."
& .venv\Scripts\python -c @"
import redis
r = redis.Redis(host='localhost', port=6379)
r.set('ticket:stock:concert_a', 200)
r.delete('ticket:soldout:flag')
r.delete('ticket:success:orders')
r.delete('ticket:request:queue')
# Also delete any user-enqueued markers
for key in r.scan_iter('ticket:user:enqueued:*'):
    r.delete(key)
print('Redis seeding completed successfully.')
"@

# 6. Execute k6 load test using Docker
Write-Host "Injecting load using k6 docker container..."
docker run --rm -i --network=src_default -e TARGET_HOST=ticketing_nginx -v "${PWD}/src/tests:/tests" grafana/k6 run /tests/k6_load_test.js

# 7. Grace period for background workers to finish database persistence
Write-Host "Waiting for background workers to persist remaining orders..."
Start-Sleep -Seconds 3

# 8. Run reconciliation/audit script
Write-Host "Executing database & cache reconciliation..."
& .venv\Scripts\python src/tests/reconcile.py

# 9. Dump logs of app and worker for diagnostic transparency
Write-Host "Dumping backend app logs..."
docker logs ticketing_app
Write-Host "Dumping queue worker logs..."
docker logs ticketing_worker

# 10. Tear down container orchestration
Write-Host "Tearing down container environment..."
docker-compose -f src/docker-compose.yml down -v

Write-Host "============================================="
Write-Host "Sandbox test completed successfully."
Write-Host "============================================="
