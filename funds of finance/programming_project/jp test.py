from typing import List


def hIndex(citations: List[int]):
    citations.sort(reverse=True)

    n = len(citations)
    citations.sort()

    for i, v in enumerate(citations):
        y = n-1
        if n - i <= v:
            return n - i
    return 0

citations =[0,1,5,3,4,7]
f=hIndex(citations)
print(f)
