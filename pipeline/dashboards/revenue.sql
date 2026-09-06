-- Executive revenue dashboard
SELECT day, plan_tier, revenue
FROM main.gold.daily_revenue
WHERE day >= current_date() - INTERVAL 30 DAYS
ORDER BY day DESC;
