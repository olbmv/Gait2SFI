# Gait2SFI
# a script for frame-by-frame search for the necessary rodent footprints on video.
# Author: PhD student Oleksandr Bomikhov
# Bogomoletz Institute of Physiology, National Academy of Sciences of Ukraine


import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "threads|1"  # Prevent FFmpeg threading issues
import tkinter as tk
from tkinter import filedialog, messagebox
import cv2
import numpy as np
import matplotlib
matplotlib.use('TkAgg')  # Explicitly set TkAgg backend
from matplotlib import pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import time
import sys
import subprocess
import importlib.util
import inspect

class MyToolbar(NavigationToolbar2Tk):
    
    def release_zoom(self, event):
        super().release_zoom(event)
        # Automatically disable zoom after use
        self.zoom()  # the second call disables

    def release_pan(self, event):
        super().release_pan(event)
        self.pan()  # disable drag and drop of frame


class Gait2SFI:
    def __init__(self):
        print("Initializing Gait2SFI")  # Debug output
        self.root = tk.Tk()
        self.root.title("Rodent Gait Analyzer")
        
        # Video handling
        self.video_path = None
        self.cap = None
        self.current_frame = 1
        self.total_frames = 0
        self.last_update_time = 0
        self.update_interval = 0.1  # Limit updates to ~10 fps
        self.area1_frame_indices = []  # Indices for area 1 frames
        self.area2_frame_indices = []  # Indices for area 2 frames
        self.area_indices = [0, 0]   # 0-BASED position of each area in its own sequence
        self.current_frame = 0
        self.area_pair_counter = 0  # Counter for selected area pairs
        self.second_wn_frames_limit = 15
        self.n_area_frames = 0       # actual number of frames available in the pair

        # Re-entrancy guards / debounce handles for the second window
        self._expected_slider_value = [None, None]  # value we wrote ourselves
        self._slider_dragging = [False, False]      # pointer is holding the handle
        self._second_window_job = None              # pending setup_second_window call
        self._suppress_lut_cb = False
        self._area_redraw_job = None
        self._main_redraw_job = None
        self._expected_frame_slider_value = None
        self._suppression_jobs = []   # pending after_idle guard-release callbacks
        self.area_sliders = [None, None]
        self.area_counter_labels = [None, None]
        
        # Selection variables
        self.rectangles = []  # List of (x, y, w, h, frame_idx) in original size
        self.current_rect = None
        self.start_x = None
        self.start_y = None
        self.selected_areas = []
        
        # Measurement variables
        self.points = []
        self.distances = []
        
        # LUT variables
        self.contrast_alpha = 1.0  # Default contrast
        self.contrast_beta = 0.0   # Default brightness
        self.should_apply_lut = False  # Flag to apply LUT only when contrast or brightness slider is used
        
        # Green area calculation
        self.green_area_values = [None, None]  # [area1, area2]
        self.green_area_button = None  # Button for calculating green area
        self.sum_green_area_button = None  # Button to display the summarized frames
        self.sum_frames_entry = None   # Entry with the frame selection, e.g. "1-8" or "1,2,3,8"
        self.green_sum_positions = []  # 0-based positions actually summed
        self._last_green_spec = None   # spec string the current accumulation was built with
        self.green_cache = None        # per-frame results, computed ONCE per pair of areas
        self.green_cache_key = None    # identifies the pair the cache belongs to
        # Frame pinned per area (e.g. by "Find maximum contact area"). Survives
        # redraws and is cleared ONLY by real navigation (slider / arrow buttons).
        self.frame_override = [None, None]
        self.display_mode = 'frame'    # 'frame' = single frames, 'sum' = accumulated image
        self.displayed_frames = [None, None]  # global video frame(s) currently on screen
        self.save_to_image = None  # Button for saving areas to image
        self.run_sfi_button = None  # Button that launches SFI.py
        self.sfi_process = None     # Fallback: handle of a separate SFI.py process
        self.sfi_window = None      # Toplevel hosting the embedded SFI panel
        self.sfi_app = None         # SFI.Application instance (same process)
        self.sfi_status_label = None  # Shows which field is armed
        
        # GUI elements
        self.fig1, self.ax1 = plt.subplots(figsize=(8, 6), dpi=150)
        self.canvas1 = None
        self.toolbar = None
        self.fig2 = None
        self.ax2 = None
        self.canvas2 = None
        self.second_window = None
        self.frame_slider = None  # Slider for main window
        self.frame_entry = None   # Entry for frame number
        self.frame_range = None   # Entry for frame range in second window
        self.nav_frame = None     # Frame for navigation controls
        self.area_sliders = [None, None]   # one slider per selected area
        self.area_entry = None    # Entry for area frame offset
        self.contrast_slider = None  # Slider for contrast
        self.brightness_slider = None  # Slider for brightness
        
        # Bind main window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_main_window_close)
        
        self.setup_file_dialog()
        print("Gait2SFI initialized successfully")  # Debug output

    def setup_file_dialog(self):
        print("Setting up file dialog")  # Debug output
        file_frame = tk.Frame(self.root)
        file_frame.pack(pady=10)
        
        tk.Button(file_frame, text="Select Video", command=self.select_video,
                  width=20, height=2, font=("Arial", 14, "bold")).pack()
        
        print("File dialog setup complete")  # Debug output

    def select_video(self):
        print("Opening file dialog for video selection")  # Debug output
        self.video_path = filedialog.askopenfilename(
            filetypes=[("Video files", "*.mp4 *.avi *.mov")]
        )
        if self.video_path:
            self.load_video()
        print(f"Video path selected: {self.video_path}")  # Debug output
        with open('shared.txt', 'w', encoding='utf-8') as file:
             file.write(os.path.basename(self.video_path))  # Write video filename for SFI.py script's log

    def load_video(self):
        print(f"Loading video: {self.video_path}")  # Debug output
        # Explicitly release previous VideoCapture
        if self.cap and self.cap.isOpened():
            self.cap.release()
            print("Released previous VideoCapture")
        self.cap = None  # Reset to None to ensure reinitialization
        
        self.cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            print("Error: Could not open video file. Check FFmpeg and video format.")
            messagebox.showerror("Error", "Could not open video file. Check FFmpeg and video format.")
            return    
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.current_frame = 1
        self.area1_frame_indices = []
        self.area2_frame_indices = []
        self.area_indices = [0, 0]
        self.n_area_frames = 0
        self.area_pair_counter = 0
        self.rectangles = []
        self.selected_areas = []
        self.points = []
        self.distances = []
        self.contrast_alpha = 1.0
        self.contrast_beta = 0.0
        self.should_apply_lut = False
        self.start_x = None
        self.start_y = None
        self.current_rect = None
        self.green_area_values = [None, None]
        self.green_frs = [None, None]
        self.intg_green_frs = [None, None]
        self.green_sum_positions = []
        self._last_green_spec = None
        self.green_cache = None
        self.green_cache_key = None
        self.frame_override = [None, None]
        self.display_mode = 'frame'
        self.displayed_frames = [None, None]
        
        if self.second_window:
            try:
                self.second_window.destroy()
            except tk.TclError as e:
                print(f"Error destroying second window: {e}")
            self.second_window = None
            self.fig2 = None
            self.ax2 = None
            self.canvas2 = None
            self.area_sliders = [None, None]
            self.area_entry = None
            self.contrast_slider = None
            self.brightness_slider = None
        
        if self.frame_slider:
            self.frame_slider.destroy()
        # Valid frame numbers are 0 .. total_frames-1, so a 200-frame clip is
        # 0..199. The slider used to start at 1 and stop at total_frames-1,
        # which hid the very first frame and mislabelled the range.
        self.frame_slider = tk.Scale(self.root, from_=0, to=max(0, self.total_frames - 1),
                                    orient=tk.HORIZONTAL,
                                    length=800, command=self.on_slider_change)
        self.frame_slider.pack(pady=10)
        
        if self.nav_frame:
            self.nav_frame.destroy()
        self.nav_frame = tk.Frame(self.root)
        self.nav_frame.pack(pady=5)
        

        tk.Button(self.nav_frame, text="◀", padx=10, pady=5,
        command=lambda: self.goto_frame(-1)).grid(row=0, column=0)

        tk.Label(self.nav_frame, text="Go to Frame:",font=("Arial", 12)).grid(row=0, column=1, padx=5)

        self.frame_entry = tk.Entry(self.nav_frame, width=10, font=("Arial", 12))
        self.frame_entry.insert(0, "1")
        self.frame_entry.grid(row=0, column=2, padx=5)
        self.frame_entry.bind('<Return>', lambda _: self.goto_frame(0))
        self.root.bind('<Left>', lambda _: self.goto_frame(-1))
        self.root.bind('<Right>', lambda _: self.goto_frame(1))

        tk.Button(self.nav_frame, text="Go", command=self.goto_frame, font=("Arial", 12)).grid(row=0, column=3, padx=5)
        tk.Button(self.nav_frame, text="▶", padx=10, pady=5, command=lambda: self.goto_frame(1)).grid(row=0, column=4)

        # Вторая строка
        tk.Label(
           self.nav_frame,
           text="Set how many frames to take from the selection",
           font=("Arial", 12)
        ).grid(row=1, column=0, columnspan=5, pady=(10, 5))

        self.frame_range = tk.Entry(self.nav_frame, width=10, font=("Arial", 12))
        self.frame_range.insert(0, "15")
        self.frame_range.grid(row=2, column=0, columnspan=5)

        

        self.root.title(f"Gait2SFI (Rodent Gait Analyzer) - {self.video_path}")
        
        self.show_first_frame()
        print("Video loaded successfully")  # Debug output

    def on_main_window_close(self):
        print("Closing main window, cleaning up resources")  # Debug output
        if self.cap:
            self.cap.release()
        if self.second_window:
            try:
                self.second_window.destroy()
            except tk.TclError as e:
                print(f"Error destroying second window: {e}")
        if self.frame_slider:
            self.frame_slider.destroy()
        if self.nav_frame:
            self.nav_frame.destroy()
        plt.close(self.fig1)
        if self.fig2:
            plt.close(self.fig2)
        self.root.destroy()
        sys.exit()

    def show_first_frame(self):
        print(f"Showing first frame (frame 0)")  # Debug output
        start_time = time.time()
        if self.canvas1:
            self.canvas1.get_tk_widget().destroy()
        
        if self.cap and self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                # Adjust figure aspect ratio to match video
                aspect_ratio = self.frame_width / self.frame_height
                fig_width = 8
                fig_height = fig_width / aspect_ratio
                self.fig1.set_size_inches(fig_width, fig_height)
                self.ax1.set_aspect('equal')
            else:
                print("Error: Could not read first frame.")
                messagebox.showerror("Error", "Could not read first frame.")
                return
        else:
            print("Error: VideoCapture not initialized.")
            return
            
        self.ax1.clear()
        self.ax1.imshow(frame)
        self.ax1.axis('off')
        self.ax1.set_title(f"Frame {self.current_frame}")
        self.canvas1 = FigureCanvasTkAgg(self.fig1, master=self.root)
        self.canvas1.draw()
        if hasattr(self, 'toolbar') and self.toolbar is not None:
           self.toolbar.destroy()
           
        # The toolbar's save dialog offers canvas.get_default_filename(). An
        # embedded canvas has no figure manager, so matplotlib falls back to a
        # literal "image.png". Point it at the video name and frame instead.
        self.canvas1.get_default_filename = self.main_canvas_filename

        self.toolbar = MyToolbar(self.canvas1, self.root)
        self.toolbar.canvas.draw_idle()
            
        self.canvas1.get_tk_widget().pack(side=tk.TOP)
        self.canvas1.mpl_connect('button_press_event', self.on_press)
        self.canvas1.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas1.mpl_connect('button_release_event', self.on_release)
        
        print(f"First frame displayed in {time.time() - start_time:.3f}s")
        print("First frame displayed and event bindings set")  # Debug output

    def on_press(self, event):
        if event.inaxes != self.ax1 or len(self.rectangles) >= 2 or self.toolbar.mode:
            return
        self.start_x = event.xdata
        self.start_y = event.ydata
        self.current_rect = plt.Rectangle((self.start_x, self.start_y), 0, 0, 
                                        fill=False, edgecolor='red', linewidth=1)
        self.ax1.add_patch(self.current_rect)
        self.canvas1.draw()
        print(f"Started drawing rectangle at ({self.start_x:.1f}, {self.start_y:.1f}) on frame {self.current_frame}")

    def on_motion(self, event):
        if self.current_rect is None or event.inaxes != self.ax1 or self.toolbar.mode:
            return
        width = event.xdata - self.start_x
        height = event.ydata - self.start_y
        self.current_rect.set_width(width)
        self.current_rect.set_height(height)
        self.canvas1.draw()

    def on_release(self, event):
        if self.cap is None or not self.cap.isOpened():
            print("Error: VideoCapture not initialized or closed.")
            return
        if self.current_rect is None or event.inaxes != self.ax1:
            return
        x, y = self.current_rect.get_xy()
        w, h = self.current_rect.get_width(), self.current_rect.get_height()
        x_orig = int(x)
        y_orig = int(y)
        w_orig = int(w)
        h_orig = int(h)
        if w_orig < 0:
            x_orig += w_orig
            w_orig = -w_orig
        if h_orig < 0:
            y_orig += h_orig
            h_orig = -h_orig
        x_orig = max(0, min(x_orig, self.frame_width - 1))
        y_orig = max(0, min(y_orig, self.frame_height - 1))
        w_orig = max(10, min(w_orig, min(400, self.frame_width - x_orig)))
        h_orig = max(10, min(h_orig, min(400, self.frame_height - y_orig)))
        self.rectangles.append((x_orig, y_orig, w_orig, h_orig, self.current_frame))
        self.current_rect = None
        print(f"Fixed area {len(self.rectangles)} at frame {self.current_frame}: {self.rectangles[-1]}")
        
        if len(self.rectangles) == 2:
            valid_areas = True
            for i, rect in enumerate(self.rectangles):
                width = abs(rect[2])
                height = abs(rect[3])
                if width < 10 or height < 10:
                    valid_areas = False
                    print(f"Error: Area {i+1} too small: {width:.1f}x{height:.1f} pixels")
            if valid_areas:
                # Cancel a pending call so a doubled mouse release cannot open
                # two windows at once.
                if self._second_window_job is not None:
                    try:
                        self.root.after_cancel(self._second_window_job)
                    except (tk.TclError, ValueError):
                        pass
                self._second_window_job = self.root.after(500, self.setup_second_window)
            else:
                messagebox.showerror("Error", "Selected areas are too small (must be at least 10x10 pixels).")
                self.rectangles = []
                self.current_rect = None
                self.start_x = None
                self.start_y = None
                self.update_frame()

    def discard_second_window(self):
        """
        Tear down the widgets of an open second window WITHOUT touching the
        selected rectangles, which the caller still needs.
        """
        if self.second_window is None:
            return
        print("Discarding the previous second window before opening a new one")
        for jid in list(self._suppression_jobs):
            try:
                (self.root or self.second_window).after_cancel(jid)
            except (tk.TclError, ValueError):
                pass
        self._suppression_jobs = []
        if self._area_redraw_job is not None:
            try:
                self.second_window.after_cancel(self._area_redraw_job)
            except (tk.TclError, ValueError):
                pass
            self._area_redraw_job = None
        try:
            self.second_window.destroy()
        except tk.TclError:
            pass
        if self.fig2 is not None:
            try:
                plt.close(self.fig2)
            except Exception:
                pass
        self.second_window = None
        self.canvas2 = None
        self.fig2 = None
        self.ax2 = None
        self.area_sliders = [None, None]
        self.area_counter_labels = [None, None]
        self.contrast_slider = None
        self.brightness_slider = None
        self.green_area_button = None
        self.sum_green_area_button = None
        self.sum_frames_entry = None
        self.save_to_image = None
        self.run_sfi_button = None
        self.sfi_status_label = None
        self._expected_slider_value = [None, None]
        self._slider_dragging = [False, False]

    def setup_second_window(self):
        print("Opening second window with two selected areas")
        start_time = time.time()

        # A previous window would otherwise stay on screen with sliders scaled
        # to the OLD frame count, while its callbacks still drive the current
        # state. Dragging such a stale slider caps the position at the old
        # limit - "set 25 frames, the slider throws you back to 15".
        self.discard_second_window()

        self._second_window_job = None

        self.area_pair_counter += 1

        try:
            requested = int(self.frame_range.get())
        except (ValueError, TypeError):
            requested = 15
        if not (2 <= requested <= 100):
            print(f"Invalid frame count {requested!r}, falling back to 15")
            requested = 15
        self.second_wn_frames_limit = requested

        try:
            self.second_window = tk.Toplevel(self.root)
            self.second_window.title(f"Selected Areas (Pair {self.area_pair_counter})")
            
            self.fig2, self.ax2 = plt.subplots(1, 2, figsize=(10, 3))
            self.canvas2 = FigureCanvasTkAgg(self.fig2, master=self.second_window)
            self.canvas2.get_default_filename = self.area_canvas_filename

            self.second_window.protocol("WM_DELETE_WINDOW", self.on_second_window_close)

            # The controls live in one container that is packed BEFORE the
            # canvas. Tk hands out space in packing order, not by 'side', so
            # whatever is packed last is the first thing squeezed out when the
            # window cannot be as tall as the sum of the requested sizes. The
            # canvas asks for a large area, so on a smaller screen the buttons
            # below it - "Run SFI calc" in particular - were pushed outside the
            # visible area and disappeared. Reserving the strip first fixes it;
            # the canvas then takes whatever is left and shrinks instead.
            controls = tk.Frame(self.second_window)
            controls.pack(side=tk.BOTTOM, fill=tk.X)
            self.canvas2.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            
            self.canvas2.mpl_connect('button_press_event', self.on_measure_or_clear)
            
            try:
                self.second_window.bind('<Up>', self.next_area_frame)
                self.second_window.bind('<Down>', self.prev_area_frame)
                print("Successfully bound keyboard events to second window")
            except tk.TclError as e:
                print(f"Error binding keyboard events: {e}")
                messagebox.showerror("Error", f"Failed to bind keyboard events: {e}")
                self.on_second_window_close()
                return
            
            frame_idx1 = self.rectangles[0][4]
            frame_idx2 = self.rectangles[1][4]
            
            # How many frames are actually available after each selection point.
            # Valid frame numbers are 0 .. total_frames-1, so the tail is clamped
            # instead of being padded with duplicated frames.
            avail1 = self.total_frames - frame_idx1
            avail2 = self.total_frames - frame_idx2
            # Each area keeps its own length. Forcing them equal used to
            # truncate a perfectly good selection just because the OTHER one
            # sat close to the end of the recording.
            n1 = min(self.second_wn_frames_limit, avail1)
            n2 = min(self.second_wn_frames_limit, avail2)
            n = max(n1, n2)

            if min(n1, n2) < 1:
                messagebox.showerror(
                    "Error",
                    "Not enough frames after the selection point. "
                    "Choose an earlier frame or reduce the frame count."
                )
                self.on_second_window_close()
                return

            if min(n1, n2) < self.second_wn_frames_limit:
                last = self.total_frames - 1
                print(f"Warning: only {n} frames available instead of "
                      f"{self.second_wn_frames_limit} (end of video reached)")
                messagebox.showwarning(
                    "Fewer frames than requested",
                    f"You asked for {self.second_wn_frames_limit} frames from the "
                    f"selection, but only {n} are available.\n\n"
                    f"The last frame of the video is {last}; the selections start "
                    f"on frames {frame_idx1} (Area 1) and {frame_idx2} (Area 2), "
                    f"which leave {avail1} and {avail2} frames respectively.\n\n"
                    f"Move the selections earlier if you need more frames."
                )

            # Actual/requested counts are shown in the title so the discrepancy
            # stays visible even after the dialog has been dismissed.
            if min(n1, n2) < self.second_wn_frames_limit:
                title_frames = (f"{n1}/{n2} of {self.second_wn_frames_limit} frames"
                                if n1 != n2 else
                                f"{n1}/{self.second_wn_frames_limit} frames")
            else:
                title_frames = f"{n} frames"
            self.second_window.title(
                f"Selected Areas (Pair {self.area_pair_counter}) - {title_frames}")

            # Both lists always have EXACTLY the same length == n,
            # because a single index is used to address both of them.
            self.area1_frame_indices = list(range(frame_idx1, frame_idx1 + n1))
            self.area2_frame_indices = list(range(frame_idx2, frame_idx2 + n2))
            self.n_area_frames = n

            self.area_indices = [0, 0]   # both start on the selected frame

            print(f"Area 1 frame indices: {self.area1_frame_indices}")
            print(f"Area 2 frame indices: {self.area2_frame_indices}")
            print(f"Sliders will span 1..{n1} and 1..{n2}")
            
            # One navigation row per area. The two prints come from different
            # steps of different paws, so coupling them to a single slider was
            # arbitrary: each is refined on its own timeline.
            nav_frame = tk.Frame(controls)
            nav_frame.pack(pady=(6, 2))

            area_names = ["Area 1", "Area 2"]
            lengths = [len(self.area1_frame_indices), len(self.area2_frame_indices)]

            for i in range(2):
                row = tk.Frame(nav_frame)
                row.pack(pady=1)

                tk.Label(row, text=f"{area_names[i]}:", font=("Arial", 11, "bold"),
                         width=7, anchor="e").pack(side=tk.LEFT, padx=(4, 6))
                tk.Button(row, text="◀", padx=8, pady=2,
                          command=lambda a=i: self.goto_area_frame(a, -1)).pack(side=tk.LEFT)

                self.area_counter_labels[i] = tk.Label(
                    row, text=f"1 / {lengths[i]}", font=("Arial", 11, "bold"), width=9)
                self.area_counter_labels[i].pack(side=tk.LEFT, padx=4)

                tk.Button(row, text="▶", padx=8, pady=2,
                          command=lambda a=i: self.goto_area_frame(a, 1)).pack(side=tk.LEFT)

                # Slider is 1-based for the user, area_indices[i] is 0-based.
                self.area_sliders[i] = tk.Scale(
                    row, from_=1, to=max(1, lengths[i]), resolution=1,
                    orient=tk.HORIZONTAL, length=180, showvalue=0,
                    command=lambda v, a=i: self.on_area_slider_change(a, v))
                # No fill/expand: the slider used to stretch to the window width
                self.area_sliders[i].pack(side=tk.LEFT, padx=(8, 6))
                # add='+' keeps Tk's own Scale bindings intact
                self.area_sliders[i].bind('<Button-1>',
                                          lambda e, a=i: self._on_slider_press(a), add='+')
                self.area_sliders[i].bind('<ButtonRelease-1>',
                                          lambda e, a=i: self._on_slider_release(a), add='+')
                self._set_area_slider_silently(i, 1)

            #tk.Label(nav_frame,
            #         text="Arrow keys move both areas together",
            #         font=("Arial", 8), fg="gray40").pack(pady=(2, 0))

            # Bound to the WINDOW, not to a frame: a tk.Frame never takes the
            # keyboard focus, so binding there would never fire.
            self.second_window.bind('<Left>', lambda _: self.step_both_areas(-1))
            self.second_window.bind('<Right>', lambda _: self.step_both_areas(1))
            
            contrast_frame = tk.Frame(controls)
            contrast_frame.pack(pady=5)
            tk.Label(contrast_frame, text="Contrast:", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            self.contrast_slider = tk.Scale(contrast_frame, from_=0.5, to=2.0, resolution=0.1, orient=tk.HORIZONTAL,
                                           length=200, command=self.on_contrast_change)
            self.contrast_slider.set(self.contrast_alpha)
            self.contrast_slider.pack(side=tk.LEFT, padx=5)
            tk.Label(contrast_frame, text="Brightness:", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            self.brightness_slider = tk.Scale(contrast_frame, from_=-100, to=100, resolution=1, orient=tk.HORIZONTAL,
                                            length=200, command=self.on_brightness_change)
            self.brightness_slider.set(self.contrast_beta)
            self.brightness_slider.pack(side=tk.LEFT, padx=5)
            tk.Button(contrast_frame, text="Reset", command=self.reset_lut, font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            
            # Add button for green area calculation
            self.green_area_button = tk.Button(controls, text="Find maximum contact area", 
                                             command=self.calculate_green_area, font=("Arial", 12))
            self.green_area_button.pack(pady=5)

            # Add button for green sum frames + selective frame range
            sum_frame = tk.Frame(controls)
            sum_frame.pack(pady=5)

            self.sum_green_area_button = tk.Button(sum_frame, text="Show total contact area",
                                                   command=self.sum_green_area, font=("Arial", 12))
            self.sum_green_area_button.pack(side=tk.LEFT, padx=5)

            tk.Label(sum_frame, text="Composite footprint:",
                     font=("Arial", 12)).pack(side=tk.LEFT, padx=(10, 2))
            self.sum_frames_entry = tk.Entry(sum_frame, width=16, font=("Arial", 12))
            self.sum_frames_entry.insert(0, f"1-{n}")
            self.sum_frames_entry.pack(side=tk.LEFT, padx=2)
            self.sum_frames_entry.bind('<Return>', lambda _: self.sum_green_area())
            tk.Button(sum_frame, text="All", command=self.reset_frame_selection,
                      font=("Arial", 10)).pack(side=tk.LEFT, padx=2)

            tk.Label(controls,
                     text=f"Format: 1-{n} (range), 1,2,3,8 (list), 1-3,5,8-10 (mixed)",
                     font=("Arial", 9), fg="gray30").pack()
            
            # Add button for saving all distances
            self.save_to_image= tk.Button(controls, text="Save to image", 
                                             command=self.save_all_dist, font=("Arial", 12))
            self.save_to_image.pack(pady=5)

            # Bottom bar: "Run SFI calc" pinned to the bottom-right corner.
            # Packed with side=BOTTOM so it stays at the very bottom no matter
            # how the widgets above are laid out.
            bottom_bar = tk.Frame(controls)
            bottom_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)
            self.run_sfi_button = tk.Button(bottom_bar, text="Run SFI calc",
                                            command=self.run_sfi_calc,
                                            font=("Arial", 12, "bold"),
                                            padx=10, pady=4)
            self.run_sfi_button.pack(side=tk.RIGHT)

            # Shows which SFI field the next measurement will go into, so the
            # user does not have to look back at the calculator window.
            self.sfi_status_label = tk.Label(bottom_bar, text="", font=("Arial", 11, "bold"))
            self.sfi_status_label.pack(side=tk.LEFT)
            if self.sfi_app is not None:
                self.on_sfi_arm_change(getattr(self.sfi_app, 'armed', None))
            
            # Keep the window within the usable screen height: if the layout
            # asks for more than the screen has, the window manager clips the
            # bottom and the controls go with it.
            self.second_window.update_idletasks()
            want_h = self.second_window.winfo_reqheight()
            want_w = self.second_window.winfo_reqwidth()
            avail_h = self.second_window.winfo_screenheight() - 120
            if want_h > avail_h:
                print(f"Second window: layout wants {want_h} px, screen offers "
                      f"{avail_h}; shrinking the image area")
                self.second_window.geometry(f"{want_w}x{avail_h}")
            self.second_window.minsize(600, min(480, want_h))

            self.root.after(600, self.show_initial_areas)
            print(f"Second window setup in {time.time() - start_time:.3f}s")
        except Exception as e:
            print(f"Error setting up second window: {e}")
            messagebox.showerror("Error", f"Failed to setup second window: {e}")
            self.on_second_window_close()

    def on_second_window_close(self):
        print("Closing second window, resetting selection variables")
        if self.second_window:
            # cancel a pending debounced redraw so it cannot fire on a dead window
            if self._area_redraw_job is not None:
                try:
                    self.second_window.after_cancel(self._area_redraw_job)
                except (tk.TclError, ValueError):
                    pass
                self._area_redraw_job = None
            for jid in list(self._suppression_jobs):
                try:
                    (self.root or self.second_window).after_cancel(jid)
                except (tk.TclError, ValueError):
                    pass
            self._suppression_jobs = []
            try:
                self.second_window.destroy()
            except tk.TclError as e:
                print(f"Error destroying second window: {e}")
            self.second_window = None
            self.fig2 = None
            self.ax2 = None
            self.canvas2 = None
            self.area_sliders = [None, None]
            self.area_entry = None
            self.contrast_slider = None
            self.brightness_slider = None
            self.green_area_button = None
            self.sum_green_area_button = None
            self.sum_frames_entry = None
            self.run_sfi_button = None
            self.sfi_status_label = None   # lives in the second window
            self.green_sum_positions = []
            self._last_green_spec = None
            self.invalidate_green_cache()   # new pair of areas -> recompute
            self.frame_override = [None, None]
            self.display_mode = 'frame'
            self.displayed_frames = [None, None]
            self.rectangles = []
            self.selected_areas = []
            self.points = []
            self.distances = []
            self.area1_frame_indices = []
            self.area2_frame_indices = []
            self.area_indices = [0, 0]
            self.n_area_frames = 0
            self.area_counter_labels = [None, None]
            self._expected_slider_value = [None, None]
            self._slider_dragging = [False, False]
            self._suppress_lut_cb = False
            self.contrast_alpha = 1.0
            self.contrast_beta = 0.0
            self.should_apply_lut = False
            self.green_area_values = [None, None]
            self.green_frs = [None, None]
            self.intg_green_frs = [None, None]

        self.update_frame()

    def apply_lut(self, image):
        start_time = time.time()
        adjusted = image
        if self.should_apply_lut:
            adjusted = cv2.convertScaleAbs(image, alpha=self.contrast_alpha, beta=self.contrast_beta)
            print(f"LUT applied (alpha={self.contrast_alpha}, beta={self.contrast_beta}) in {time.time() - start_time:.3f}s")
        else:
            print(f"LUT not applied (using default alpha=1.0, beta=0.0) in {time.time() - start_time:.3f}s")
        return adjusted
        
    @staticmethod
    def _safe_name(text):
        """Strip characters Windows refuses in a file name."""
        cleaned = "".join("_" if c in '<>:"/\\|?*' else c for c in str(text))
        cleaned = cleaned.strip().rstrip(".")
        return cleaned or "frame"

    def video_basename(self):
        if not self.video_path:
            return "video"
        return self._safe_name(os.path.splitext(os.path.basename(self.video_path))[0])

    def area_start_frames(self):
        """Frame each area was selected on - the first frame of its sequence."""
        frames = []
        for i in range(2):
            if i < len(self.rectangles) and len(self.rectangles[i]) >= 5:
                frames.append(int(self.rectangles[i][4]))
        return frames

    def main_canvas_filename(self):
        """Default name offered by the toolbar's save dialog, main window."""
        return f"{self.video_basename()}_frame{self.current_frame}.png"

    def area_image_stem(self):
        """<video>_Pair<N>_A1f<start>_A2f<start> - names the pair and its frames."""
        stem = f"{self.video_basename()}_Pair{self.area_pair_counter}"
        for i, f in enumerate(self.area_start_frames(), 1):
            stem += f"_A{i}f{f}"
        return self._safe_name(stem)

    def area_canvas_filename(self):
        """Default name offered by the toolbar's save dialog, areas window."""
        return f"{self.area_image_stem()}.png"

    def save_all_dist(self):
        """Save the pair of areas, named after the video, the pair number and
        the frame each area was selected on."""
        if self.fig2 is None:
            print("Error: second window figure not initialized")
            return
        path = os.path.abspath(f"{self.area_image_stem()}.png")
        self.fig2.savefig(path,
                  dpi=300,
                  bbox_inches='tight',
                  facecolor='white',
                  edgecolor='none',
                  pad_inches=0.1)
        print(f"Areas saved to: {path}")

    """
    Worse way to detect only green
    def greenness_mask(self, bgr, thr_frac=0.18, blur=3):
        
        b, g, r = cv2.split(bgr.astype(np.float32))
        green = g - cv2.max(r, b)                 # доминирование зелёного
        green = np.clip(green, 0, 255)
        if blur:
          green = cv2.GaussianBlur(green, (blur, blur), 0)
        gmax = float(green.max())
        norm = green / gmax if gmax > 0 else green   # нормировка 0..1
        mask = (norm > thr_frac).astype(np.uint8) * 255
        return norm, mask
    """

    def greenness_mask(self, bgr, green_min=30, v_min=70, blur=3):
        """
        Best way to detect only green
        green_min: min. green dominance over R/B (absolute 0..255) - dampens red
        v_min: min. green channel brightness (absolute 0..255) - dampens DIM
        """
        b, g, r = cv2.split(bgr.astype(np.float32))
        green = np.clip(g - cv2.max(r, b), 0, 255)
        if blur:
           green  = cv2.GaussianBlur(green,  (blur, blur), 0)
           g_blur = cv2.GaussianBlur(g,      (blur, blur), 0)
        else:
           g_blur = g
        # two absolute conditions at once: dominance and brightness
        mask = ((green > green_min) & (g_blur > v_min)).astype(np.uint8) * 255
        norm = np.clip(green / 255.0, 0, 1)   # БЕЗ деления на per-image максимум
        return norm, mask
   

    def hsv_mask(self, bgr, h_lo=35, h_hi=90, s_min=40, v_min=25, blur=3):
        """HSV threshold. h in the range [35..90] ~ green tones (OpenCV: H 0..179)."""
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        lower = np.array([h_lo, s_min, v_min], dtype=np.uint8)
        upper = np.array([h_hi, 255, 255], dtype=np.uint8)
        mask = cv2.inRange(hsv, lower, upper)
        if blur:
           mask = cv2.GaussianBlur(mask, (blur, blur), 0)
           mask = (mask > 127).astype(np.uint8) * 255
        # intensity map = luminance (V), normalized and clipped by mask
        v = hsv[..., 2].astype(np.float32) / 255.0
        norm = np.where(mask > 0, v, 0.0)
        m = norm.max()
        if m > 0:
           norm = norm / m
        return norm, mask


    def clean_up(self, mask, k=3, min_area=20):
       """Morphology: remove noise (opening) and fill holes (closing) + filter out small spots."""
       kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
       mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
       mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
       # screening of small components
       n, lbl, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
       out = np.zeros_like(mask)
       for i in range(1, n):
           if stats[i, cv2.CC_STAT_AREA] >= min_area:
              out[lbl == i] = 255
       return out
  

    

    # ------------------------------------------------------------------
    #  Green processing is split in two stages:
    #    1) ensure_green_cache() - reads every frame of the pair from the
    #       video EXACTLY ONCE and stores the per-frame result.
    #    2) aggregate_green()    - combines cached frames for any selection.
    #  The cache lives as long as the current pair of areas; selecting new
    #  areas on the video invalidates it automatically.
    # ------------------------------------------------------------------

    def _green_cache_key(self):
        """Identifies the current pair of areas + their frame lists."""
        return (self.area_pair_counter,
                tuple(tuple(r) for r in self.rectangles),
                tuple(self.area1_frame_indices),
                tuple(self.area2_frame_indices))

    def invalidate_green_cache(self):
        if self.green_cache is not None:
            print("Green cache invalidated")
        self.green_cache = None
        self.green_cache_key = None

    def ensure_green_cache(self):
        """
        Compute per-frame green data for the whole pair, once.
        Returns True if a usable cache is available.
        """
        key = self._green_cache_key()
        if self.green_cache is not None and self.green_cache_key == key:
            print("Green cache hit - skipping recalculation")
            return True

        if self.cap is None or not self.cap.isOpened():
            print("Error: VideoCapture not initialized or closed.")
            messagebox.showerror("Error", "VideoCapture not initialized or closed.")
            return False

        counts = self.area_frame_counts()
        n = max(counts)
        if min(counts) == 0:
            print("Error: No area frames available")
            return False

        print(f"Green cache miss - processing {counts[0]} + {counts[1]} frames")
        messagebox.showinfo(
            "Processing",
            f"Please wait, analysing {n} frames of this pair...\n"
            "This is done only once - changing the frame selection afterwards is instant."
        )

        start_time = time.time()
        # Each area keeps its own length: the two sequences may differ when one
        # selection sits closer to the end of the recording.
        cache = {
            'green': [[None] * counts[0], [None] * counts[1]],
            'counts': [[0] * counts[0], [0] * counts[1]],
            'frames': [list(self.area1_frame_indices), list(self.area2_frame_indices)],
        }

        try:
            for area_idx in range(2):
                x, y, w, h, _ = self.rectangles[area_idx]
                for p in range(counts[area_idx]):
                    frame_idx = cache['frames'][area_idx][p]
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    ret, frame = self.cap.read()
                    if not ret:
                        print(f"Error: Could not read frame {frame_idx} for area {area_idx + 1}")
                        continue

                    roi = frame[y:y+h, x:x+w]
                    norm, mask = self.greenness_mask(roi)
                    mask = self.clean_up(mask)

                    # keep only the green channel, masked - 3x less memory than a BGR copy
                    green_ch = cv2.bitwise_and(roi[..., 1], mask)
                    cache['green'][area_idx][p] = green_ch
                    cache['counts'][area_idx][p] = int(np.sum(mask > 0))
                    print(f"Frame {frame_idx}, Area {area_idx + 1} green pixels: "
                          f"{cache['counts'][area_idx][p]}")

                    # Debug: Display mask
                    debug_img = np.zeros_like(roi)
                    debug_img[..., 1] = green_ch
                    cv2.imshow(f"Debug Mask Area {area_idx + 1}", debug_img)
                    cv2.waitKey(1)
        finally:
            cv2.destroyAllWindows()

        self.green_cache = cache
        self.green_cache_key = key
        print(f"Green cache built for {counts[0]}+{counts[1]} frames in "
              f"{time.time() - start_time:.3f}s")

        if self.second_window is not None:
            try:
                self.second_window.focus_force()
            except tk.TclError:
                pass
        return True

    def aggregate_green(self, positions):
        """Combine cached frames for the given 0-based positions. No video I/O."""
        cache = self.green_cache
        if cache is None:
            return False

        start_time = time.time()
        self.green_area_values = [0, 0]
        self.green_frs = [0, 0]
        self.intg_green_frs = [None, None]

        for area_idx in range(2):
            acc = None
            total = 0
            best_count = 0
            best_record = 0
            for p in positions:
                # A position may exist in one area and not in the other
                if p >= len(cache['green'][area_idx]):
                    continue
                green_ch = cache['green'][area_idx][p]
                if green_ch is None:
                    continue
                # saturating add: plain '+' on uint8 wraps at 255 and would
                # punch black holes into the brightest contact zones
                acc = green_ch.copy() if acc is None else cv2.add(acc, green_ch)

                count = cache['counts'][area_idx][p]
                total += count
                if count > best_count:
                    best_count = count
                    best_record = [area_idx, cache['frames'][area_idx][p], count]

            if acc is not None:
                rgb = np.zeros((acc.shape[0], acc.shape[1], 3), dtype=np.uint8)
                rgb[..., 1] = acc
                self.intg_green_frs[area_idx] = rgb

            self.green_frs[area_idx] = best_record
            self.green_area_values[area_idx] = total
            print(f"Area {area_idx + 1} total green pixel count: {total} "
                  f"(over {len(positions)} frames)")

        self.green_sum_positions = list(positions)
        self._last_green_spec = self.get_frame_selection_spec()
        print(f"Aggregated from cache in {time.time() - start_time:.3f}s")
        return True

    def calculate_green_area(self):
        """'Find maximum contact area' - uses the cache, computes only on first use."""
        print("Calculating green area for both regions")

        try:
            positions = self.get_selected_frame_positions()
        except ValueError as e:
            print(f"Invalid frame selection: {e}")
            messagebox.showerror("Invalid frame selection", str(e))
            return

        if not self.ensure_green_cache():
            return

        print(f"Using {len(positions)} of {self.area_frame_count()} frames: "
              f"{self.describe_positions(positions)}")
        if not self.aggregate_green(positions):
            return

        # Pin each area to its best-contact frame. This survives redraws
        # (e.g. clearing measurements) until the user navigates.
        for i in range(2):
            rec = self.green_frs[i]
            if isinstance(rec, (list, tuple)) and len(rec) >= 2:
                self.frame_override[i] = rec[1]
                print(f"Area {i+1} pinned to video frame {rec[1]}")

        # Each area now has its own slider, so each one moves to its own
        # maximum - the two no longer have to agree on a single position.
        counts = self.area_frame_counts()
        pinned = self.pinned_positions()
        for i in range(2):
            if pinned[i] is not None:
                self.area_indices[i] = pinned[i]
                self._set_area_slider_silently(i, pinned[i] + 1)
                print(f"Area {i+1}: navigation moved to position "
                      f"{pinned[i] + 1} of {counts[i]}")
        self._update_area_counter_label()

        self.update_area_frames()

    

    def sum_green_area(self):
        print("Adding sum of green frames in second window")
        if self.fig2 is None or self.ax2 is None or self.second_window is None:
            print("Error: Second window figure, axes, or window not initialized")
            return

        if not self.area1_frame_indices or not self.area2_frame_indices:
            print("Error: No area frames available")
            return

        # Validate the selection before doing anything else
        try:
            positions = self.get_selected_frame_positions()
        except ValueError as e:
            print(f"Invalid frame selection: {e}")
            messagebox.showerror("Invalid frame selection", str(e))
            return

        # Build the cache once for this pair, then aggregate (cheap, no video I/O)
        if not self.ensure_green_cache():
            return

        spec_now = self.get_frame_selection_spec()
        if self.intg_green_frs[0] is None or spec_now != self._last_green_spec:
            if not self.aggregate_green(positions):
                return
        else:
            print("Selection unchanged - reusing the current accumulation")
            positions = self.green_sum_positions

        start_time = time.time()
        label = self.describe_positions(positions)

        # Remember which real video frames this accumulation came from
        self.display_mode = 'sum'
        self.displayed_frames = [
            [self.area1_frame_indices[p] for p in positions if p < len(self.area1_frame_indices)],
            [self.area2_frame_indices[p] for p in positions if p < len(self.area2_frame_indices)],
        ]

        for i in range(2):
            if self.intg_green_frs[i] is not None:
               area = self.intg_green_frs[i]
               area = self.apply_lut(area)
               self.ax2[i].clear()
               self.ax2[i].imshow(area, interpolation='bicubic')
               self.ax2[i].set_title(f"Area {i+1} (sum of {len(positions)} frames: {label})", fontsize=9)
               self.ax2[i].axis('off')
               if self.green_area_values[i] is not None:
                  self.ax2[i].text(5, 10, f"Total Green px.: {self.green_area_values[i]} px", color='white', backgroundcolor='black', fontsize=10)
        
        for p1, p2, distance in self.distances:
            p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
            mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
            p1[2].text(mid_x, mid_y, f'{distance:.1f}', color='red', fontsize=14)
            p1[2].axis('off')
        self.draw_canvas()
        print(f"Area frames updated in {time.time() - start_time:.3f}s")
        self.second_window.focus_force()
        
        

    def display_normal_areas(self):
        start_time = time.time()
        self.selected_areas = []
        for i, rect in enumerate(self.rectangles):
            x, y, w, h, frame_idx = rect
            x, y, w, h = int(x), int(y), int(w), int(h)
            x = max(0, min(x, self.frame_width - 1))
            y = max(0, min(y, self.frame_height - 1))
            w = max(10, min(w, self.frame_width - x))
            h = max(10, min(h, self.frame_height - y))
            
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            read_start = time.time()
            ret, frame = self.cap.read()
            print(f"Read frame {frame_idx} in {time.time() - read_start:.3f}s")
            if not ret:
                print(f"Error: Could not read frame {frame_idx} for area {i+1}")
                messagebox.showerror("Error", f"Could not read frame {frame_idx} for area {i+1}")
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            area = frame[y:y+h, x:x+w]
            area = self.apply_lut(area)
            self.ax2[i].clear()
            self.ax2[i].imshow(area, interpolation='bicubic')
            self.ax2[i].set_title(f"Area {i+1} (Frame {frame_idx})")
            self.ax2[i].axis('off')
            if self.green_area_values[i] is not None:
                self.ax2[i].text(5, 10, f"Total Green px.: {self.green_area_values[i]} px", 
                                color='white', backgroundcolor='black', fontsize=10)
            self.selected_areas.append((x, y, w, h))
            print(f"Displayed area {i+1} at frame {frame_idx}: x={x}, y={y}, w={w}, h={h}, shape={area.shape}")
        
        for p1, p2, distance in self.distances:
            p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
            mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
            p1[2].text(mid_x, mid_y, f'{distance:.1f}', color='yellow')
            p1[2].axis('off')

    def update_area_frames(self):
        print("Updating area frames in second window")
        start_time = time.time()
        if self.fig2 is None or self.ax2 is None or self.second_window is None:
            print("Error: Second window figure, axes, or window not initialized")
            return
        
        if min(self.area_frame_counts()) == 0:
            print("Error: No area frames available")
            return

        # Last line of defence: the index can never leave the valid range
        counts = self.area_frame_counts()
        lists = self.area_frame_lists()
        frame_indices = []
        for i in range(2):
            # Last line of defence: an index can never leave its own range
            if not (0 <= self.area_indices[i] < counts[i]):
                print(f"Warning: area {i+1} index {self.area_indices[i]} out of "
                      f"range 0..{counts[i]-1}, clamping")
                self.area_indices[i] = max(0, min(self.area_indices[i], counts[i] - 1))
                self._set_area_slider_silently(i, self.area_indices[i] + 1)
            frame_indices.append(lists[i][self.area_indices[i]])

        print(f"update_area_frames: positions {[p+1 for p in self.area_indices]} "
              f"of {counts}")
        self.selected_areas = []
        num_ar=[0,0]

        for i, (rect, frame_idx) in enumerate(zip(self.rectangles, frame_indices)):
            x, y, w, h, _ = rect
            x, y, w, h = int(x), int(y), int(w), int(h)
            x = max(0, min(x, self.frame_width - 1))
            y = max(0, min(y, self.frame_height - 1))
            w = max(10, min(w, self.frame_width - x))
            h = max(10, min(h, self.frame_height - y))
            
            # A pinned frame (from "Find maximum contact area") wins over the
            # slider position and STAYS pinned across redraws - clearing
            # measurements must not silently jump back to the slider frame.
            pinned = self.frame_override[i] if i < len(self.frame_override) else None
            if pinned is not None:
               self.cap.set(cv2.CAP_PROP_POS_FRAMES, pinned)
               num_ar[i]=pinned
            else:
               self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
               num_ar[i]=frame_idx

            read_start = time.time()
            ret, frame = self.cap.read()
            print(f"Read frame {frame_idx} in {time.time() - read_start:.3f}s")
            if not ret:
                print(f"Error: Could not read frame {frame_idx} for area {i+1}")
                messagebox.showerror("Error", f"Could not read frame {frame_idx} for area {i+1}")
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            area = frame[y:y+h, x:x+w]
            area = self.apply_lut(area)
            self.ax2[i].clear()
            self.ax2[i].imshow(area, interpolation='bicubic')
            self.ax2[i].set_title(f"Area {i+1} (Frame {num_ar[i]})")
            self.ax2[i].axis('off')
            if self.green_area_values[i] is not None:
                self.ax2[i].text(5, 10, f"Total Green px.: {self.green_area_values[i]} px", color='white', backgroundcolor='black', fontsize=10)
            self.selected_areas.append((x, y, w, h))
            print(f"Updated area {i+1} at video frame {num_ar[i]}: shape={area.shape}")

        self.display_mode = 'frame'
        self.displayed_frames = list(num_ar)

        for p1, p2, distance in self.distances:
            p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
            mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
            p1[2].text(mid_x, mid_y, f'{distance:.1f}', color='red', fontsize=14)
            p1[2].axis('off')
        self.draw_canvas()
        print(f"Area frames updated in {time.time() - start_time:.3f}s")

    def on_measure_or_clear(self, event):
        if event.inaxes not in self.ax2.tolist():
            return
        
        start_time = time.time()
        if event.button == 1:
            self.points.append((event.xdata, event.ydata, event.inaxes))
            if len(self.points) == 2:
                p1, p2 = self.points
                if p1[2] == p2[2]:
                    distance = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                    distance = (distance / 10)*3.4  # Short digits; Del it if you want distance in pixels
                    p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
                    mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
                    p1[2].text(mid_x, mid_y, f'{distance:.1f}', color='red', fontsize=14)
                    self.distances.append((p1, p2, distance))
                    p1[2].axis('off')
                    self.draw_canvas()

                    # Which of the two areas was measured (needed for E/N mapping)
                    area_index = None
                    try:
                        area_index = list(self.ax2).index(p1[2])
                    except (ValueError, TypeError):
                        pass
                    self.deliver_measurement_to_sfi(distance, area_index)
                self.points = []
        
        elif event.button == 3:
            print("Clearing measurements in second window")
            self.distances = []
            self.points = []
            # Redraw whatever is currently on screen. Calling update_area_frames()
            # here used to throw away the pinned best-contact frames and the
            # accumulated view, silently jumping back to the slider position.
            self.redraw_current_view()
            print(f"Measurements cleared in {time.time() - start_time:.3f}s")

    def redraw_current_view(self):
        """Re-render the second window without changing which frames are shown."""
        if self.display_mode == 'sum' and self.intg_green_frs[0] is not None:
            self.sum_green_area()
        else:
            self.update_area_frames()

    def last_frame_index(self):
        """Highest valid frame number: a 200-frame clip is 0..199."""
        return max(0, self.total_frames - 1)

    def _set_frame_slider_silently(self, value):
        """Value-based guard, for the same reason as the area sliders."""
        if self.frame_slider is None:
            return
        self._expected_frame_slider_value = int(value)
        self.frame_slider.set(int(value))

    def set_current_frame(self, index):
        """Single clamped entry point for main-window navigation."""
        if self.total_frames <= 0:
            return
        index = max(0, min(int(index), self.last_frame_index()))
        if index == self.current_frame:
            return
        self.current_frame = index
        self._set_frame_slider_silently(index)
        if self.frame_entry:
            self.frame_entry.delete(0, tk.END)
            self.frame_entry.insert(0, str(index))
        self.update_frame()

    def _schedule_main_redraw(self, delay_ms=80):
        """Debounce the main slider so the released position is always drawn."""
        if self.root is None:
            return
        if self._main_redraw_job is not None:
            try:
                self.root.after_cancel(self._main_redraw_job)
            except (tk.TclError, ValueError):
                pass
        self._main_redraw_job = self.root.after(delay_ms, self._do_main_redraw)

    def _do_main_redraw(self):
        self._main_redraw_job = None
        self.update_frame()

    def on_slider_change(self, value):
        new_index = max(0, min(int(float(value)), self.last_frame_index()))

        if self._expected_frame_slider_value == new_index:
            self._expected_frame_slider_value = None
            return
        if new_index == self.current_frame:
            return
        self.last_update_time = time.time()
        self.current_frame = new_index
        if self.frame_entry:
            self.frame_entry.delete(0, tk.END)
            self.frame_entry.insert(0, str(new_index))
        # Postponed, not skipped: the old throttle dropped the update entirely,
        # so current_frame and the picture on screen could disagree.
        self._schedule_main_redraw()

    def goto_frame(self, way=0):
        """way = -1 back, +1 forward, 0 = jump to the number typed in the box."""
        if way in (-1, 1):
            target = self.current_frame + way
            if not (0 <= target <= self.last_frame_index()):
                # Frame 0 used to be unreachable going forward: the guard read
                # "0 < current_frame", so stepping on from frame 0 did nothing.
                print(f"Already at the edge (frame {self.current_frame} "
                      f"of 0..{self.last_frame_index()})")
                return
            self.last_update_time = time.time()
            self.set_current_frame(target)
            return

        try:
            frame_num = int(self.frame_entry.get())
        except (ValueError, AttributeError):
            messagebox.showerror("Error", "Please enter a valid frame number")
            return

        if not (0 <= frame_num <= self.last_frame_index()):
            messagebox.showerror(
                "Error", f"Frame number must be between 0 and {self.last_frame_index()}")
            return
        self.last_update_time = time.time()
        self.set_current_frame(frame_num)


    # ------------------------------------------------------------------
    #  Second-window navigation helpers
    #  Single source of truth: self.area_indices[area], 0-based,
    #  always in the range 0 .. n_area_frames-1.
    #  The slider shows index+1 (1..n) so that the user sees 1-based numbers.
    # ------------------------------------------------------------------

    def area_frame_lists(self):
        return [self.area1_frame_indices, self.area2_frame_indices]

    def area_frame_counts(self):
        """Length of each area's own sequence; the two may differ."""
        return [len(self.area1_frame_indices), len(self.area2_frame_indices)]

    def area_frame_count(self, area=None):
        """
        Frames available for one area, or - when no area is given - the longest
        of the two. Kept for the places that only need "is there anything here".
        """
        counts = self.area_frame_counts()
        if area is None:
            return max(counts) if counts else 0
        return counts[area] if 0 <= area < len(counts) else 0

    def _clear_suppression_later(self, attr):
        """
        tk.Scale fires its -command asynchronously, on the next trip through the
        event loop - clearing the guard right after .set() would let that
        deferred callback through. after_idle runs after the Scale command,
        so the flag is released at exactly the right moment.
        """
        # Scheduled on the root window, which outlives the second window:
        # a pending idle callback on a destroyed widget makes Tk complain.
        win = self.root if self.root is not None else self.second_window
        if win is None:
            setattr(self, attr, False)
            return

        holder = {}

        def clear():
            setattr(self, attr, False)
            jid = holder.get('id')
            if jid in self._suppression_jobs:
                self._suppression_jobs.remove(jid)

        try:
            holder['id'] = win.after_idle(clear)
            self._suppression_jobs.append(holder['id'])
        except tk.TclError:
            setattr(self, attr, False)

    def _set_area_slider_silently(self, area, slider_value):
        """
        Move one area's slider without reacting to the callback it will fire.

        The guard is on the VALUE, not on a time window. tk.Scale fires its
        -command asynchronously, so a flag set around .set() and cleared on the
        next idle cycle stays raised for a short while afterwards. If the user
        grabbed the slider during that window their drag events were silently
        discarded: the widget had moved but the index had not, and the next
        redraw wrote the stale index back - the slider appeared to snap back.
        Remembering the value we wrote and ignoring exactly that one callback
        removes the timing dependency altogether.
        """
        slider = self.area_sliders[area] if area < len(self.area_sliders) else None
        if slider is None:
            return

        # Never reposition a handle the pointer is holding. A long redraw - a
        # 4K seek can take hundreds of milliseconds - blocks the event loop,
        # and any programmatic move that lands in that window would yank the
        # handle out from under the user and look like the slider jumping back.
        if self._slider_dragging[area]:
            print(f"Area {area + 1}: slider is being dragged, not moving it")
            return

        self._expected_slider_value[area] = int(slider_value) - 1   # store 0-based
        slider.set(int(slider_value))

    def _on_slider_press(self, area):
        self._slider_dragging[area] = True
        # Drop any stale expectation: if a programmatic set had left one
        # unconsumed, it would swallow one of the user's own drag events.
        self._expected_slider_value[area] = None

    def _on_slider_release(self, area):
        """
        Widget bindings run BEFORE class bindings in Tk, so at this point
        tk::ScaleButtonUp has not finished and the widget may still hold an
        intermediate value from the middle of the drag. Reading it here and
        forcing the state onto it moved the displayed frame backwards while
        the handle stayed where the user left it. The read is therefore
        deferred until Tk has settled.
        """
        self._slider_dragging[area] = False
        win = self.root if self.root is not None else self.second_window
        if win is None:
            self._sync_slider_after_release(area)
            return
        try:
            win.after_idle(lambda a=area: self._sync_slider_after_release(a))
        except tk.TclError:
            self._sync_slider_after_release(area)

    def _sync_slider_after_release(self, area):
        """Adopt the position the handle actually ended on."""
        slider = self.area_sliders[area] if area < len(self.area_sliders) else None
        if slider is None:
            return
        try:
            landed = int(float(slider.get())) - 1
        except (tk.TclError, ValueError):
            return
        n = self.area_frame_count(area)
        if not n:
            return
        landed = max(0, min(landed, n - 1))
        if landed == self.area_indices[area]:
            return
        print(f"Area {area + 1}: re-syncing to the released position "
              f"{landed + 1} (state was {self.area_indices[area] + 1})")
        self.area_indices[area] = landed
        self.release_frame_override(area, "slider release")
        self.display_mode = 'frame'
        self._update_area_counter_label(area)
        self._schedule_area_redraw()

    def pinned_positions(self):
        """
        Position of each pinned frame inside its own selection, 1-based on
        display. Returns [None, None] when nothing is pinned.
        """
        lists = [self.area1_frame_indices, self.area2_frame_indices]
        out = []
        for i in range(2):
            frame = self.frame_override[i] if i < len(self.frame_override) else None
            if frame is None or i >= len(lists) or frame not in lists[i]:
                out.append(None)
            else:
                out.append(lists[i].index(frame))
        return out

    def _update_area_counter_label(self, area=None):
        """Refresh one counter, or both when no area is given."""
        targets = range(2) if area is None else [area]
        counts = self.area_frame_counts()
        for i in targets:
            label = self.area_counter_labels[i] if i < len(self.area_counter_labels) else None
            if label is None:
                continue
            text = f"{self.area_indices[i] + 1} / {counts[i]}"
            # A pinned frame is marked, so it is obvious that the position was
            # chosen by "Find maximum contact area" rather than by hand.
            if self.frame_override[i] is not None:
                text += " \u2605"
            try:
                label.config(text=text)
            except tk.TclError:
                pass

    def _reset_lut_silently(self):
        """Reset contrast/brightness without the slider callbacks re-enabling the LUT."""
        self.should_apply_lut = False
        self.contrast_alpha = 1.0
        self.contrast_beta = 0.0
        self._suppress_lut_cb = True
        try:
            if self.contrast_slider:
                self.contrast_slider.set(self.contrast_alpha)
            if self.brightness_slider:
                self.brightness_slider.set(self.contrast_beta)
        finally:
            self._clear_suppression_later('_suppress_lut_cb')

    def set_area_index(self, area, index, wrap=False, redraw=True):
        """Central entry point for moving ONE area to a position in its sequence."""
        n = self.area_frame_count(area)
        if n == 0:
            print(f"Area {area + 1}: no frames available for navigation")
            return

        if wrap:
            index = index % n
        else:
            index = max(0, min(int(index), n - 1))

        if index == self.area_indices[area] and self.frame_override[area] is None:
            self._update_area_counter_label(area)
            return

        self.area_indices[area] = index
        # Moving an area is the ONLY thing that releases ITS pinned frame; the
        # other area keeps whatever it was showing. Contrast and brightness
        # survive a frame change and are cleared only by their Reset button.
        self.release_frame_override(area, "navigation")
        self.display_mode = 'frame'   # navigating leaves the accumulated view
        self._set_area_slider_silently(area, index + 1)
        self._update_area_counter_label(area)
        if redraw:
            self.update_area_frames()

    def _focus_handles_arrows(self):
        """
        True when the focused widget reacts to arrow keys on its own.

        Widget bindings run before toplevel bindings in Tk, so a focused Scale
        moves itself AND then the window-level binding fires - one key press
        advanced the area twice.
        """
        try:
            widget = self.second_window.focus_get()
        except (tk.TclError, AttributeError):
            return False
        return isinstance(widget, (tk.Scale, tk.Entry, tk.Spinbox))

    def step_both_areas(self, way):
        """Keyboard arrows: move both areas together, as a quick scan."""
        if self._focus_handles_arrows():
            return
        moved = False
        for i in range(2):
            target = self.area_indices[i] + int(way)
            if 0 <= target < self.area_frame_count(i):
                self.set_area_index(i, target, redraw=False)
                moved = True
        if moved:
            self.update_area_frames()

    def release_frame_override(self, area=None, reason=""):
        """Drop the pinned frame of one area, or of both when none is given."""
        targets = range(2) if area is None else [area]
        for i in targets:
            if self.frame_override[i] is not None:
                print(f"Area {i + 1}: releasing pinned frame ({reason})")
                self.frame_override[i] = None

    def _schedule_area_redraw(self, delay_ms=80):
        """Debounce: while the slider is dragged only the last position is rendered."""
        if self.second_window is None or not self.second_window.winfo_exists():
            return
        if self._area_redraw_job is not None:
            try:
                self.second_window.after_cancel(self._area_redraw_job)
            except (tk.TclError, ValueError):
                pass
        self._area_redraw_job = self.second_window.after(delay_ms, self._do_area_redraw)

    def _do_area_redraw(self):
        self._area_redraw_job = None
        self._update_area_counter_label()
        self.redraw_current_view()

    def on_area_slider_change(self, area, value):
        n = self.area_frame_count(area)
        if n == 0:
            return

        # Slider is 1-based -> internal index is 0-based
        new_index = max(0, min(int(float(value)) - 1, n - 1))

        # Swallow exactly the callback caused by our own .set(), and only that
        # one. Any other value is a real user action, whenever it arrives.
        if self._expected_slider_value[area] == new_index:
            self._expected_slider_value[area] = None
            return

        if new_index == self.area_indices[area] and self.frame_override[area] is None:
            return

        self.last_update_time = time.time()
        self.area_indices[area] = new_index
        self.release_frame_override(area, "slider")
        self.display_mode = 'frame'
        self._update_area_counter_label(area)
        # No frames are dropped any more: the redraw is postponed, not skipped,
        # so the position the user releases the slider on is always rendered.
        self._schedule_area_redraw()

    def goto_area_frame(self, area, way=0):
        """way = -1 previous frame, +1 next frame. No wrap-around at the edges."""
        n = self.area_frame_count(area)
        if n == 0:
            print(f"Area {area + 1}: no frames available for navigation")
            return
        if way == 0:
            return

        target = self.area_indices[area] + int(way)
        if not (0 <= target < n):
            print(f"Area {area + 1}: edge of the selection reached "
                  f"(index {self.area_indices[area]}, range 0..{n - 1})")
            return

        self.last_update_time = time.time()
        self.set_area_index(area, target, wrap=False)

    # ------------------------------------------------------------------
    #  Selective summation: which frames of the selection to accumulate
    # ------------------------------------------------------------------

    @staticmethod
    def parse_frame_selection(spec, n):
        """
        Parse a user-typed frame selection into 0-based positions.

        Accepted syntax (numbers are 1-based positions inside the selection):
            "1-15"        -> all frames from 1 to 15
            "1-8"         -> frames 1..8
            "1,2,3,8"     -> only those four frames
            "1-3,5,8-10"  -> ranges and single frames can be mixed
            ""            -> all n frames

        Returns a sorted list of 0-based indices.
        Raises ValueError with a human-readable message on bad input.
        """
        if n <= 0:
            raise ValueError("No frames available in the selection.")

        spec = "" if spec is None else str(spec).strip()
        # tolerate spaces, en/em dashes and semicolons as separators
        spec = spec.replace(" ", "").replace("\u2013", "-").replace("\u2014", "-").replace(";", ",")
        if not spec:
            return list(range(n))

        positions = set()
        for token in spec.split(","):
            if not token:
                continue
            if "-" in token:
                parts = token.split("-")
                if len(parts) != 2 or not parts[0] or not parts[1]:
                    raise ValueError(f"Invalid range: '{token}'. Use the form 1-8.")
                try:
                    start, end = int(parts[0]), int(parts[1])
                except ValueError:
                    raise ValueError(f"Invalid range: '{token}'. Use the form 1-8.")
                if start > end:
                    start, end = end, start
                positions.update(range(start, end + 1))
            else:
                try:
                    positions.add(int(token))
                except ValueError:
                    raise ValueError(f"Invalid frame number: '{token}'.")

        bad = sorted(p for p in positions if not (1 <= p <= n))
        if bad:
            shown = ", ".join(str(b) for b in bad[:8])
            raise ValueError(f"Frame(s) out of range: {shown}. Allowed range is 1-{n}.")

        if not positions:
            raise ValueError("The frame selection is empty.")

        return sorted(p - 1 for p in positions)

    def get_frame_selection_spec(self):
        """Raw text currently typed in the selection field."""
        if self.sum_frames_entry is None:
            return ""
        try:
            return self.sum_frames_entry.get().strip()
        except tk.TclError:
            return ""

    def get_selected_frame_positions(self):
        """0-based positions to accumulate. Raises ValueError on invalid input."""
        return self.parse_frame_selection(self.get_frame_selection_spec(), self.area_frame_count())

    @staticmethod
    def compact_numbers(nums):
        """Compact a list of integers into ranges: [7,8,9,14] -> '7-9,14'."""
        nums = sorted(set(int(v) for v in nums))
        if not nums:
            return "-"
        parts, start, prev = [], nums[0], nums[0]
        for v in nums[1:] + [None]:
            if v is not None and v == prev + 1:
                prev = v
                continue
            parts.append(str(start) if start == prev else f"{start}-{prev}")
            if v is not None:
                start = prev = v
        return ",".join(parts)

    @staticmethod
    def describe_positions(positions):
        """Compact form of a position list, 1-based for display: [0,1,2,7] -> '1-3,8'."""
        if not positions:
            return "-"
        return Gait2SFI.compact_numbers(p + 1 for p in positions)

    def reset_frame_selection(self):
        """'All' button: restore the full range."""
        if self.sum_frames_entry is None:
            return
        n = self.area_frame_count()
        self.sum_frames_entry.delete(0, tk.END)
        self.sum_frames_entry.insert(0, f"1-{n}" if n > 0 else "")
        print(f"Frame selection reset to 1-{n}")

    # ------------------------------------------------------------------
    #  Launching the companion SFI.py script
    # ------------------------------------------------------------------

    @staticmethod
    def get_script_dir():
        """Folder this program lives in (works for a plain script and a frozen exe)."""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))

    def _load_sfi_module(self):
        """Import SFI.py from the folder this program lives in."""
        script_path = os.path.join(self.get_script_dir(), "SFI.py")
        if not os.path.isfile(script_path):
            return None, script_path
        spec = importlib.util.spec_from_file_location("sfi_calc", script_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, script_path

    @staticmethod
    def _supports_measure_link(module):
        """True if this SFI.py understands the embedded measurement protocol."""
        app = getattr(module, "Application", None)
        if app is None:
            return False
        try:
            params = inspect.signature(app.__init__).parameters
        except (TypeError, ValueError):
            return False
        return "measure_link" in params and hasattr(app, "receive_measurement")

    def run_sfi_calc(self):
        """Open the SFI calculator as a panel of THIS process, so measurements
        can be pushed straight into its fields (no IPC, no polling)."""
        # Already open - just bring it forward
        if self.sfi_window is not None:
            try:
                if self.sfi_window.winfo_exists():
                    self.sfi_window.deiconify()
                    self.sfi_window.lift()
                    self.sfi_window.focus_force()
                    return
            except tk.TclError:
                pass
            self.sfi_window = None
            self.sfi_app = None

        try:
            module, script_path = self._load_sfi_module()
        except Exception as e:
            print(f"Error importing SFI.py: {e}")
            messagebox.showerror("Error", f"Could not load SFI.py:\n{e}")
            return

        if module is None:
            messagebox.showerror(
                "SFI.py not found",
                f"SFI.py must be in the same folder as Gait2SFI.\n\nExpected:\n{script_path}"
            )
            return

        if not self._supports_measure_link(module):
            # Old SFI.py without the link protocol - keep it usable as a separate process
            print("SFI.py has no measurement link, falling back to a separate process")
            self.launch_sfi_subprocess(script_path)
            return

        self.sfi_window = tk.Toplevel(self.root)
        self.sfi_window.title("SFI calc")
        self.sfi_window.wm_minsize(320, 700)
        self.sfi_window.protocol("WM_DELETE_WINDOW", self.on_sfi_window_close)

        # Park it next to the second window so both are visible at once
        try:
            if self.second_window is not None and self.second_window.winfo_exists():
                self.second_window.update_idletasks()
                x = self.second_window.winfo_x() + self.second_window.winfo_width() + 12
                y = self.second_window.winfo_y()
                self.sfi_window.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass

        self.sfi_app = module.Application(
            master=self.sfi_window,
            measure_link=True,
            on_arm_change=self.on_sfi_arm_change,
            context_provider=self.get_sfi_context,
        )
        self.sfi_app.arm_field('epl')  # ready for the first measurement immediately
        print("SFI calc panel opened in-process")

    def launch_sfi_subprocess(self, script_path):
        """Legacy path: run SFI.py as a separate process (no measurement link)."""
        if self.sfi_process is not None and self.sfi_process.poll() is None:
            messagebox.showwarning("SFI calc", "SFI.py is already running.")
            return
        python_exe = sys.executable
        if getattr(sys, 'frozen', False) or not python_exe:
            python_exe = "python" if os.name == "nt" else "python3"
        try:
            self.sfi_process = subprocess.Popen([python_exe, script_path])
            print(f"SFI.py started as a separate process (pid {self.sfi_process.pid})")
        except Exception as e:
            print(f"Error starting SFI.py: {e}")
            messagebox.showerror("Error", f"Could not start SFI.py:\n{e}")

    def on_sfi_window_close(self):
        print("Closing SFI calc panel")
        self.sfi_app = None
        if self.sfi_window is not None:
            try:
                self.sfi_window.destroy()
            except tk.TclError:
                pass
        self.sfi_window = None
        self.set_sfi_status("")

    def on_sfi_arm_change(self, field_name):
        """Called by the SFI panel whenever the armed field changes."""
        if field_name:
            self.set_sfi_status(f"Measuring: {field_name.upper()}", "#00695c")
        else:
            self.set_sfi_status("")

    def set_sfi_status(self, text, colour="gray25"):
        if self.sfi_status_label is None:
            return
        try:
            self.sfi_status_label.config(text=text, fg=colour)
        except tk.TclError:
            pass

    def describe_displayed_frames(self):
        """
        Global video frame numbers currently shown, per area, e.g.
          single frames    -> 'A1:1234 A2:1456'
          accumulated view -> 'A1:1230-1232,1237 A2:1450-1452,1457'
        These are the frames the footprint was actually measured on.
        """
        parts = []
        for i, shown in enumerate(self.displayed_frames):
            if shown is None:
                continue
            if isinstance(shown, (list, tuple)):
                if not shown:
                    continue
                parts.append(f"A{i+1}:{self.compact_numbers(shown)}")
            else:
                parts.append(f"A{i+1}:{int(shown)}")
        return " ".join(parts)

    def get_sfi_context(self):
        """Extra provenance columns for the SFI CSV."""
        video = ""
        if self.video_path:
            video = os.path.basename(self.video_path)
        return {'FILE': video,
                'Pair': self.area_pair_counter,
                'Frames': self.describe_displayed_frames()}

    def deliver_measurement_to_sfi(self, value, area_index=None):
        """Push a completed measurement into the armed field of the SFI panel."""
        if self.sfi_app is None or self.sfi_window is None:
            return False
        try:
            if not self.sfi_window.winfo_exists():
                self.sfi_app = None
                self.sfi_window = None
                return False
            return bool(self.sfi_app.receive_measurement(value, area_index))
        except Exception as e:
            print(f"Could not deliver the measurement to SFI calc: {e}")
            return False

    def update_frame(self):
        print(f"Updating frame {self.current_frame}")  # Debug output
        start_time = time.time()
        if self.cap is None or not self.cap.isOpened():
            print("Error: VideoCapture not initialized or closed.")
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
        read_start = time.time()
        ret, frame = self.cap.read()
        print(f"Read frame {self.current_frame} in {time.time() - read_start:.3f}s")
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Adjust figure aspect ratio to match video
            aspect_ratio = self.frame_width / self.frame_height
            fig_width = 8
            fig_height = fig_width / aspect_ratio
            self.fig1.set_size_inches(fig_width, fig_height)
            self.ax1.set_aspect('equal')
        else:
            print(f"Error: Could not read frame {self.current_frame}")
            messagebox.showerror("Error", f"Could not read frame {self.current_frame}")
            return
        
        self.ax1.clear()
        self.ax1.imshow(frame)
        self.ax1.axis('off')
        self.ax1.set_title(f"Frame {self.current_frame}")
        if len(self.rectangles) == 2:
            for x, y, w, h, frame_idx in self.rectangles:
                self.ax1.add_patch(plt.Rectangle((x, y), w, h, 
                                               fill=False, edgecolor='red', linewidth=2))
        self.canvas1.draw()
        print(f"Updated frame {self.current_frame} with {len(self.rectangles)} fixed areas in {time.time() - start_time:.3f}s")

    def next_area_frame(self, event=None):
        # Up arrow: cyclic navigation of both areas
        if self._focus_handles_arrows():
            return
        if self.area_frame_count() == 0:
            print("No area frames available for navigation")
            return
        self.last_update_time = time.time()
        for i in range(2):
            if self.area_frame_count(i):
                self.set_area_index(i, self.area_indices[i] + 1, wrap=True, redraw=False)
        self.update_area_frames()

    def prev_area_frame(self, event=None):
        # Down arrow: cyclic navigation of both areas
        if self._focus_handles_arrows():
            return
        if self.area_frame_count() == 0:
            print("No area frames available for navigation")
            return
        self.last_update_time = time.time()
        for i in range(2):
            if self.area_frame_count(i):
                self.set_area_index(i, self.area_indices[i] - 1, wrap=True, redraw=False)
        self.update_area_frames()

    def run(self):
        print("Starting main loop")
        try:
            print("Entering tkinter mainloop")
            self.root.mainloop()
            print("Exited tkinter mainloop")
        except Exception as e:
            print(f"Error in tkinter mainloop: {e}")
            self.on_main_window_close()

    def draw_canvas(self):
        start_time = time.time()
        if self.canvas2 and self.second_window and self.second_window.winfo_exists():
            try:
                self.canvas2.draw()
                print(f"Second window canvas drawn in {time.time() - start_time:.3f}s")
            except Exception as e:
                print(f"Error drawing second window canvas: {e}")
                messagebox.showerror("Error", f"Failed to draw areas: {e}")

    def show_initial_areas(self):
        start_time = time.time()
        if self.fig2 is None or self.ax2 is None or self.second_window is None:
            print("Error: Second window figure, axes, or window not initialized")
            return
        
        self.selected_areas = []
        self.display_normal_areas()
        self.draw_canvas()
        print(f"Initial areas displayed in {time.time() - start_time:.3f}s")

    def on_contrast_change(self, value):
        if self._suppress_lut_cb:
            return
        self.last_update_time = time.time()
        self.contrast_alpha = float(value)
        self.should_apply_lut = True  # Enable LUT application
        print(f"Contrast changed to alpha={self.contrast_alpha}, LUT will be applied")
        # Debounced instead of skipped: the value the slider is released on
        # is always the one that gets rendered.
        self._schedule_area_redraw()

    def on_brightness_change(self, value):
        if self._suppress_lut_cb:
            return
        self.last_update_time = time.time()
        self.contrast_beta = float(value)
        self.should_apply_lut = True  # Enable LUT application
        print(f"Brightness changed to beta={self.contrast_beta}, LUT will be applied")
        self._schedule_area_redraw()

    def reset_lut(self):
        """The ONLY thing that clears contrast/brightness. Frame changes do not."""
        print("Resetting LUT parameters")
        # _reset_lut_silently suppresses the slider callbacks; setting the
        # sliders directly used to fire on_contrast_change and switch
        # should_apply_lut straight back on, plus cause a second redraw.
        self._reset_lut_silently()
        self.redraw_current_view()

if __name__ == "__main__":
    print("Starting application")
    app = Gait2SFI()
    app.run()
    print("Application ended")
