-- Executive revenue dashboard
SELECT day, plan_tier, revenue
FROM main.gold.daily_revenue
WHERE day >= date_sub(current_date(), 30)
ORDER BY day DESC;
