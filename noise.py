for i in range(1, 3001):
    print(f"INFO worker-{i % 8} processed batch {i} ok")
    if i == 1743:
        print("ERROR db connection refused: host=10.0.0.5 port=5432 (attempt 3/3)")
