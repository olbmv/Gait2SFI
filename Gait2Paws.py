# Gait2Paws
# A script for automatic gait visualization and footprint intensity assessment (something like the catwalk method). 
# This code is just an example; feel free to modify it to suit your needs.
# Author: PhD student Oleksandr Bomikhov
# Bogomoletz Institute of Physiology, National Academy of Sciences of Ukraine


import os
import csv
import math
from collections import defaultdict
from math import cos, sin, radians

import cv2
import numpy as np
import matplotlib.pyplot as plt
from skimage import filters, morphology
from skimage.measure import label, regionprops
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from tkinter import filedialog, messagebox


def leading_trailing_on_hull(cnt, vhat=[1, 0]):
    """
    Given a contour and a direction vector vhat,
    find the two extreme points on the convex hull
    along that direction (front and back).

    Parameters
    ----------
    cnt : np.ndarray
        Contour points (OpenCV format).
    vhat : list or np.ndarray
        Direction vector [vx, vy]. Does not need to be normalized.

    Returns
    -------
    front_pt : tuple(float, float)
        Point with maximum projection on vhat.
    back_pt : tuple(float, float)
        Point with minimum projection on vhat.
    """
    hull = cv2.convexHull(cnt, returnPoints=True).reshape(-1, 2).astype(float)
    vhat = np.asarray(vhat, dtype=float)
    proj = hull @ vhat
    front_pt = tuple(hull[np.argmax(proj)])
    back_pt = tuple(hull[np.argmin(proj)])
    return front_pt, back_pt


def merge_close_contours(footprints, dist_thresh=40):
    """
    Merge only nearby contours (e.g., multiple toes of the same paw)
    based on the distance between their centers of mass.

    Parameters
    ----------
    footprints : list of dict
        Each dict must have keys 'cx', 'cy', 'contour'.
    dist_thresh : float
        Max distance (in pixels) between two centers to consider them
        belonging to the same group.

    Returns
    -------
    merged_contours : list of np.ndarray
        Each element is a merged contour (convex hull of grouped points).
    """
    if not footprints:
        return []

    # Collect centers of all footprints
    centers = np.array([[fp["cx"], fp["cy"]] for fp in footprints],
                       dtype=np.float32)

    # Pairwise distance matrix
    dist = np.linalg.norm(
        centers[:, None, :] - centers[None, :, :],
        axis=2
    )

    visited = np.zeros(len(footprints), bool)
    groups = []

    # Simple BFS-based grouping: merge indices that are closer than dist_thresh
    for i in range(len(footprints)):
        if visited[i]:
            continue

        group = [i]
        visited[i] = True
        queue = [i]

        while queue:
            j = queue.pop()
            close_idxs = np.where(dist[j] < dist_thresh)[0]
            for k in close_idxs:
                if not visited[k]:
                    visited[k] = True
                    queue.append(k)
                    group.append(k)
        groups.append(group)

    merged_contours = []
    for g in groups:
        pts = np.vstack([footprints[idx]["contour"] for idx in g])
        hull = cv2.convexHull(pts)
        merged_contours.append(hull)

    return merged_contours


def ResizeWithAspectRatio(image, width=None, height=None,
                          inter=cv2.INTER_AREA):
    """
    Resize an image while preserving the aspect ratio.

    Parameters
    ----------
    image : np.ndarray
        Input image.
    width : int, optional
        Desired width. If None, it will be calculated from height.
    height : int, optional
        Desired height. If None, it will be calculated from width.
    inter : int
        OpenCV interpolation flag.

    Returns
    -------
    resized : np.ndarray
        Resized image.
    """
    (h, w) = image.shape[:2]

    if width is None and height is None:
        return image

    if width is None:
        r = height / float(h)
        dim = (int(w * r), height)
    else:
        r = width / float(w)
        dim = (width, int(h * r))

    return cv2.resize(image, dim, interpolation=inter)


def select_video():
    """
    Open a file dialog to select a video and write its name
    into 'files_log.txt'. The selected path is stored in
    the global variable 'video_path'.
    """
    global video_path

    print("Opening file dialog for video selection...")
    video_path = filedialog.askopenfilename(
        filetypes=[("Video files", "*.mp4 *.avi *.mov")]
    )
    print(f"Video path selected: {video_path}")

    with open('files_log.txt', 'a+', encoding='utf-8') as file:
        file.write(os.path.basename(video_path)+"\r\n")



