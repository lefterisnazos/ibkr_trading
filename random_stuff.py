def bani_wrapper(func):
    def wrapper(*args, **kwargs):
        print("bani")
        result = func(*args, **kwargs)
        print("bani after")
        return result * 2
    return wrapper

@bani_wrapper
def add(a, b):
    return (a+b)

x= add(1, 2)
y=3