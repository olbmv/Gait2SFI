# Gait2Paws
# Automatic gait analysis for an fTIR walkway: detects the animal body, finds
# every paw contact, labels it Front/Back x Left/Right and groups the per-frame
# detections into individual steps.
#
# Author: PhD student Oleksandr Bomikhov
# Bogomoletz Institute of Physiology, National Academy of Sciences of Ukraine
#
# Usage:
#   python Gait2Paws.py                        - pick a video in a dialog
#   python Gait2Paws.py video.mp4              - process that file
#   python Gait2Paws.py video.mp4 --no-display - batch mode, no windows
#   python Gait2Paws.py video.mp4 --roi 100,200,1500,900
#   python Gait2Paws.py --help                 - all options

import os
import csv
import sys
import argparse
from collections import deque

import cv2
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from tkinter import filedialog, messagebox


# ======================================================================
#  Colour segmentation - the same approach used in Gait2SFI
# ======================================================================
#
# The walkway is lit so that the body glows red and the paw contacts glow
# green. A plain HSV window cannot separate them reliably: a saturated red
# highlight and a dim green print can land in overlapping HSV cells.
#
# Channel dominance does separate them. "How much does green beat the
# strongest of the other two channels" is unaffected by overall brightness
# and actively rejects red, which is exactly the interference here.

def channel_dominance(bgr, channel=1):
    """
    C - max(other two channels), saturating, in uint8.

    cv2.subtract saturates at 0, so this is exactly clip(C - max(...), 0, 255)
    without ever converting the frame to float32. On a 4K frame the float
    version allocated ~100 MB per call and dominated the runtime.
    """
    planes = cv2.split(bgr)
    others = [planes[i] for i in range(3) if i != channel]
    return cv2.subtract(planes[channel], cv2.max(others[0], others[1]))


def dominance_mask(bgr, channel=1, min_dominance=30, min_value=70, blur=3):
    """
    Generic channel-dominance segmentation.

        dominance = C - max(other two channels)

    Two absolute thresholds are applied:
      min_dominance : how far the channel must beat the others (rejects the
                      opposite colour and grey/white highlights)
      min_value     : minimum brightness of the channel itself (rejects dim
                      sensor noise)

    Absolute thresholds are deliberate. Normalising by the per-frame maximum
    makes an empty frame amplify its own noise up to "full scale", so noise
    in a frame with no contacts would look identical to a real print.

    Returns (dominance_float_0_1, mask_uint8_0_255).
    """
    dom = channel_dominance(bgr, channel)
    target = bgr[:, :, channel]

    if blur and blur >= 3:
        dom = cv2.GaussianBlur(dom, (blur, blur), 0)
        target = cv2.GaussianBlur(target, (blur, blur), 0)

    _, m1 = cv2.threshold(dom, min_dominance, 255, cv2.THRESH_BINARY)
    _, m2 = cv2.threshold(target, min_value, 255, cv2.THRESH_BINARY)
    return dom, cv2.bitwise_and(m1, m2)


def greenness_mask(bgr, min_dominance=30, min_value=70, blur=3, background=None):
    """
    Paw contacts: green dominance over red and blue.

    When a background model is supplied, only green that is NEW relative to
    the static scene counts. That removes fixed bright edges which otherwise
    pass the colour test and appear as a row of phantom paws in every frame.
    """
    if background is None:
        return dominance_mask(bgr, 1, min_dominance, min_value, blur)

    dom = cv2.subtract(green_dominance(bgr), background.gdom)
    green = bgr[:, :, 1]
    if blur and blur >= 3:
        dom = cv2.GaussianBlur(dom, (blur, blur), 0)
        green = cv2.GaussianBlur(green, (blur, blur), 0)

    _, m1 = cv2.threshold(dom, min_dominance, 255, cv2.THRESH_BINARY)
    _, m2 = cv2.threshold(green, min_value, 255, cv2.THRESH_BINARY)
    return dom, cv2.bitwise_and(m1, m2)


def redness_mask(bgr, min_dominance=25, min_value=60, blur=5):
    """Body silhouette: red dominance over green and blue."""
    return dominance_mask(bgr, 2, min_dominance, min_value, blur)


