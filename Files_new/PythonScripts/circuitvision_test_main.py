"""
image_tests.py
Standalone utilities for three vision tests on a supplied frame.
Call `image_test(...)` with the desired arguments.

Example
-------
>>> from image_tests import image_test
>>> ok = image_test(use_image=True, image_path='captured_image6.jpg',
...                 test='test3', debug=True)
>>> print("PASS" if ok else "FAIL")
"""

import cv2
import numpy as np
import sys
import os


# Global debug flag (over‑written by `image_test`)
DEBUG: bool = False


# ─── Internal display helper ────────────────────────────────────────────────────
def _show(title: str, img):
    """Show an image only when DEBUG is True."""
    if DEBUG:
        cv2.imshow(title, img)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


# ─── Image Acquisition ──────────────────────────────────────────────────────────
def capture_image(camera_index: int = 1):
    cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise IOError(f"Cannot open camera #{camera_index}")
    for _ in range(5):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise IOError("Failed to capture image")
    return frame


def load_image(path: str):
    img = cv2.imread(path)
    if img is None:
        raise IOError(f"Cannot load image at '{path}'")
    return img


# ─── Low‑level Helpers ──────────────────────────────────────────────────────────
def find_white_pixel(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, bin_ = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    h, w = bin_.shape
    for x in range(w):
        for y in range(h):
            if bin_[y, x] > 150:
                return (x, y)
    raise ValueError("White pixel not found")


def crop_to_rect(img, tl, br):
    x1, y1 = tl
    x2, y2 = br
    return img[y1:y2, x1:x2]


def rotate_90(img):
    return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)


def enhance_contrast(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return np.array(255 * (enhanced / 255) ** 3.0, dtype="uint8")


def get_three_regions(img):
    """Return (top, bottom‑left, bottom‑right) regions after 180° rotation."""
    h, w = img.shape[:2]
    mid_h, mid_w = h // 2, w // 2
    top = img[0 : mid_h - 15, 15 : w - 15]
    bottom_left = img[mid_h - 10 : h, 0 : mid_w - 5]
    bottom_right = img[mid_h : h - 15, mid_w + 10 : w - 5]
    return top, bottom_left, bottom_right


def get_three_regions_with_offsets(img):
    """As above, but also return (y0,x0) offsets and labels for each region."""
    h, w = img.shape[:2]
    mid_h, mid_w = h // 2, w // 2

    # y‑ranges
    top_y0, top_y1 = 0, mid_h - 15
    bl_y0, bl_y1 = mid_h - 10, h-20
    br_y0, br_y1 = mid_h, h - 15

    # x‑ranges
    top_x0, top_x1 = 15, w - 15
    bl_x0, bl_x1 = 0, mid_w - 5
    br_x0, br_x1 = mid_w + 10, w - 5

    return [
        (img[top_y0:top_y1, top_x0:top_x1], (top_y0, top_x0), "coin battery"),
        (img[bl_y0:bl_y1, bl_x0:bl_x1], (bl_y0, bl_x0), "black switch"),
        (img[br_y0:br_y1, br_x0:br_x1], (br_y0, br_x0), "tiny LED"),
    ]


def increase_contrast(gray: np.ndarray) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=5.0, tileGridSize=(5, 5))

    #sharpen
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])  
    gray = cv2.filter2D(gray, -1, kernel) 
    
    return clahe.apply(255 - gray)

def test_1(img, mn, mx, sigma: float = 15.0):
    gray      = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # norm_gray = _retinex(gray, sigma=sigma)    
    contrast = increase_contrast(gray)
    #regions   = get_three_regions(norm_gray)
    regions   = get_three_regions(contrast)


    ok = True
    for i, region in enumerate(regions, 1):
        _show(f"Test1Region{i}", region)

        mean_val = float(np.mean(region))
        print(f"[Test1‑R] R{i} mean={mean_val:.1f} (expect {mn[i-1]}–{mx[i-1]})")
        if not (mn[i - 1] <= mean_val <= mx[i - 1]):
            ok = False
    return ok



