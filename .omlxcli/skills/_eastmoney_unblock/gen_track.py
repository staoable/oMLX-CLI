import json
import os
import sys

import cv2
import numpy as np
import requests
from PIL import Image

from get_trace import generate_trace


def _pic_download(url, kind):
    save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
    os.makedirs(save_dir, exist_ok=True)
    img_path = os.path.join(save_dir, f"{kind}.jpg")
    img_data = requests.get(url, timeout=10).content
    with open(img_path, "wb") as f:
        f.write(img_data)
    return img_path


def merge_img(url, kind):
    merge_array = [
        {"left": 157, "top": 0}, {"left": 145, "top": 0}, {"left": 265, "top": 0}, {"left": 277, "top": 0},
        {"left": 181, "top": 0}, {"left": 169, "top": 0}, {"left": 241, "top": 0}, {"left": 253, "top": 0},
        {"left": 109, "top": 0}, {"left": 97, "top": 0}, {"left": 289, "top": 0}, {"left": 301, "top": 0},
        {"left": 85, "top": 0}, {"left": 73, "top": 0}, {"left": 25, "top": 0}, {"left": 37, "top": 0},
        {"left": 13, "top": 0}, {"left": 1, "top": 0}, {"left": 121, "top": 0}, {"left": 133, "top": 0},
        {"left": 61, "top": 0}, {"left": 49, "top": 0}, {"left": 217, "top": 0}, {"left": 229, "top": 0},
        {"left": 205, "top": 0}, {"left": 193, "top": 0}, {"left": 145, "top": 80}, {"left": 157, "top": 80},
        {"left": 277, "top": 80}, {"left": 265, "top": 80}, {"left": 169, "top": 80}, {"left": 181, "top": 80},
        {"left": 253, "top": 80}, {"left": 241, "top": 80}, {"left": 97, "top": 80}, {"left": 109, "top": 80},
        {"left": 301, "top": 80}, {"left": 289, "top": 80}, {"left": 73, "top": 80}, {"left": 85, "top": 80},
        {"left": 37, "top": 80}, {"left": 25, "top": 80}, {"left": 1, "top": 80}, {"left": 13, "top": 80},
        {"left": 133, "top": 80}, {"left": 121, "top": 80}, {"left": 49, "top": 80}, {"left": 61, "top": 80},
        {"left": 229, "top": 80}, {"left": 217, "top": 80}, {"left": 193, "top": 80}, {"left": 205, "top": 80},
    ]
    captcha_path = _pic_download(url, kind)
    captcha = Image.open(captcha_path)
    new_captcha = Image.new("RGB", (260, 160))
    upper_list = merge_array[:26]
    lower_list = merge_array[26:]
    for index, location in enumerate(upper_list):
        imgcrop = captcha.crop((location["left"], location["top"], location["left"] + 10, location["top"] + 80))
        new_captcha.paste(imgcrop, (index * 10, 0))
    for index, location in enumerate(lower_list):
        imgcrop = captcha.crop((location["left"], location["top"], location["left"] + 10, location["top"] + 80))
        new_captcha.paste(imgcrop, (index * 10, 80))
    new_captcha.save(captcha_path)
    return captcha_path


def get_distance(captcha_url, slider_url):
    save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
    os.makedirs(save_path, exist_ok=True)
    captcha_path = merge_img(captcha_url, "slide_full")
    slider_path = _pic_download(slider_url, "slide_gap")
    with open(slider_path, "rb") as f:
        target_bytes = f.read()
    with open(captcha_path, "rb") as f:
        background_bytes = f.read()
    slice_image = np.asarray(bytearray(target_bytes), dtype=np.uint8)
    slice_image = cv2.imdecode(slice_image, 1)
    slice_image = cv2.Canny(slice_image, 255, 255)
    bg_image = np.asarray(bytearray(background_bytes), dtype=np.uint8)
    bg_image = cv2.imdecode(bg_image, 1)
    bg_image = cv2.pyrMeanShiftFiltering(bg_image, 5, 50)
    bg_image = cv2.Canny(bg_image, 255, 255)
    result = cv2.matchTemplate(bg_image, slice_image, cv2.TM_CCOEFF_NORMED)
    _, _, _, max_loc = cv2.minMaxLoc(result)
    return max_loc[0]


def main():
    try:
        if len(sys.argv) != 3:
            print(json.dumps({"success": False, "error": "Usage: python gen_track.py <captcha_url> <slider_url>"}))
            return
        captcha_url = sys.argv[1]
        slider_url = sys.argv[2]
        distance = get_distance(captcha_url, slider_url)
        trace = generate_trace(distance)
        print(json.dumps({"success": True, "distance": distance, "trace": trace, "error": None}))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"success": False, "error": str(e), "distance": None, "trace": None}))


if __name__ == "__main__":
    main()