def clean_up(mask, k=3, min_area=20):
    """Opening removes speckle, closing fills holes, then small blobs are dropped."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    n, lbl, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n <= 1:
        return np.zeros_like(mask)

    # Table lookup in one pass. Testing "lbl == i" per component walks all
    # 8.3 M pixels of a 4K frame once per blob, which dominated the runtime.
    keep = (stats[:, cv2.CC_STAT_AREA] >= min_area)
    keep[0] = False                      # label 0 is the background
    return np.where(keep[lbl], 255, 0).astype(np.uint8)


# ======================================================================
#  Static-scene background model
# ======================================================================
#
# Two artefacts on this rig cannot be removed by colour alone:
#
#   * the walkway strip is lit red from below, so the ANIMAL IS A DARK
#     SILHOUETTE blocking that light, not a red object. Segmenting "red"
#     therefore returns the whole strip - a 3651 px wide "body" on a
#     3840 px frame - instead of the rat.
#   * the edge of the glass throws a fixed bright line that passes the
#     green test and produces a row of phantom "paws" every single frame.
#
# A per-pixel median over frames spread across the clip gives the empty
# walkway: the animal is somewhere different in each sample, so it
# disappears from the median while everything static survives. Comparing
# each frame against that background fixes both problems at once.


def green_dominance(bgr):
    """g - max(r, b), saturating uint8. The raw quantity behind greenness_mask."""
    return channel_dominance(bgr, 1)


class BackgroundModel:
    """Median of the static scene: red backlight level and green dominance."""

    def __init__(self, red_median, gdom_median):
        self.red = red_median
        self.gdom = gdom_median

    @classmethod
    def build(cls, video_path, samples=11, verbose=True, scale=1.0, roi=None):
        """
        Sample frames evenly and take the per-pixel median.

        Frames are collected during ONE SEQUENTIAL PASS. Seeking with
        CAP_PROP_POS_FRAMES on 4K footage costs about 3.7 s per frame here
        versus 90 ms for a sequential read - roughly 40x slower - so random
        access is avoided entirely.

        Only the two channels actually needed are kept rather than whole
        BGR frames, which keeps peak memory to a third.
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            total = 1
        wanted = set(np.linspace(0, max(0, total - 1), max(2, samples)).astype(int).tolist())

        reds, gdoms = [], []
        idx = -1
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            if idx in wanted:
                if roi is not None:
                    rx, ry, rw, rh = roi
                    frame = frame[ry:ry + rh, rx:rx + rw]
                if scale != 1.0:
                    frame = cv2.resize(frame, None, fx=scale, fy=scale,
                                       interpolation=cv2.INTER_AREA)
                reds.append(frame[:, :, 2].copy())
                gdoms.append(green_dominance(frame))
        cap.release()

        if len(reds) < 3:
            if verbose:
                print("Not enough frames for a background model, falling back to colour only")
            return None

        red_median = np.median(np.stack(reds), axis=0).astype(np.uint8)
        gdom_median = np.median(np.stack(gdoms), axis=0).astype(np.uint8)
        if verbose:
            print(f"Background model built from {len(reds)} sampled frames")
        return cls(red_median, gdom_median)


# ======================================================================
#  Geometry helpers
# ======================================================================

def principal_axis(contour):
    """
    Long axis of a contour via PCA of its points.
    Returns a unit vector; the sign is arbitrary and gets resolved by motion.
    """
    pts = contour.reshape(-1, 2).astype(np.float32)
    if len(pts) < 2:
        return np.array([1.0, 0.0])
    mean = pts.mean(axis=0)
    centred = pts - mean
    cov = np.cov(centred.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, int(np.argmax(eigvals))]
    norm = np.linalg.norm(axis)
    return axis / norm if norm > 1e-9 else np.array([1.0, 0.0])


def extreme_points(contour, direction):
    """Hull points with the largest and smallest projection onto `direction`."""
    hull = cv2.convexHull(contour).reshape(-1, 2).astype(float)
    proj = hull @ np.asarray(direction, dtype=float)
    return tuple(hull[int(np.argmax(proj))]), tuple(hull[int(np.argmin(proj))])


# ======================================================================
#  Body detection and orientation tracking
# ======================================================================