# ─── Test 2 ─────────────────────────────────────────────────────────────────────
def test2(img):
    annotated = img.copy()
    specs = get_three_regions_with_offsets(img)
    passes = []

    for region, (y0, x0), name in specs:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
        clean = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel, iterations=1)

        _show(f"{name} raw mask", mask)
        _show(f"{name} cleaned mask", clean)

        contours, _ = cv2.findContours(clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        valid = 0
        for c in contours:
            if cv2.contourArea(c) < 50:
                continue
            x, y, w_box, h_box = cv2.boundingRect(c)
            cv2.rectangle(
                annotated,
                (x0 + x, y0 + y),
                (x0 + x + w_box, y0 + y + h_box),
                (0, 255, 0),
                2,
            )
            valid += 1

        print(f"[Test2] {name:12s} → {valid} component(s)")
        passes.append(valid >= 1)

    _show("Detected Components", annotated)
    return all(passes)


# ─── Test 3 ─────────────────────────────────────────────────────────────────────
def test3(img, thresh: float = 0.18):
    """
    Edge‑density continuity test.
    1) Crop ROI.
    2) Grayscale → CLAHE → GaussianBlur.
    3) Canny → edge density.
    PASS if density ≥ `thresh`.
    """
    h, w = img.shape[:2]
    roi = img[5 : h - 20, 5 : w - 5]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(10, 10))
    eq = clahe.apply(gray)

    _show("Equalized", eq)

    blur = cv2.GaussianBlur(eq, (5, 5), 0)
    _show("Blurred", blur)

    edges = cv2.Canny(blur, 50, 100)
    _show("Edges", edges)

    density = np.count_nonzero(edges) / edges.size
    print(f"[Test3] edge density = {density:.2%} (threshold = {thresh:.2%})")
    return density >= thresh

def image_test(
    *,
    use_image: bool = True,
    image_path: str = "captured_image.jpg",
    cam_idx: int = 1,
    test: str = "test3",
    debug: bool = False,
):
  
    global DEBUG
    DEBUG = bool(debug)

    frame = load_image(image_path) if use_image else capture_image(cam_idx)

    # Fixed crop + rotation identical to original script
    cr = crop_to_rect(frame, (150, 100), (400, 300))
    tl = find_white_pixel(cr)
    br = (tl[0] + 100, tl[1] + 65)
    roi = crop_to_rect(cr, tl, br)
    roi = rotate_90(roi)

    # #DEBUG: for simulating other times of the day 
    # # safe intensity‑scaling helpers
    # darker = cv2.convertScaleAbs(roi, alpha=0.6)          # α·I, returns uint8
    # # or, with NumPy
    # darker = (roi * 1.2).clip(0, 255).astype(np.uint8)
    # roi = darker
    best_vals = [67.9, 70.6, 74.1] #calibration for test
    allowance = 7
    mn = [best_vals[i]-allowance for i in range(len(best_vals))]
    mx = [best_vals[i]+allowance for i in range(len(best_vals))]
    if test == "test1":
        return test_1(roi, mn, mx)
    #thresholds depend on time of day and environment
    if test == "test2":
        return test2(roi)
    if test == "test3":
        return test3(roi)
    raise ValueError(f"Unknown test '{test}'. Choose 'test1', 'test2', or 'test3'.")

#THIS IS WHAT U CALL
# ─── Public Entry Point ─────────────────────────────────────────────────────────
def run_image_test(test_torun):
    '''
    for automation
    '''
    score = 0
    passes = 5
    passed = True 

    for i in range(passes):
        print(f"trial {i}")
        result = image_test(use_image=False,
                            image_path="_",
                            test=test_torun,
                            debug=False)
        if result:         # Test passed, no error
            print(f"Test {i} passed!") 
        else:
            print(f"Test {i} failed")
            
        passed = False

        if result:
            score += 1
        
    if score > (passes/2):         # Test passed, no error
        print(f"Test passed, score {score}!") 
        passed = True
    else:
        print(f"Test failed, score {score}")
        passed = False

    return passed
    # return True #for debugging purposes


if __name__ == "__main__":
    pass
    # run_image_test('test2')
  