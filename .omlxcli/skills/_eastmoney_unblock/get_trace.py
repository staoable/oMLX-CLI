import random


def __ease_out_expo(sep):
    if sep == 1:
        return 1
    return 1 - pow(2, -10 * sep)


def generate_trace(distance):
    if not isinstance(distance, int) or distance < 0:
        raise ValueError(f"distance must be non-negative int: {distance}")
    slide_track = [[0, 0, 0]]
    count = 30 + int(distance / 2)
    t = random.randint(50, 100)
    last_x = 0
    y = -1
    for i in range(count):
        x = round(__ease_out_expo(i / count) * distance)
        t += random.randint(10, 20)
        if x == last_x:
            continue
        slide_track.append([x, y, t])
        last_x = x
    slide_track.append(slide_track[-1])
    return ":".join(f"{x},{y},{t}" for x, y, t in slide_track)

