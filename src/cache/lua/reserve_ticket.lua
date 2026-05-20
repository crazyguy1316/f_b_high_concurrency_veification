-- Redis Lua Script: reserve_ticket.lua
-- Atomically verify stock and user purchase state, and deduct stock.

-- Keys and Arguments description:
-- KEYS[1]: Anti-replay key "ticket:user:has_bought:{event_id}:{member_id}"
-- KEYS[2]: Stock key "ticket:stock:{event_id}"
-- KEYS[3]: Success Hash key "ticket:success:orders"
-- ARGV[1]: member_id
-- ARGV[2]: event_id

-- 1. Check for duplicate order
local has_bought = redis.call("EXISTS", KEYS[1])
if has_bought == 1 then
    return "DUPLICATE_ORDER"
end

-- 2. Check stock level
local current_stock = redis.call("GET", KEYS[2])
if not current_stock then
    return "SOLD_OUT"
end

local stock_num = tonumber(current_stock)
if not stock_num or stock_num <= 0 then
    return "SOLD_OUT"
end

-- 3. Atomically decrement stock
redis.call("DECR", KEYS[2])

-- 4. Mark purchase as successful (TTL 24 hours / 86400 seconds)
redis.call("SET", KEYS[1], "1")
redis.call("EXPIRE", KEYS[1], 86400)

-- 5. Record successful order in the success hash mapping
redis.call("HSET", KEYS[3], ARGV[1], ARGV[2])

return "SUCCESS"