def detect_red_body_pose(frame_bgr, min_body_area):
    """
    Detect the rat body silhouette (red/bright shape after preprocessing),
    estimate body bounding box, center and approximate head/tail/left/right
    points based on the convex hull.

    Parameters
    ----------
    frame_bgr : np.ndarray
        BGR frame with body silhouette (red still present).
    min_body_area : float
        Minimal contour area to be considered as body.

    Returns
    -------
    body_rect : tuple or None
        (x, y, w, h) bounding box of detected body.
    body_center : tuple or None
        (cx, cy) center of the body.
    body_cnt : np.ndarray or None
        Contour of the body.
    tail, head, left, right : tuple or None
        Approximate tail/head/left/right points on the body contour.
    """
    global last_pose_center

    filtered_image = cv2.medianBlur(frame_bgr, 7)
    gray = cv2.cvtColor(filtered_image, cv2.COLOR_BGR2GRAY)

    # Thresholding to obtain the body region (trunc + Otsu)
    _, mask = cv2.threshold(
        gray, 100, 255,
        cv2.THRESH_TRUNC + cv2.THRESH_OTSU
    )

    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None, None, None, None, None, None, None

    bodies = []

    for cnt in cnts:
        area = cv2.contourArea(cnt)
        if area < min_body_area:
            continue

        M = cv2.moments(cnt)
        if M["m00"] != 0:
            # Use bounding box center instead of centroid
            x, y, w, h = cv2.boundingRect(cnt)
            cx, cy = x + w // 2, y + h // 2
        else:
            x, y, w, h = cv2.boundingRect(cnt)
            cx, cy = x + w // 2, y + h // 2

        bodies.append({
            "cx": cx,
            "cy": cy,
            "area": int(area),
            "contour": cnt,
            "bbox": (int(x), int(y), int(w), int(h)),
        })

    if len(bodies) == 0:
        return None, None, None, None, None, None, None

    # Take the largest body by area
    bodies.sort(key=lambda d: d["area"], reverse=True)
    body = bodies[0]["contour"]

    x, y, w, h = bodies[0]["bbox"]
    cx = bodies[0]["cx"]
    cy = bodies[0]["cy"]

    # Draw debug info on frame
    cv2.drawContours(frame_bgr, [body], -1, (255, 255, 255), 2)
    cv2.rectangle(frame_bgr, (x, y), (x + w, y + h), (255, 255, 255), 1)

    prev_center = np.array(last_pose_center, float)
    cur_center = np.array([cx, cy], float)

    # Movement vector (not strictly needed for current logic but kept)
    v = cur_center - prev_center
    vhat = v / (np.linalg.norm(v) + 1e-8)

    # Approximate orientation using convex hull in fixed axes
    tail, head = leading_trailing_on_hull(body, [-1, 0])   # left-right axis
    left, right = leading_trailing_on_hull(body, [0, 1])   # up-down axis

    cv2.circle(frame_bgr, (int(head[0]), int(head[1])), 8, (255, 34, 155), -1)
    cv2.putText(frame_bgr, "HEAD",
                (int(head[0]) + 8, int(head[1]) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    cv2.circle(frame_bgr, (int(tail[0]), int(tail[1])), 8, (20, 255, 55), -1)
    cv2.putText(frame_bgr, "TAIL",
                (int(tail[0]) + 8, int(tail[1]) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    cv2.circle(frame_bgr, (int(right[0]), int(right[1])), 8,
               (100, 140, 250), -1)
    cv2.putText(frame_bgr, "RIGHT",
                (int(right[0]) + 8, int(right[1]) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    cv2.circle(frame_bgr, (int(left[0]), int(left[1])), 8,
               (255, 146, 125), -1)
    cv2.putText(frame_bgr, "LEFT",
                (int(left[0]) + 8, int(left[1]) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    cv2.circle(frame_bgr, (cx, cy), 8, (0, 0, 255), -1)
    cv2.putText(frame_bgr, "CENTER",
                (cx + 5, cy + 5),
                cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)

    return (x, y, w, h), (cx, cy), body, tail, head, left, right


def detect_green_footprints(frame_bgr,
                            min_area=200,
                            max_area=None,
                            hsv_range=((35, 60, 40), (85, 255, 255)),
                            # green in OpenCV HSV (H:0–179)
                            lab_a_thresh=135,           # lower 'a' => more green
                            k_open=3,
                            k_close=7,
                            draw=True,
                            body_center=None,
                            time_ms=0,
                            tail=None,
                            head=None,
                            left=None,
                            right=None,
                            body_rect=None):
    """
    Detect green paw prints on the frame and return per-print descriptors.

    Parameters
    ----------
    frame_bgr : np.ndarray
        Input frame with green footprints visible.
    min_area : int
        Minimal contour area (px) for a footprint (noise removal).
    max_area : int or None
        Maximal contour area; if None, no upper limit is applied.
    hsv_range : ((Hmin,Smin,Vmin),(Hmax,Smax,Vmax))
        HSV range for initial green segmentation.
    lab_a_thresh : int
        Threshold on Lab 'a' channel (lower values correspond to greener pixels).
    k_open, k_close : int
        Kernel sizes for morphological opening/closing.
    draw : bool
        If True, will draw annotation and detect paw side.
    body_center, time_ms, tail, head, left, right, body_rect :
        Additional context used to classify paw (Front/Back, Left/Right).

    Returns
    -------
    footprints : list of dict
        Each dict contains 'cx', 'cy', 'area', 'contour', 'bbox', 'angle'.
    mask : np.ndarray
        Binary mask (0/255) of green footprints.
    vis : np.ndarray or None
        Annotated image if draw=True, otherwise None.
    """
    img = frame_bgr.copy()

    # 1) Color segmentation in HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hmin, smin, vmin = hsv_range[0]
    hmax, smax, vmax = hsv_range[1]
    mask_hsv = cv2.inRange(hsv, (hmin, smin, vmin), (hmax, smax, vmax))

    # 2) Additional filter in Lab (channel 'a' is lower for green)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2Lab)
    a = lab[:, :, 1]  # 0..255, green-ish < ~135–140
    _, mask_lab = cv2.threshold(
        a, lab_a_thresh, 255, cv2.THRESH_BINARY_INV
    )

    # Combine (AND) – keep robust green pixels
    mask = cv2.bitwise_and(mask_hsv, mask_lab)

    # 3) Clean up the mask
    mask = cv2.medianBlur(mask, 3)
    k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_open, k_open))
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_close, k_close))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k1, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k2, iterations=1)

    # 4) Find contours
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    footprints = []
    H, W = img.shape[:2]
    if max_area is None:
        max_area = H * W

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue

        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            x, y, w, h = cv2.boundingRect(cnt)
            cx, cy = x + w // 2, y + h // 2

        x, y, w, h = cv2.boundingRect(cnt)

        angle = None
        if len(cnt) >= 5:
            try:
                (ex, ey), (MA, ma), ang = cv2.fitEllipse(cnt)
                angle = float(ang)
            except cv2.error:
                angle = None

        footprints.append({
            "cx": cx,
            "cy": cy,
            "area": float(area),
            "contour": cnt,
            "bbox": (int(x), int(y), int(w), int(h)),
            "angle": angle
        })

    # Sort footprints by area (largest first)
    footprints.sort(key=lambda d: d["area"], reverse=True)

    global last_paw, Paws, counter, second_scr

    img_crop = None
    vis = None

    if draw:
        vis = img.copy()
        for i, fp in enumerate(footprints, 1):
            if i != 1:
                continue

            # Merge nearby contours (all toes of one paw)
            merged = merge_close_contours(footprints, dist_thresh=80)
            largest = max(merged, key=cv2.contourArea)

            x_, y_, w_, h_ = cv2.boundingRect(largest)
            img_crop = vis[y_:y_ + h_, x_:x_ + w_].copy()

            roi = vis[y_:y_ + h_, x_:x_ + w_]

            # Count green pixels in ROI
            hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            mask_green = cv2.inRange(
                hsv_roi, (35, 40, 40), (90, 255, 255)
            )
            green_pixels = cv2.countNonZero(mask_green)

            out_name = f"{counter:03d}.png"
            out_path = os.path.join("imgs", out_name)

            cv2.putText(roi, str(green_pixels),
                        (10, 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.3, (0, 255, 255), 1)

            # Enhance green channel for visualization
            b, g, r = cv2.split(roi)
            roi = cv2.merge([b, g + 100, r])

            # Detect dark blue sub-region (pressure area)
            hsv_roi2 = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            lower_dark_blue = np.array([100, 150, 0], dtype=np.uint8)
            upper_dark_blue = np.array([130, 255, 120], dtype=np.uint8)
            blue_mask = cv2.inRange(hsv_roi2, lower_dark_blue,
                                    upper_dark_blue)
            blue_pixels = cv2.countNonZero(blue_mask)

            cx_ = x_ + w_ // 2
            cy_ = y_ + h_ // 2

            second_scr[y_:y_ + h_, x_:x_ + w_] = roi
            
            #Write paws to images, if you want
            
            #cv2.imwrite(out_path, roi) 

            # Determine which paw (Front/Back, Left/Right)
            x_body, y_body, w_body, h_body = body_rect
            x_center = body_center[0]
            y_center = body_center[1]

            if int(tail[0]) < cx_ < x_center:
                # Paw is between tail and body center => back paws
                if cy_ > int(head[1]) or cy_ > y_center:
                    lr = "Back_Left"
                else:
                    lr = "Back_Right"
            else:
                # Paw is in front of body center => front paws
                if cy_ > int(head[1]) or cy_ > y_center:
                    lr = "Front_Left"
                else:
                    lr = "Front_Right"

            last_paw = lr

            cv2.putText(second_scr, str(lr),
                        (x_ + w_, y_ + h_),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        1.4, (255, 255, 255), 3)

            Paws.append({
                "paw": img_crop,
                "left_or_right": str(last_paw),
                "green_pixels": int(green_pixels),
                "blue_pixels": int(blue_pixels),
                "metric": blue_pixels / green_pixels,
                "step": counter,
                "time": int(time_ms)
            })

            counter += 1
            break

    return footprints, mask, vis



def export_paw_metrics(Paws,
                       video_path="paw_metrics.mp4",
                       image_path="paw_metrics.png",
                       fps=25,
                       width=800,
                       height=600,
                       smooth_window=5):
    """
    Build a smoothed line plot of metric vs step for each paw and
    export it as an animation (video) and as a final PNG image.

    X-axis: 'step'
    Y-axis: 'metric' = blue_pixels / green_pixels
    Only back paws are plotted (Back_Left, Back_Right).

    Parameters
    ----------
    Paws : list of dict
        Each element has keys:
        'left_or_right', 'metric', 'step', 'time', etc.
    video_path : str
        Output path for the animated plot (MP4).
    image_path : str
        Output path for the final static plot (PNG).
    fps : int
        Frames per second for the output video.
    width, height : int
        Size of the output video frames.
    smooth_window : int
        Window size for moving-average smoothing.
    """
    if not Paws:
        print("Paws list is empty, nothing to plot.")
        return

    # Group by paw name using step as X value
    def build_paw_traces(paws_list):
        by_paw_local = defaultdict(list)
        for p in paws_list:
            paw_name = p["left_or_right"]
            step = int(p["step"])         # X = step index
            m = float(p["metric"])        # Y = metric
            by_paw_local[paw_name].append((step, m))

        for paw in by_paw_local:
            by_paw_local[paw].sort(key=lambda x: x[0])

        return by_paw_local

    def smooth_series(values, window):
        values = np.asarray(values, dtype=float)
        n = len(values)
        if n == 0 or window <= 1:
            return values
        if window > n:
            window = n
        kernel = np.ones(window, dtype=float) / window
        return np.convolve(values, kernel, mode="same")

    def draw_metric_plot(by_paw_local, step_limit=None):
        fig = plt.figure(figsize=(8, 5))
        ax = fig.add_subplot(111)

        # Only back paws are drawn; front paws can be added if needed
        paw_order = ["Back_Left", "Back_Right"]

        for paw_name in paw_order:
            if paw_name not in by_paw_local:
                continue

            data = by_paw_local[paw_name]
            steps = [s for s, m in data if (step_limit is None or s <= step_limit)]
            metrics = [m for s, m in data if (step_limit is None or s <= step_limit)]

            if not steps:
                continue

            smoothed = smooth_series(metrics, smooth_window)
            ax.plot(steps, smoothed, linewidth=2.0, label=paw_name)

        ax.set_xlabel("Step index")
        ax.set_ylabel("metric = blue/green")
        ax.set_title("Paw contact metric over steps")
        ax.grid(True, linestyle="--", alpha=0.3)
        ax.legend(loc="center left", bbox_to_anchor=(1, 0.5))

        fig.tight_layout()
        return fig

    by_paw = build_paw_traces(Paws)
    all_steps = sorted(set([int(p["step"]) for p in Paws]))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_path, fourcc, fps, (width, height))

    for s_current in all_steps:
        fig = draw_metric_plot(by_paw, step_limit=s_current)
        canvas = FigureCanvas(fig)
        canvas.draw()

        img_rgba = np.asarray(canvas.buffer_rgba())
        img_rgb = img_rgba[:, :, :3]
        plt.close(fig)

        frame = cv2.resize(img_rgb, (width, height))
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        writer.write(frame)

    writer.release()

    # Final static image
    final_fig = draw_metric_plot(by_paw, step_limit=None)
    final_canvas = FigureCanvas(final_fig)
    final_canvas.draw()

    final_rgba = np.asarray(final_canvas.buffer_rgba())
    final_rgb = final_rgba[:, :, :3]
    plt.close(final_fig)

    final_img_bgr = cv2.cvtColor(final_rgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(image_path, final_img_bgr)

    print(f"Metric plot video saved to: {video_path}")
    print(f"Final metric plot PNG saved to: {image_path}")


# -------------------- MAIN VIDEO PROCESSING LOOP --------------------

video_path = None
select_video()

cap = cv2.VideoCapture(video_path)
if not cap.isOpened():
    print("Failed to open video!")
    exit()

# Get video parameters
frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = int(cap.get(cv2.CAP_PROP_FPS))

current_frame = 0
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
ret, frame = cap.read()
if not ret:
    print("Could not read the first frame.")
    cap.release()
    exit()

# Scale frame down if width > 1000 px (for ROI selection)
scale_factor = min(1.0, 1000 / frame_width)
resized_frame = cv2.resize(
    frame,
    (int(frame_width * scale_factor),
     int(frame_height * scale_factor))
)

# Manual ROI selection on downscaled frame
roi_resized = cv2.selectROI(
    "Select a workspace",
    resized_frame,
    fromCenter=False,
    showCrosshair=True
)
cv2.destroyWindow("Select a workspace")

# Map ROI coordinates back to original resolution
x, y, w, h = [int(coord / scale_factor) for coord in roi_resized]

# Background subtractor for movement detection
background_subtractor = cv2.createBackgroundSubtractorMOG2(
    history=500,
    varThreshold=50,
    detectShadows=False
)

# Video writer for debug output (4 stacked views)
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(
    'rat_walks_output.mp4',
    fourcc,
    fps,
    (w, h * 4)
)


last_paw = ""
Paws = []
counter = 1
last_pose_center = [1, 1]
second_scr = None

# Main frame processing loop
while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    roi_frame = frame[y:y + h, x:x + w]
    time_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

    # Background subtraction (movement only)
    fg_mask = background_subtractor.apply(roi_frame)
    kernel = np.ones((5, 5), np.uint8)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
    fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
    _, fg_mask = cv2.threshold(fg_mask, 200, 255, cv2.THRESH_BINARY)

    # Keep only moving green objects
    final_result = np.zeros_like(roi_frame)
    final_result[fg_mask > 0] = roi_frame[fg_mask > 0]
    final_result[:, :, 2] = 0  # remove red channel from result

    copy_for_mask = final_result.copy()

    # Detect body pose on the filtered frame
    body_rect, body_center, body_cnt, tail, head, left, right = \
        detect_red_body_pose(copy_for_mask, min_body_area=50000)

    if body_center is None:
        continue

    last_pose_center = body_center

    second_scr = np.zeros_like(roi_frame)

    # Detect green pawprints and classify paw
    footprints, mask, vis = detect_green_footprints(
        final_result,
        min_area=5,
        hsv_range=((30, 40, 25), (90, 255, 255)),
        lab_a_thresh=135,
        k_open=3,
        k_close=6,
        draw=True,
        body_center=body_center,
        time_ms=time_ms,
        tail=tail,
        head=head,
        left=left,
        right=right,
        body_rect=body_rect
    )

    font = cv2.FONT_HERSHEY_DUPLEX
    cv2.putText(
        roi_frame,
        'ORIGINAL Frame: ' +
        str(cap.get(cv2.CAP_PROP_POS_FRAMES)) +
        " Time:" + str(int(time_ms)),
        (50, 100),
        font,
        1.5,
        (0, 255, 255),
        4
    )
    cv2.putText(
        final_result,
        'WITHOUT RED + ONLY MOVEMENT',
        (50, 100),
        font,
        1.5,
        (0, 255, 255),
        4
    )
    cv2.putText(
        second_scr,
        'PAWS',
        (50, 100),
        font,
        1.5,
        (0, 255, 0),
        4
    )
    cv2.putText(
        copy_for_mask,
        'DETAILS',
        (50, 100),
        font,
        1.5,
        (0, 255, 0),
        4
    )

    stacked = np.vstack((roi_frame, final_result, second_scr, copy_for_mask))
    out.write(stacked)

    vis_resized = ResizeWithAspectRatio(stacked, width=1280)
    cv2.imshow(
        "Gait2Paws. Obtaining animal tracks",
        vis_resized if vis_resized is not None else final_result
    )

    key = cv2.waitKey(10) & 0xFF
    if key == 27:  # ESC
        break

cap.release()
out.release()
cv2.destroyAllWindows()

# After processing all frames, export metric plot based on Paws list
export_paw_metrics(
    Paws,
    video_path="paw_metrics_video.mp4",
    image_path="paw_metrics_final.png",
    fps=25,
    width=1080,
    height=800
)



