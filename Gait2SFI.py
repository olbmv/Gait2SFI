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
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import time
import sys

class RatGaitAnalyzer:
    def __init__(self):
        print("Initializing Gait2SFI")  # Debug output
        self.root = tk.Tk()
        self.root.title("Gait2SFI")
        
        # Video handling
        self.video_path = None
        self.cap = None
        self.current_frame = 0
        self.total_frames = 0
        self.last_update_time = 0
        self.update_interval = 0.1  # Limit updates to ~10 fps
        self.area1_frame_indices = []  # Indices for area 1 frames (no caching)
        self.area2_frame_indices = []  # Indices for area 2 frames (no caching)
        self.current_area_index = 0  # Current index for navigation
        self.area_pair_counter = 0  # Counter for selected area pairs
        
        # Selection variables
        self.rectangles = []  # List of (x, y, w, h, frame_idx) in original size
        self.current_rect = None
        self.start_x = None
        self.start_y = None
        self.selected_areas = []
        
        # Measurement variables
        self.points = []
        self.distances = []
        
        # GUI elements
        self.fig1, self.ax1 = plt.subplots(figsize=(8, 6), dpi=150)
        self.canvas1 = None
        self.fig2 = None
        self.ax2 = None
        self.canvas2 = None
        self.second_window = None
        self.frame_slider = None  # Slider for main window
        self.frame_entry = None  # Entry for frame number
        self.area_slider = None  # Slider for second window
        self.area_entry = None  # Entry for area frame offset
        
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
        
        # Frame navigation controls
        nav_frame = tk.Frame(self.root)
        nav_frame.pack(pady=5)
        tk.Label(nav_frame, text="Go to Frame:", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
        self.frame_entry = tk.Entry(nav_frame, width=10, font=("Arial", 12))
        self.frame_entry.pack(side=tk.LEFT, padx=5)
        self.frame_entry.bind('<Return>', self.goto_frame)  # Bind Enter key
        tk.Button(nav_frame, text="Go", command=self.goto_frame, font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
        
        print("File dialog and navigation controls setup complete")  # Debug output

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
        if self.cap:
            self.cap.release()
            
        self.cap = cv2.VideoCapture(self.video_path, cv2.CAP_FFMPEG)
        if not self.cap.isOpened():
            print("Error: Could not open video file. Check FFmpeg and video format.")
            messagebox.showerror("Error", "Could not open video file. Check FFmpeg and video format.")
            return    
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.current_frame = 0
        self.area1_frame_indices = []
        self.area2_frame_indices = []
        self.current_area_index = 0
        self.area_pair_counter = 0
        self.rectangles = []
        self.selected_areas = []
        self.points = []
        self.distances = []
        self.start_x = None
        self.start_y = None
        self.current_rect = None
        
        if self.second_window:
            try:
                self.second_window.destroy()
            except tk.TclError as e:
                print(f"Error destroying second window: {e}")
            self.second_window = None
            self.fig2 = None
            self.ax2 = None
            self.canvas2 = None
            self.area_slider = None
            self.area_entry = None
        
        # Setup slider for main window
        if self.frame_slider:
            self.frame_slider.destroy()
        self.frame_slider = tk.Scale(self.root, from_=0, to=self.total_frames-1, orient=tk.HORIZONTAL,
                                    length=800, command=self.on_slider_change)
        self.frame_slider.pack(pady=10)
        
        self.root.title(f"Gait2SFI - {self.video_path}")
        
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
        if self.frame_entry:
            self.frame_entry.destroy()
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
        
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = self.cap.read()
        if ret:
            frame = cv2.resize(frame, None, fx=0.5, fy=0.5)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            print("Error: Could not read first frame.")
            messagebox.showerror("Error", "Could not read first frame.")
            return
            
        self.ax1.clear()
        self.ax1.imshow(frame)
        self.ax1.axis('off')
        self.ax1.set_title(f"Frame {self.current_frame}")
        self.canvas1 = FigureCanvasTkAgg(self.fig1, master=self.root)
        self.canvas1.draw()
        self.canvas1.get_tk_widget().pack()
        
        self.canvas1.mpl_connect('button_press_event', self.on_press)
        self.canvas1.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas1.mpl_connect('button_release_event', self.on_release)
        
        print(f"First frame displayed in {time.time() - start_time:.3f}s")
        print("First frame displayed and event bindings set")  # Debug output

    def on_press(self, event):
        if event.inaxes != self.ax1 or len(self.rectangles) >= 2:
            return
        self.start_x = event.xdata
        self.start_y = event.ydata
        self.current_rect = plt.Rectangle((self.start_x, self.start_y), 0, 0, 
                                        fill=False, edgecolor='red', linewidth=2)
        self.ax1.add_patch(self.current_rect)
        self.canvas1.draw()
        print(f"Started drawing rectangle at ({self.start_x:.1f}, {self.start_y:.1f}) on frame {self.current_frame}")

    def on_motion(self, event):
        if self.current_rect is None or event.inaxes != self.ax1:
            return
        width = event.xdata - self.start_x
        height = event.ydata - self.start_y
        self.current_rect.set_width(width)
        self.current_rect.set_height(height)
        self.canvas1.draw()

    def on_release(self, event):
        if self.current_rect is None or event.inaxes != self.ax1:
            return
        x, y = self.current_rect.get_xy()
        w, h = self.current_rect.get_width(), self.current_rect.get_height()
        x_orig = int(x / 0.5)
        y_orig = int(y / 0.5)
        w_orig = int(w / 0.5)
        h_orig = int(h / 0.5)
        if w_orig < 0:
            x_orig += w_orig
            w_orig = -w_orig
        if h_orig < 0:
            y_orig += h_orig
            h_orig = -h_orig
        x_orig = max(0, min(x_orig, self.frame_width - 1))
        y_orig = max(0, min(y_orig, self.frame_height - 1))
        w_orig = max(10, min(w_orig, min(400, self.frame_width - x_orig)))  # Increased limit
        h_orig = max(10, min(h_orig, min(400, self.frame_height - y_orig)))  # Increased limit
        self.rectangles.append((x_orig, y_orig, w_orig, h_orig, self.current_frame))
        self.current_rect = None
        # Do not call update_frame to avoid showing the first rectangle
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
                self.root.after(500, self.setup_second_window)
            else:
                messagebox.showerror("Error", "Selected areas are too small (must be at least 10x10 pixels).")
                self.rectangles = []
                self.current_rect = None
                self.start_x = None
                self.start_y = None
                self.update_frame()

    def setup_second_window(self):
        print("Opening second window with two selected areas")
        start_time = time.time()
        self.area_pair_counter += 1
        try:
            self.second_window = tk.Toplevel(self.root)
            self.second_window.title(f"Selected Areas (Pair {self.area_pair_counter})")
            
            self.fig2, self.ax2 = plt.subplots(1, 2, figsize=(10, 5))
            self.canvas2 = FigureCanvasTkAgg(self.fig2, master=self.second_window)
            self.canvas2.get_tk_widget().pack()
            
            self.second_window.protocol("WM_DELETE_WINDOW", self.on_second_window_close)
            
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
            
            # Set up 20 cycled frame indices for each area
            frame_idx1 = self.rectangles[0][4]  # Frame X for area 1
            frame_idx2 = self.rectangles[1][4]  # Frame Y for area 2
            self.area1_frame_indices = list(range(max(0, frame_idx1 - 10), min(self.total_frames, frame_idx1 + 11)))
            self.area2_frame_indices = list(range(max(0, frame_idx2 - 10), min(self.total_frames, frame_idx2 + 11)))
            if len(self.area1_frame_indices) < 20:
                while len(self.area1_frame_indices) < 20 and self.area1_frame_indices:
                    self.area1_frame_indices += self.area1_frame_indices[:20 - len(self.area1_frame_indices)]
            if len(self.area2_frame_indices) < 20:
                while len(self.area2_frame_indices) < 20 and self.area2_frame_indices:
                    self.area2_frame_indices += self.area2_frame_indices[:20 - len(self.area2_frame_indices)]
            self.current_area_index = 0
            print(f"Area 1 frame indices: {self.area1_frame_indices}")
            print(f"Area 2 frame indices: {self.area2_frame_indices}")
            
            # Setup slider and entry for second window
            nav_frame = tk.Frame(self.second_window)
            nav_frame.pack(pady=5)
            tk.Label(nav_frame, text="Go to Offset (0-19):", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            self.area_entry = tk.Entry(nav_frame, width=10, font=("Arial", 12))
            self.area_entry.pack(side=tk.LEFT, padx=5)
            self.area_entry.bind('<Return>', self.goto_area_frame)  # Bind Enter key
            tk.Button(nav_frame, text="Go", command=self.goto_area_frame, font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            
            self.area_slider = tk.Scale(self.second_window, from_=0, to=19, orient=tk.HORIZONTAL,
                                       length=400, command=self.on_area_slider_change)
            self.area_slider.pack(pady=10)
            
            self.root.after(600, self.show_initial_areas)
            print(f"Second window setup in {time.time() - start_time:.3f}s")
        except Exception as e:
            print(f"Error setting up second window: {e}")
            messagebox.showerror("Error", f"Failed to setup second window: {e}")
            self.on_second_window_close()

    def on_second_window_close(self):
        print("Closing second window, resetting selection variables")
        if self.second_window:
            try:
                self.second_window.destroy()
            except tk.TclError as e:
                print(f"Error destroying second window: {e}")
            self.second_window = None
            self.fig2 = None
            self.ax2 = None
            self.canvas2 = None
            self.area_slider = None
            self.area_entry = None
            self.rectangles = []
            self.selected_areas = []
            self.points = []
            self.distances = []
            self.area1_frame_indices = []
            self.area2_frame_indices = []
            self.current_area_index = 0
        self.update_frame()

    def show_initial_areas(self):
        start_time = time.time()
        if self.fig2 is None or self.ax2 is None or self.second_window is None:
            print("Error: Second window figure, axes, or window not initialized")
            return
        
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
            if area.size == 0 or area.shape[0] < 10 or area.shape[1] < 10:
                print(f"Error: Invalid area {i+1} at frame {frame_idx}, x={x}, y={y}, w={w}, h={h}, shape={area.shape}")
                messagebox.showerror("Error", f"Invalid area {i+1} at frame {frame_idx} (too small: {area.shape})")
                continue
            self.ax2[i].imshow(area, interpolation='bicubic')  # Use bicubic interpolation
            self.ax2[i].set_title(f"Area {i+1} (Frame {frame_idx})")
            self.ax2[i].axis('off')
            self.selected_areas.append((x, y, w, h))
            print(f"Displayed area {i+1} at frame {frame_idx}: x={x}, y={y}, w={w}, h={h}, shape={area.shape}")
        
        self.root.after(100, self.draw_canvas)
        print(f"Initial areas displayed in {time.time() - start_time:.3f}s")

    def draw_canvas(self):
        start_time = time.time()
        if self.canvas2 and self.second_window and self.second_window.winfo_exists():
            try:
                self.canvas2.draw()
                print(f"Second window canvas drawn in {time.time() - start_time:.3f}s")
            except Exception as e:
                print(f"Error drawing second window canvas: {e}")
                messagebox.showerror("Error", f"Failed to draw areas: {e}")

    def update_area_frames(self):
        print("Updating area frames in second window")
        start_time = time.time()
        if self.fig2 is None or self.ax2 is None or self.second_window is None:
            print("Error: Second window figure, axes, or window not initialized")
            return
        
        if not self.area1_frame_indices or not self.area2_frame_indices:
            print("Error: No area frames available")
            return
        
        frame_indices = [self.area1_frame_indices[self.current_area_index], 
                         self.area2_frame_indices[self.current_area_index]]
        self.selected_areas = []
        for i, (rect, frame_idx) in enumerate(zip(self.rectangles, frame_indices)):
            x, y, w, h, _ = rect  # Ignore original frame_idx for navigation
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
            if area.size == 0 or area.shape[0] < 10 or area.shape[1] < 10:
                print(f"Error: Invalid area {i+1} at frame {frame_idx}, x={x}, y={y}, w={w}, h={h}, shape={area.shape}")
                continue
            self.ax2[i].clear()
            self.ax2[i].imshow(area, interpolation='bicubic')  # Use bicubic interpolation
            self.ax2[i].set_title(f"Area {i+1} (Frame {frame_idx})")
            self.ax2[i].axis('off')
            self.selected_areas.append((x, y, w, h))
            print(f"Updated area {i+1} at frame {frame_idx}: shape={area.shape}")
        
        self.area_slider.set(self.current_area_index)  # Update slider position
        self.root.after(100, self.draw_canvas)
        print(f"Area frames updated in {time.time() - start_time:.3f}s")

    def on_measure_or_clear(self, event):
        if event.inaxes not in self.ax2.tolist():
            return
        
        start_time = time.time()
        if event.button == 1:  # Left click for measurement
            self.points.append((event.xdata, event.ydata, event.inaxes))
            if len(self.points) == 2:
                p1, p2 = self.points
                if p1[2] == p2[2]:
                    distance = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                    distance = distance / 10
                    p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
                    mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
                    p1[2].text(mid_x, mid_y, f'{distance:.1f}', 
                              color='white', backgroundcolor='black')
                    self.distances.append((p1, p2, distance))
                    p1[2].axis('off')
                    self.root.after(100, self.draw_canvas)
                self.points = []
        
        elif event.button == 3:  # Right click for clearing
            print("Clearing measurements in second window")
            self.distances = []
            self.points = []
            self.update_area_frames()  # Redraw current frames without resetting index
            print(f"Measurements cleared in {time.time() - start_time:.3f}s")

    def on_slider_change(self, value):
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping slider update: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.current_frame = int(value)
        print(f"Slider moved to frame: {self.current_frame}")
        self.frame_entry.delete(0, tk.END)
        self.frame_entry.insert(0, str(self.current_frame))
        self.update_frame()

    def goto_frame(self, event=None):  # Allow event for Enter key
        try:
            frame_num = int(self.frame_entry.get())
            if 0 <= frame_num < self.total_frames:
                current_time = time.time()
                if current_time - self.last_update_time < self.update_interval:
                    print(f"Skipping frame jump: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
                    return
                self.last_update_time = current_time
                self.current_frame = frame_num
                self.frame_slider.set(self.current_frame)
                print(f"Jumped to frame: {self.current_frame}")
                self.update_frame()
            else:
                messagebox.showerror("Error", f"Frame number must be between 0 and {self.total_frames-1}")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid frame number")

    def on_area_slider_change(self, value):
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping area slider update: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.current_area_index = int(value)
        print(f"Area slider moved to offset: {self.current_area_index} (Area 1: Frame {self.area1_frame_indices[self.current_area_index]}, Area 2: Frame {self.area2_frame_indices[self.current_area_index]})")
        self.area_entry.delete(0, tk.END)
        self.area_entry.insert(0, str(self.current_area_index))
        self.update_area_frames()

    def goto_area_frame(self, event=None):  # Allow event for Enter key
        try:
            offset = int(self.area_entry.get())
            max_offset = min(len(self.area1_frame_indices), len(self.area2_frame_indices)) - 1
            if 0 <= offset <= max_offset:
                current_time = time.time()
                if current_time - self.last_update_time < self.update_interval:
                    print(f"Skipping area frame jump: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
                    return
                self.last_update_time = current_time
                self.current_area_index = offset
                self.area_slider.set(self.current_area_index)
                print(f"Jumped to area offset: {self.current_area_index} (Area 1: Frame {self.area1_frame_indices[self.current_area_index]}, Area 2: Frame {self.area2_frame_indices[self.current_area_index]})")
                self.update_area_frames()
            else:
                messagebox.showerror("Error", f"Offset must be between 0 and {max_offset}")
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid offset number")

    def update_frame(self):
        print(f"Updating frame {self.current_frame}")  # Debug output
        start_time = time.time()
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
        read_start = time.time()
        ret, frame = self.cap.read()
        print(f"Read frame {self.current_frame} in {time.time() - read_start:.3f}s")
        if ret:
            frame = cv2.resize(frame, None, fx=0.5, fy=0.5)
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        else:
            print(f"Error: Could not read frame {self.current_frame}")
            messagebox.showerror("Error", f"Could not read frame {self.current_frame}")
            return
        
        self.ax1.clear()
        self.ax1.imshow(frame)
        self.ax1.axis('off')
        self.ax1.set_title(f"Frame {self.current_frame}")
        if len(self.rectangles) == 2:  # Show rectangles only after both are selected
            for x, y, w, h, frame_idx in self.rectangles:
                self.ax1.add_patch(plt.Rectangle((x * 0.5, y * 0.5), 
                                               w * 0.5, h * 0.5, 
                                               fill=False, edgecolor='red', linewidth=2))
        self.canvas1.draw()
        print(f"Updated frame {self.current_frame} with {len(self.rectangles)} fixed areas in {time.time() - start_time:.3f}s")

    def next_area_frame(self, event):
        if not self.area1_frame_indices or not self.area2_frame_indices:
            print("No area frames available for navigation")
            return
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping next area frame: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.current_area_index = (self.current_area_index + 1) % min(len(self.area1_frame_indices), len(self.area2_frame_indices))
        self.area_slider.set(self.current_area_index)
        print(f"Navigating to next area frame: Area 1 (Frame {self.area1_frame_indices[self.current_area_index]}), Area 2 (Frame {self.area2_frame_indices[self.current_area_index]})")
        self.update_area_frames()

    def prev_area_frame(self, event):
        if not self.area1_frame_indices or not self.area2_frame_indices:
            print("No area frames available for navigation")
            return
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping prev area frame: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.current_area_index = (self.current_area_index - 1) % min(len(self.area1_frame_indices), len(self.area2_frame_indices))
        self.area_slider.set(self.current_area_index)
        print(f"Navigating to previous area frame: Area 1 (Frame {self.area1_frame_indices[self.current_area_index]}), Area 2 (Frame {self.area2_frame_indices[self.current_area_index]})")
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

if __name__ == "__main__":
    print("Starting application")
    app = RatGaitAnalyzer()
    app.run()
    print("Application ended")