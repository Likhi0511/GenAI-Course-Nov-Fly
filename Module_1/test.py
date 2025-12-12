# from datetime import datetime, timedelta
# import random
#
# START_DATE = datetime.now() - timedelta(days=365 * 2)  # two years ago
# END_DATE = datetime.now()
#
# print(START_DATE)
# print(END_DATE)
#
# delta = END_DATE - START_DATE
# print(delta)
# delta_seconds = int(delta.total_seconds())
# sec = random.randrange(delta_seconds)
# print(START_DATE + timedelta(seconds=sec))
#
# i = 20
# print(f"CUST{i:010d}")
import random

ORDER_STATUSES = ["pending", "processing", "shipped", "delivered", "canceled", "returned"]


status = random.choices(
    ORDER_STATUSES,
    weights=[5, 10, 40, 30, 10, 5],  # weighted so most become delivered/shipped
    k=1
)

print(status)