class BodyTracker:
    """
    Finds the body and, crucially, works out which end is the head.

    The original version assumed the animal always moves along a fixed image
    axis and hard-coded "head = rightmost hull point". That silently inverts
    every paw label when the animal walks the other way. Here the body's long
    axis comes from PCA and its sign is resolved by the direction the centre
    of mass has actually been travelling.
    """

    def __init__(self, min_body_area=20000, history=12,
                 background=None, darkening=40, fixed_direction=None):
        self.min_body_area = min_body_area
        self.centres = deque(maxlen=history)
        self.direction = None      # smoothed unit vector of travel
        self.background = background
        self.darkening = darkening
        # A rig with a fixed walking direction should say so: estimating it
        # from motion is unreliable exactly when the animal is entering or
        # leaving the frame and only part of the silhouette is visible.
        self.fixed_direction = (np.asarray(fixed_direction, float)
                                if fixed_direction is not None else None)

    def body_mask(self, frame_bgr):
        """
        With a background model the body is where the animal BLOCKS the red
        backlight. Without one, fall back to plain red dominance - correct
        only on rigs where the animal itself is the red object.
        """
        if self.background is not None:
            shadow = cv2.subtract(self.background.red, frame_bgr[:, :, 2])
            shadow = cv2.GaussianBlur(shadow, (9, 9), 0)
            _, mask = cv2.threshold(shadow, self.darkening, 255, cv2.THRESH_BINARY)
            return mask
        _, mask = redness_mask(frame_bgr)
        return mask

    def update(self, frame_bgr):
        mask = self.body_mask(frame_bgr)
        mask = clean_up(mask, k=5, min_area=max(20, self.min_body_area // 4))

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = [c for c in contours if cv2.contourArea(c) >= self.min_body_area]
        if not candidates:
            return None

        body = max(candidates, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(body)

        M = cv2.moments(body)
        if M["m00"] > 0:
            centre = np.array([M["m10"] / M["m00"], M["m01"] / M["m00"]])
        else:
            centre = np.array([x + w / 2.0, y + h / 2.0])

        self.centres.append(centre)
        travel = self.fixed_direction if self.fixed_direction is not None \
            else self._travel_vector()

        axis = principal_axis(body)
        if travel is not None and np.dot(axis, travel) < 0:
            axis = -axis                      # point the axis the way it moves

        forward = travel if travel is not None else axis
        head, tail = extreme_points(body, forward)
        side_a, side_b = extreme_points(body, np.array([-forward[1], forward[0]]))

        return {
            "contour": body,
            "bbox": (int(x), int(y), int(w), int(h)),
            "centre": centre,
            "axis": axis,
            "forward": forward,
            "head": head,
            "tail": tail,
            "side_a": side_a,
            "side_b": side_b,
            "area": float(cv2.contourArea(body)),
            "confident_direction": travel is not None,
        }

    def _travel_vector(self):
        """Smoothed direction of travel, or None until the animal has moved enough."""
        if len(self.centres) < 3:
            return None
        delta = self.centres[-1] - self.centres[0]
        dist = np.linalg.norm(delta)
        if dist < 5.0:                        # still standing: keep the last estimate
            return self.direction
        new_dir = delta / dist
        if self.direction is None:
            self.direction = new_dir
        else:                                 # exponential smoothing, resists jitter
            blended = 0.7 * self.direction + 0.3 * new_dir
            n = np.linalg.norm(blended)
            self.direction = blended / n if n > 1e-9 else new_dir
        return self.direction


# ======================================================================
#  Paw detection and labelling
# ======================================================================

def detect_paws(frame_bgr, min_area=150, max_area_frac=0.05,
                min_dominance=30, min_value=70, merge_dist=60,
                background=None, max_elongation=6.0):
    """
    Every green contact in the frame, with its area and integrated intensity.

    Toes of one paw arrive as several blobs, so nearby components are merged
    by centroid distance before being reported.

    max_elongation rejects long thin streaks: a paw print is roughly compact,
    while glare along an edge is a ribbon. Cheap insurance on top of the
    background subtraction.
    """
    dom, mask = greenness_mask(frame_bgr, min_dominance, min_value,
                               background=background)
    mask = clean_up(mask, k=3, min_area=max(5, min_area // 3))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = mask.shape[:2]
    max_area = max_area_frac * H * W

    blobs = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area <= 0 or area > max_area:
            continue
        M = cv2.moments(cnt)
        if M["m00"] <= 0:
            continue
        blobs.append({
            "contour": cnt,
            "centre": np.array([M["m10"] / M["m00"], M["m01"] / M["m00"]]),
        })

    groups = _group_by_distance([b["centre"] for b in blobs], merge_dist)

    paws = []
    for group in groups:
        pts = np.vstack([blobs[i]["contour"] for i in group])
        hull = cv2.convexHull(pts)
        x, y, w, h = cv2.boundingRect(hull)

        # Work inside the bounding box only. Allocating a full-frame mask per
        # blob costs 8.3 M pixels each time on 4K footage, for a paw print a
        # few hundred pixels across.
        local = np.zeros((h, w), np.uint8)
        cv2.drawContours(local, [hull - [x, y]], -1, 255, -1)
        local = cv2.bitwise_and(local, mask[y:y + h, x:x + w])

        area_px = int(cv2.countNonZero(local))
        if area_px < min_area:
            continue

        # Reject ribbons: glare along an edge is long and thin, a paw is not
        (_, _), (rw, rh), _ = cv2.minAreaRect(hull)
        short_side, long_side = min(rw, rh), max(rw, rh)
        if short_side < 1 or long_side / short_side > max_elongation:
            continue

        # Integrated green dominance is the physically meaningful quantity:
        # in fTIR a firmer contact frustrates more light, so brighter pixels
        # mean more pressure. Summing them gives total contact "load".
        values = dom[y:y + h, x:x + w][local > 0].astype(np.float32) / 255.0
        intensity_sum = float(values.sum())

        M = cv2.moments(local, binaryImage=True)
        cx = x + (M["m10"] / M["m00"] if M["m00"] else w / 2.0)
        cy = y + (M["m01"] / M["m00"] if M["m00"] else h / 2.0)

        paws.append({
            "centre": np.array([cx, cy]),
            "bbox": (int(x), int(y), int(w), int(h)),
            "contour": hull,
            "area_px": area_px,
            "intensity_sum": intensity_sum,
            "mean_intensity": intensity_sum / area_px,
            "max_intensity": float(values.max()) if values.size else 0.0,
        })

    paws.sort(key=lambda p: p["area_px"], reverse=True)
    return paws, mask


def _group_by_distance(centres, threshold):
    """Union nearby points into groups (BFS over a distance graph)."""
    n = len(centres)
    if n == 0:
        return []
    pts = np.asarray(centres, dtype=np.float32)
    dist = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=2)

    seen = np.zeros(n, bool)
    groups = []
    for i in range(n):
        if seen[i]:
            continue
        seen[i] = True
        group, queue = [i], [i]
        while queue:
            j = queue.pop()
            for k in np.where(dist[j] < threshold)[0]:
                if not seen[k]:
                    seen[k] = True
                    queue.append(int(k))
                    group.append(int(k))
        groups.append(group)
    return groups


def classify_paw(paw_centre, body, left_side="bottom", midline_offset=0.0):
    """
    Label a contact Front/Back x Left/Right in the animal's own frame.

    Front/back : projection onto the direction of travel, relative to the
                 body centre. Positive means ahead of the centre.
    Left/right : projection onto the perpendicular, which rotates with the
                 direction of travel, so the convention holds either way
                 the animal walks.

    left_side names the edge of the frame where the animal's LEFT flank
    appears WHEN IT WALKS LEFT TO RIGHT. On this rig the walkway is filmed
    from below through the glass, so the image is mirrored and the left
    flank is at the bottom. Getting this backwards swaps every Left/Right
    label with no other visible symptom, so it is stated explicitly rather
    than assumed.
    """
    forward = np.asarray(body["forward"], dtype=float)
    normal = np.array([-forward[1], forward[0]])   # +y (down) when walking right

    rel = np.asarray(paw_centre, dtype=float) - body["centre"]
    along = float(np.dot(rel, forward))
    across = float(np.dot(rel, normal))

    fb = "Front" if along >= 0 else "Back"
    side_sign = 1.0 if left_side == "bottom" else -1.0
    lr = "Left" if (across - midline_offset) * side_sign >= 0 else "Right"
    return f"{fb}_{lr}", along, across


def estimate_midline_offset(across_values, min_share=0.15):
    """
    Find where the left/right boundary really sits.

    The paws touch the glass while the body floats above it, so unless the
    camera is exactly perpendicular the silhouette is projected slightly to
    one side of the contact plane. The result is a constant bias: the two
    clusters of "distance from the midline" are cleanly separated but not
    centred on zero, and contacts close to the midline get the wrong side.

    The signed distances form two well-separated clusters, so the widest gap
    between consecutive sorted values marks the true boundary. Returns the
    offset to subtract, or None when the data do not support the estimate
    (for example only one side was ever in contact).
    """
    values = np.sort(np.asarray(across_values, dtype=float))
    if len(values) < 20:
        return None

    gaps = np.diff(values)
    if not len(gaps):
        return None

    # Only consider gaps in the middle of the range - the widest gap in a
    # single-cluster distribution sits at its edge and means nothing.
    span = values[-1] - values[0]
    if span <= 0:
        return None
    order = np.argsort(gaps)[::-1]
    for k in order[:5]:
        boundary = 0.5 * (values[k] + values[k + 1])
        below = int((values < boundary).sum())
        above = len(values) - below
        if min(below, above) < min_share * len(values):
            continue
        if abs(boundary - values.mean()) > 0.35 * span:
            continue
        return float(boundary)
    return None


def near_body(paw_centre, body, max_reach=1.1):
    """
    A real contact sits under or beside the animal. Prints left elsewhere on
    the walkway, or glare, can be far away - discard those rather than
    labelling them as one of the four paws.
    """
    _, _, bw, bh = body["bbox"]
    reach = max_reach * max(bw, bh) / 2.0
    return float(np.linalg.norm(np.asarray(paw_centre, float) - body["centre"])) <= reach


# ======================================================================
#  Grouping per-frame detections into steps
# ======================================================================

class StepBuilder:
    """
    A paw stays down for many frames. The original code incremented the step
    counter once per frame, so a single contact became a dozen "steps" and the
    metric plot was really a per-frame plot. Here consecutive detections of
    the same paw are collapsed into one step, and the step is summarised by
    its peak contact - the moment of full weight bearing.
    """

    def __init__(self, gap_tolerance=3):
        self.gap_tolerance = gap_tolerance
        self.open_steps = {}     # paw label -> step being accumulated
        self.steps = []

    def add(self, label, frame_idx, time_ms, paw):
        step = self.open_steps.get(label)
        if step is not None and frame_idx - step["last_frame"] > self.gap_tolerance:
            self._close(label)
            step = None

        if step is None:
            step = {
                "paw": label,
                "first_frame": frame_idx,
                "last_frame": frame_idx,
                "start_ms": time_ms,
                "end_ms": time_ms,
                "n_frames": 0,
                "peak_area": 0,
                "peak_frame": frame_idx,
                "peak_intensity": 0.0,
                "peak_mean_intensity": 0.0,
                "areas": [],
                "cx": float(paw["centre"][0]),
                "cy": float(paw["centre"][1]),
            }
            self.open_steps[label] = step

        step["last_frame"] = frame_idx
        step["end_ms"] = time_ms
        step["n_frames"] += 1
        step["areas"].append(paw["area_px"])

        if paw["area_px"] > step["peak_area"]:
            step["peak_area"] = paw["area_px"]
            step["peak_frame"] = frame_idx
            step["peak_intensity"] = paw["intensity_sum"]
            step["peak_mean_intensity"] = paw["mean_intensity"]
            step["cx"] = float(paw["centre"][0])
            step["cy"] = float(paw["centre"][1])

    def _close(self, label):
        step = self.open_steps.pop(label, None)
        if step is not None:
            self.steps.append(step)

    def finish(self, min_frames=2):
        for label in list(self.open_steps):
            self._close(label)
        self.steps = [s for s in self.steps if s["n_frames"] >= min_frames]
        self.steps.sort(key=lambda s: (s["first_frame"], s["paw"]))
        for i, s in enumerate(self.steps, 1):
            s["step"] = i
            s["duration_ms"] = round(s["end_ms"] - s["start_ms"], 1)
            s["mean_area"] = round(float(np.mean(s["areas"])), 1) if s["areas"] else 0.0
            del s["areas"]
        return self.steps


# ======================================================================
#  Output
# ======================================================================

PAW_COLOURS = {
    "Front_Left":  (255, 160, 60),
    "Front_Right": (60, 200, 255),
    "Back_Left":   (120, 255, 120),
    "Back_Right":  (200, 120, 255),
}
PAW_ORDER = ["Front_Left", "Front_Right", "Back_Left", "Back_Right"]


def export_steps_csv(steps, path):
    """The per-step table - the array meant for downstream analysis."""
    fields = ["step", "paw", "first_frame", "last_frame", "peak_frame",
              "n_frames", "start_ms", "end_ms", "duration_ms",
              "peak_area", "mean_area", "peak_intensity",
              "peak_mean_intensity", "cx", "cy"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for s in steps:
            writer.writerow(s)
    print(f"Steps CSV saved to: {path}  ({len(steps)} steps)")


def export_detections_csv(detections, path):
    """Raw per-frame detections, in case the step grouping needs re-deriving."""
    fields = ["frame", "time_ms", "paw", "cx", "cy", "area_px",
              "intensity_sum", "mean_intensity", "along", "across"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(detections)
    print(f"Per-frame CSV saved to: {path}  ({len(detections)} detections)")


def export_plots(steps, path):
    """Contact area per step and a footfall (gait) diagram."""
    if not steps:
        print("No steps detected, skipping plots.")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8))

    for paw in PAW_ORDER:
        pts = [(s["step"], s["peak_area"]) for s in steps if s["paw"] == paw]
        if pts:
            xs, ys = zip(*pts)
            ax1.plot(xs, ys, "o-", linewidth=2,
                     color=np.array(PAW_COLOURS[paw][::-1]) / 255.0, label=paw)
    ax1.set_xlabel("Step index")
    ax1.set_ylabel("Peak contact area (px)")
    ax1.set_title("Peak contact area per step")
    ax1.grid(True, linestyle="--", alpha=0.3)
    ax1.legend(loc="center left", bbox_to_anchor=(1.01, 0.5))

    # Footfall diagram: when each paw is on the ground
    for row, paw in enumerate(PAW_ORDER):
        for s in steps:
            if s["paw"] != paw:
                continue
            width = max(s["end_ms"] - s["start_ms"], 1.0)
            ax2.barh(row, width, left=s["start_ms"], height=0.6,
                     color=np.array(PAW_COLOURS[paw][::-1]) / 255.0)
    ax2.set_yticks(range(len(PAW_ORDER)))
    ax2.set_yticklabels(PAW_ORDER)
    ax2.set_xlabel("Time (ms)")
    ax2.set_title("Footfall pattern (stance phases)")
    ax2.grid(True, axis="x", linestyle="--", alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Plots saved to: {path}")


def open_writer(path, fps, size, max_width=1920, max_height=4000):
    """
    Create a VideoWriter that actually opens.

    The original stacked four full-resolution panels vertically, which for a
    4K input asks for a 3840x8640 MPEG-4 frame. That exceeds what the codec
    accepts, so the writer failed to open and every write was silently
    discarded - the debug video simply never appeared, with no error.

    A four-panel stack is 2.25x taller than it is wide, so the HEIGHT is the
    binding constraint, not the width. Both are capped here and the result is
    verified before returning.
    """
    w, h = size
    scale = min(1.0, max_width / float(w), max_height / float(h))
    out_size = (max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2))

    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, out_size)
    if not writer.isOpened():
        print(f"Warning: could not open the video writer for {path} at {out_size}")
        return None, out_size
    return writer, out_size


def panel_title(img, text, colour=(0, 255, 255), scale_ref=None):
    """Section caption in the top-left corner, sized to the panel."""
    w = img.shape[1] if scale_ref is None else scale_ref
    fs = max(0.45, w / 1400.0)
    th = max(1, int(w / 700))
    cv2.putText(img, text, (int(14 * fs) + 6, int(40 * fs) + 6),
                cv2.FONT_HERSHEY_DUPLEX, fs, colour, th, cv2.LINE_AA)
    return img


def green_only_view(frame, green_mask):
    """Black frame carrying just the detected green footprints."""
    out = np.zeros_like(frame)
    out[..., 1] = cv2.bitwise_and(frame[..., 1], green_mask)
    return out


def draw_paw_labels(img, labelled_paws):
    """Boxes and Front/Back x Left/Right captions over the footprints."""
    w = img.shape[1]
    fs = max(0.4, w / 1600.0)
    th = max(1, int(w / 800))
    for label, paw in labelled_paws:
        x, y, bw, bh = paw["bbox"]
        colour = PAW_COLOURS.get(label, (255, 255, 255))
        pad = max(4, int(w / 200))
        cv2.rectangle(img, (x - pad, y - pad), (x + bw + pad, y + bh + pad), colour, th)
        cv2.putText(img, label, (x + bw + pad + 4, y + bh),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, colour, th, cv2.LINE_AA)
    return img


def draw_body_details(frame, body, left_side="bottom"):
    """Body outline with head, tail, both flanks, centre and heading arrow."""
    out = np.zeros_like(frame)
    if body is None:
        return out

    w = out.shape[1]
    fs = max(0.4, w / 1600.0)
    th = max(1, int(w / 800))
    r = max(3, int(w / 260))

    cv2.drawContours(out, [body["contour"]], -1, (255, 255, 255), th)
    x, y, bw, bh = body["bbox"]
    cv2.rectangle(out, (x, y), (x + bw, y + bh), (120, 120, 120), max(1, th // 2))

    # extreme_points returns (max projection, min projection) along the normal,
    # and the normal points to the animal's LEFT on a ventral rig
    left_pt, right_pt = (body["side_a"], body["side_b"]) if left_side == "bottom" \
        else (body["side_b"], body["side_a"])

    for name, pt, colour in (("HEAD", body["head"], (255, 40, 160)),
                             ("TAIL", body["tail"], (40, 255, 60)),
                             ("LEFT", left_pt, (255, 146, 125)),
                             ("RIGHT", right_pt, (100, 140, 250))):
        p = (int(pt[0]), int(pt[1]))
        cv2.circle(out, p, r, colour, -1)
        cv2.putText(out, name, (p[0] + r + 3, p[1] - r - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th, cv2.LINE_AA)

    cx, cy = body["centre"].astype(int)
    cv2.circle(out, (int(cx), int(cy)), r, (0, 0, 255), -1)
    cv2.putText(out, "CENTER", (int(cx) + r + 3, int(cy) + r + 12),
                cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), th, cv2.LINE_AA)

    tip = (body["centre"] + np.asarray(body["forward"]) * (bw * 0.35 + 40)).astype(int)
    cv2.arrowedLine(out, (int(cx), int(cy)), (int(tip[0]), int(tip[1])),
                    (0, 255, 255), th, tipLength=0.25)
    return out


def build_stack(frame, body, labelled_paws, green_mask, frame_idx, time_ms,
                left_side="bottom", panel_width=None):
    """
    The four stacked sections of the debug video:

      1  ORIGINAL              the ROI as filmed
      2  GREEN FOOTPRINTS      colour segmentation only
      3  PAWS                  the same prints, labelled per paw
      4  DETAILS               body outline, head/tail/flanks, heading

    Panels are resized BEFORE stacking. Stacking four 4K panels first would
    build a 3840x8640 image that no MPEG-4 writer will accept and that costs
    100 MB per frame to hold.
    """
    green_view = green_only_view(frame, green_mask)

    panels = [
        panel_title(frame.copy(),
                    f"ORIGINAL  Frame: {frame_idx}  Time: {int(time_ms)} ms"),
        panel_title(green_view.copy(), "GREEN FOOTPRINTS ONLY"),
        panel_title(draw_paw_labels(green_view.copy(), labelled_paws), "PAWS",
                    (0, 255, 0)),
        panel_title(draw_body_details(frame, body, left_side), "DETAILS", (0, 255, 0)),
    ]

    if panel_width and panel_width != frame.shape[1]:
        ph = max(2, int(frame.shape[0] * panel_width / frame.shape[1]))
        panels = [cv2.resize(p, (panel_width, ph), interpolation=cv2.INTER_AREA)
                  for p in panels]
    return np.vstack(panels)


def annotate(frame, body, labelled_paws, frame_idx, time_ms):
    """Draw the body pose and every labelled contact onto a copy of the frame."""
    vis = frame.copy()
    thickness = max(1, vis.shape[1] // 900)
    font_scale = max(0.4, vis.shape[1] / 1400.0)

    if body is not None:
        cv2.drawContours(vis, [body["contour"]], -1, (200, 200, 200), thickness)
        cx, cy = body["centre"].astype(int)
        cv2.circle(vis, (cx, cy), 4 * thickness, (0, 0, 255), -1)
        cv2.putText(vis, "CENTER", (cx + 8, cy - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    font_scale, (255, 255, 255), thickness)
        for name, pt, colour in (("HEAD", body["head"], (255, 40, 160)),
                                 ("TAIL", body["tail"], (40, 255, 60))):
            p = (int(pt[0]), int(pt[1]))
            cv2.circle(vis, p, 4 * thickness, colour, -1)
            cv2.putText(vis, name, (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, (255, 255, 255), thickness)
        tip = (body["centre"] + np.asarray(body["forward"]) * 150).astype(int)
        cv2.arrowedLine(vis, (int(cx), int(cy)), (int(tip[0]), int(tip[1])),
                        (0, 255, 255), thickness, tipLength=0.3)

    for label, paw in labelled_paws:
        x, y, w, h = paw["bbox"]
        colour = PAW_COLOURS.get(label, (255, 255, 255))
        pad = 6 * thickness
        cv2.rectangle(vis, (x - pad, y - pad), (x + w + pad, y + h + pad), colour, thickness)
        cv2.putText(vis, f"{label} {paw['area_px']}", (x - pad, max(14, y - pad - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale * 0.8, colour, thickness)

    cv2.putText(vis, f"Frame {frame_idx}  t={int(time_ms)} ms",
                (20, int(50 * font_scale)), cv2.FONT_HERSHEY_DUPLEX,
                font_scale, (0, 255, 255), thickness)
    return vis


# ======================================================================
#  Main processing
# ======================================================================

DIRECTION_VECTORS = {"ltr": (1.0, 0.0), "rtl": (-1.0, 0.0), "auto": None}


def process_video(video_path, roi=None, out_dir=".", display=True,
                  left_side="bottom", direction="ltr",
                  min_body_area=20000, min_paw_area=150,
                  green_dominance_thr=30, green_value=70, merge_dist=60,
                  gap_tolerance=3, min_step_frames=2, write_video=True,
                  use_background=True, bg_samples=11, body_darkening=40,
                  max_reach=1.1, proc_scale=None, max_proc_width=1600,
                  midline_offset=None, panel_width=960, preview_height=900,
                  progress_every=25):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    messagebox.showinfo("Info",f"Please wait, this process may take time.")
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or np.isnan(fps):
        fps = 25.0
        print("Warning: the file reports no frame rate, assuming 25 fps")

    if roi is None:
        roi = (0, 0, frame_w, frame_h)
    x, y, w, h = [int(v) for v in roi]
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    w = max(1, min(w, frame_w - x))
    h = max(1, min(h, frame_h - y))
    print(f"Video: {frame_w}x{frame_h}, {total} frames, {fps:.1f} fps")
    print(f"ROI:   x={x} y={y} w={w} h={h}")
    dir_text = {"ltr": "left to right", "rtl": "right to left",
                "auto": "estimated from motion"}[direction]
    print(f"Walk:  {dir_text}")
    print(f"Sides: the animal's LEFT flank is at the {left_side.upper()} of the frame "
          f"when it walks left to right")

    os.makedirs(out_dir, exist_ok=True)
    writer, out_size = (None, None)

    # Detection runs on a downscaled copy: a paw print is tens of pixels
    # across, so full 4K resolution buys nothing and costs 4x the time per
    # halving. Every reported coordinate and area is converted back to
    # full-resolution units, so the numbers do not depend on this setting.
    if proc_scale is None:
        proc_scale = min(1.0, max_proc_width / float(w))
    proc_scale = float(np.clip(proc_scale, 0.05, 1.0))
    inv = 1.0 / proc_scale
    if proc_scale < 1.0:
        print(f"Scale: processing at {proc_scale:.2f} "
              f"({int(w * proc_scale)}x{int(h * proc_scale)})")

    # thresholds are given in full-resolution units, convert them once
    p_min_body = max(1, int(min_body_area * proc_scale ** 2))
    p_min_paw = max(1, int(min_paw_area * proc_scale ** 2))
    p_merge = max(2, int(merge_dist * proc_scale))

    background = None
    if use_background:
        background = BackgroundModel.build(
            video_path, samples=bg_samples, scale=proc_scale,
            roi=(x, y, w, h) if (x, y, w, h) != (0, 0, frame_w, frame_h) else None)
    else:
        print("Background model disabled (--no-background)")

    proc_w, proc_h = int(w * proc_scale), int(h * proc_scale)
    panel_w = min(panel_width, proc_w)
    panel_h = max(2, int(proc_h * panel_w / proc_w))
    if write_video:
        writer, out_size = open_writer(
            os.path.join(out_dir, "rat_walks_output.mp4"), fps,
            (panel_w, panel_h * 4))
        if writer is not None:
            print(f"Video: 4 stacked panels, {out_size[0]}x{out_size[1]}")

    provisional_offset = 0.0 if midline_offset is None else midline_offset * proc_scale

    tracker = BodyTracker(min_body_area=p_min_body, background=background,
                          darkening=body_darkening,
                          fixed_direction=DIRECTION_VECTORS[direction])
    builder = StepBuilder(gap_tolerance=gap_tolerance)
    detections = []
    frames_without_body = 0
    frame_idx = -1

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        time_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        roi_frame = frame[y:y + h, x:x + w]
        small = roi_frame if proc_scale == 1.0 else cv2.resize(
            roi_frame, None, fx=proc_scale, fy=proc_scale, interpolation=cv2.INTER_AREA)

        body = tracker.update(small)

        # Paws are found on the ORIGINAL colours. The previous version zeroed
        # the red channel before segmentation, which destroys exactly the
        # information green-over-red dominance needs.
        paws, green_mask = detect_paws(
            small, min_area=p_min_paw,
            min_dominance=green_dominance_thr, min_value=green_value,
            merge_dist=p_merge, background=background)

        labelled = []
        if body is None:
            frames_without_body += 1
        else:
            for paw in paws:
                if not near_body(paw["centre"], body, max_reach):
                    continue
                label, along, across = classify_paw(paw["centre"], body, left_side,
                                                    provisional_offset)
                labelled.append((label, paw))
                builder.add(label, frame_idx, time_ms, paw)
                detections.append({
                    "frame": frame_idx, "time_ms": round(time_ms, 1), "paw": label,
                    "cx": round(float(paw["centre"][0]) * inv, 1),
                    "cy": round(float(paw["centre"][1]) * inv, 1),
                    "area_px": int(round(paw["area_px"] * inv * inv)),
                    "intensity_sum": round(paw["intensity_sum"], 1),
                    "mean_intensity": round(paw["mean_intensity"], 4),
                    "along": round(along, 1), "across": round(across, 1),
                    "_area_proc": paw["area_px"], "_centre_proc": paw["centre"],
                })

        if writer is not None or display:
            stacked = build_stack(small, body, labelled, green_mask,
                                  frame_idx, time_ms, left_side, panel_w)
            if writer is not None:
                writer.write(stacked if stacked.shape[1::-1] == out_size
                             else cv2.resize(stacked, out_size))
            if display:
                ph = max(1, int(preview_height))
                pw = max(1, int(ph * stacked.shape[1] / stacked.shape[0]))
                cv2.imshow("Gait2Paws. Obtaining animal tracks",
                           cv2.resize(stacked, (pw, ph)))
                if (cv2.waitKey(1) & 0xFF) == 27:
                    print("Interrupted by user (ESC)")
                    break

        if progress_every and frame_idx % progress_every == 0:
            print(f"  frame {frame_idx}/{total}: {len(labelled)} contacts "
                  f"({len(paws)} blobs), body {'ok' if body is not None else 'not found'}")

    cap.release()
    if writer is not None:
        writer.release()
    if display:
        cv2.destroyAllWindows()

    # The overlay used the provisional offset; the analysis output gets the
    # calibrated one, because a systematic bias silently mislabels every
    # contact that lands near the midline.
    if midline_offset is None and detections:
        estimated = estimate_midline_offset([d["across"] for d in detections])
        if estimated is not None and abs(estimated) > 1e-6:
            print(f"\nMidline calibration: boundary sits at {estimated:+.1f} px, not 0")
            builder = StepBuilder(gap_tolerance=gap_tolerance)
            changed = 0
            for d in detections:
                side_sign = 1.0 if left_side == "bottom" else -1.0
                fb = "Front" if d["along"] >= 0 else "Back"
                lr = "Left" if (d["across"] - estimated) * side_sign >= 0 else "Right"
                new_label = f"{fb}_{lr}"
                if new_label != d["paw"]:
                    changed += 1
                d["paw"] = new_label
            for d in detections:
                builder.add(d["paw"], d["frame"], d["time_ms"],
                            {"area_px": d["_area_proc"], "centre": d["_centre_proc"],
                             "intensity_sum": d["intensity_sum"],
                             "mean_intensity": d["mean_intensity"]})
            print(f"  {changed} of {len(detections)} detections relabelled")
            print(f"  pin it with  --midline-offset {estimated / proc_scale:.1f}  "
                  f"to get the same labels in the overlay video")

    steps = builder.finish(min_frames=min_step_frames)
    for s in steps:                       # back to full-resolution units
        s["peak_area"] = int(round(s["peak_area"] * inv * inv))
        s["mean_area"] = round(s["mean_area"] * inv * inv, 1)
        s["cx"] = round(s["cx"] * inv, 1)
        s["cy"] = round(s["cy"] * inv, 1)
        s["peak_intensity"] = round(s["peak_intensity"] * inv * inv, 1)
        s["peak_mean_intensity"] = round(s["peak_mean_intensity"], 4)
    print(f"\nProcessed {frame_idx + 1} frames, "
          f"{frames_without_body} without a body detection")
    print(f"Detections: {len(detections)}, grouped into {len(steps)} steps")
    for paw in PAW_ORDER:
        n = sum(1 for s in steps if s["paw"] == paw)
        print(f"  {paw:<12} {n} steps")

    export_steps_csv(steps, os.path.join(out_dir, "paw_steps.csv"))
    export_detections_csv(detections, os.path.join(out_dir, "paw_detections.csv"))
    export_plots(steps, os.path.join(out_dir, "paw_metrics_final.png"))
    return steps, detections


def select_video_dialog():
    """File dialog, used only when no path is given on the command line."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()                    # otherwise an empty grey window is left behind
    path = filedialog.askopenfilename(
        title="Select a walkway video",
        filetypes=[("Video files", "*.mp4 *.avi *.mov"), ("All files", "*.*")])
    root.destroy()
    return path


def select_roi_dialog(frame):
    """Interactive ROI on a downscaled preview, mapped back to full resolution."""
    h, w = frame.shape[:2]
    scale = min(1.0, 1000.0 / w)
    preview = cv2.resize(frame, (int(w * scale), int(h * scale)))
    r = cv2.selectROI("Select a workspace", preview, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Select a workspace")
    if r[2] == 0 or r[3] == 0:
        print("No ROI selected, using the whole frame.")
        return None
    return tuple(int(v / scale) for v in r)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect and label rat paw contacts on an fTIR walkway video.")
    parser.add_argument("video", nargs="?", help="input video (a dialog opens if omitted)")
    parser.add_argument("--roi", help="x,y,w,h in full-resolution pixels (interactive if omitted)")
    parser.add_argument("--out-dir", default=".", help="where to write CSV/PNG/MP4")
    parser.add_argument("--no-display", action="store_true", help="batch mode, no windows")
    parser.add_argument("--no-video", action="store_true", help="skip the annotated video")
    parser.add_argument("--direction", choices=["ltr", "rtl", "auto"], default="ltr",
                        help="walking direction: ltr (default), rtl, or auto "
                             "(estimated from motion - less reliable while the animal "
                             "is entering or leaving the frame)")
    parser.add_argument("--left-side", choices=["bottom", "top"], default="bottom",
                        help="edge of the frame showing the animal's LEFT flank when it "
                             "walks left to right. Default 'bottom' matches an fTIR "
                             "walkway filmed from below. Wrong value swaps every "
                             "Left/Right label silently.")
    parser.add_argument("--min-body-area", type=int, default=20000)
    parser.add_argument("--min-paw-area", type=int, default=150)
    parser.add_argument("--green-dominance", type=int, default=30,
                        help="how far green must beat red/blue (0-255)")
    parser.add_argument("--green-value", type=int, default=70,
                        help="minimum green brightness (0-255)")
    parser.add_argument("--merge-dist", type=int, default=60,
                        help="max distance between toe blobs of one paw (px)")
    parser.add_argument("--gap-tolerance", type=int, default=3,
                        help="frames a contact may vanish for and still be one step")
    parser.add_argument("--min-step-frames", type=int, default=2,
                        help="discard contacts shorter than this many frames")
    parser.add_argument("--no-background", action="store_true",
                        help="skip the median background model (needed only if the "
                             "animal never moves, which makes the median unusable)")
    parser.add_argument("--bg-samples", type=int, default=11,
                        help="frames sampled for the background median")
    parser.add_argument("--body-darkening", type=int, default=40,
                        help="how much the animal must darken the red backlight (0-255)")
    parser.add_argument("--panel-width", type=int, default=960,
                        help="width of each of the 4 stacked panels in the output video")
    parser.add_argument("--preview-height", type=int, default=900,
                        help="height of the on-screen preview window")
    parser.add_argument("--midline-offset", type=float, default=None,
                        help="pin the left/right boundary, in full-resolution px "
                             "(default: calibrated automatically from the data)")
    parser.add_argument("--scale", type=float, default=None,
                        help="processing scale (default: auto, so the frame is at most "
                             "1600 px wide). Reported areas and coordinates are always "
                             "converted back to full-resolution pixels.")
    parser.add_argument("--max-reach", type=float, default=1.1,
                        help="max distance of a contact from the body centre, "
                             "in half body-bbox sizes")
    args = parser.parse_args(argv)

    video = args.video or select_video_dialog()
    if not video:
        print("No video selected.")
        return 1
    if not os.path.isfile(video):
        print(f"File not found: {video}")
        return 1

    display = not args.no_display
    if not display:
        matplotlib.use("Agg")

    roi = None
    if args.roi:
        try:
            roi = tuple(int(v) for v in args.roi.split(","))
            if len(roi) != 4:
                raise ValueError
        except ValueError:
            print("--roi must look like  x,y,w,h")
            return 1
    elif display:
        cap = cv2.VideoCapture(video)
        ok, first = cap.read()
        cap.release()
        if ok:
            roi = select_roi_dialog(first)

    out_dir = args.out_dir or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "files_log.txt"), "a+", encoding="utf-8") as f:
        f.write(os.path.basename(video) + "\n")

    process_video(video, roi=roi, out_dir=out_dir, display=display,
                  left_side=args.left_side, direction=args.direction,
                  min_body_area=args.min_body_area, min_paw_area=args.min_paw_area,
                  green_dominance_thr=args.green_dominance, green_value=args.green_value,
                  merge_dist=args.merge_dist, gap_tolerance=args.gap_tolerance,
                  min_step_frames=args.min_step_frames,
                  write_video=not args.no_video,
                  use_background=not args.no_background,
                  bg_samples=args.bg_samples,
                  body_darkening=args.body_darkening,
                  max_reach=args.max_reach, proc_scale=args.scale,
                  midline_offset=args.midline_offset,
                  panel_width=args.panel_width,
                  preview_height=args.preview_height)
    return 0


if __name__ == "__main__":
    sys.exit(main())
