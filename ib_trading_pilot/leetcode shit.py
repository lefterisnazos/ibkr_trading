import pandas as pd


def run():
    gas = [5, 5, 2, 1, 7, 11, 23, 1]
    cost = [3, 3, 5, 3, 3, 5, 1, 2]
    tank = 0
    for i in range(0, len(gas)):
        tank = gas[i] + tank - cost[i]
        if tank <=0:
            return -1

    return None

run()