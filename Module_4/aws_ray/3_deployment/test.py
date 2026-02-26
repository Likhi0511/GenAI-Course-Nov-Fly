from concurrent.futures import ThreadPoolExecutor
import time

max_concurrent = 10

def print_result(i,name_of_worker):
    print(f"{name_of_worker} {i} called")
    time.sleep(100)
    return f"{name_of_worker} {i} finished"

with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
    future_to_doc = {
        pool.submit(print_result, i,"Worker")
        for i in range(0,20)
    }
    print(future_to_doc)