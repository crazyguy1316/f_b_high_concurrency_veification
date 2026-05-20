import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
    stages: [
        { duration: '5s', target: 200 },   // Ramp up to 200 users
        { duration: '10s', target: 1000 }, // Spike to 1000 users (high-concurrency load)
        { duration: '5s', target: 0 },    // Ramp down to 0
    ],
    thresholds: {
        http_req_duration: ['p(95)<500'], // 95% of requests must complete below 500ms
    },
};

export default function () {
    const eventId = 'concert_a';
    const memberId = __VU; // unique VU ID (starts from 1)
    const token = `token_${memberId}`;
    const targetHost = __ENV.TARGET_HOST || 'localhost';
    const url = `http://${targetHost}/api/v1/tickets/${eventId}/reserve`;

    const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
    };

    const rand = Math.random();

    if (rand < 0.80) {
        // --- 80% Valid Ticket Reservation Request ---
        const payload = JSON.stringify({
            member_id: memberId,
            token: token
        });
        const res = http.post(url, payload, { headers: headers });
        
        check(res, {
            'valid request returns 202 or rate-limited/sold-out status': (r) => [202, 503, 403, 401].includes(r.status),
        });
    } 
    else if (rand >= 0.80 && rand < 0.90) {
        // --- 10% Unauthorized Request (401) ---
        const invalidHeaders = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer invalid_token_xyz',
        };
        const payload = JSON.stringify({
            member_id: memberId,
            token: 'invalid_token_xyz'
        });
        const res = http.post(url, payload, { headers: invalidHeaders });

        check(res, {
            'invalid token returns 401': (r) => r.status === 401,
        });
    } 
    else {
        // --- 10% Rate Limiting / High-Frequency Request ---
        const payload = JSON.stringify({
            member_id: memberId,
            token: token
        });
        
        // First request
        http.post(url, payload, { headers: headers });

        // Second request immediately after (triggers Nginx burst limit)
        const res2 = http.post(url, payload, { headers: headers });

        check(res2, {
            'high frequency triggers Nginx 503 or 403 limit': (r) => r.status === 503 || r.status === 403,
        });
    }

    sleep(0.1); // small delay between loops to prevent client socket saturation
}
