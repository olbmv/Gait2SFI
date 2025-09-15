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

class Gait2SFI:
    def __init__(self):
        print("Initializing Gait2SFI")  # Debug output
        self.root = tk.Tk()
        self.root.title("Rodent Gait Analyzer")
        
        # Video handling
        self.video_path = None
        self.cap = None
        self.current_frame = 0
        self.total_frames = 0
        self.last_update_time = 0
        self.update_interval = 0.1  # Limit updates to ~10 fps
        self.area1_frame_indices = []  # Indices for area 1 frames
        self.area2_frame_indices = []  # Indices for area 2 frames
        self.current_area_index = 10  # Initial offset to 10
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
        
        # LUT variables
        self.contrast_alpha = 1.0  # Default contrast
        self.contrast_beta = 0.0   # Default brightness
        self.should_apply_lut = False  # Flag to apply LUT only when contrast or brightness slider is used
        
        # Green area calculation
        self.green_area_values = [None, None]  # [area1, area2]
        self.green_area_button = None  # Button for calculating green area
        
        # GUI elements
        self.fig1, self.ax1 = plt.subplots(figsize=(8, 6), dpi=150)
        self.canvas1 = None
        self.fig2 = None
        self.ax2 = None
        self.canvas2 = None
        self.second_window = None
        self.frame_slider = None  # Slider for main window
        self.frame_entry = None   # Entry for frame number
        self.nav_frame = None     # Frame for navigation controls
        self.area_slider = None   # Slider for second window
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
        self.current_frame = 0
        self.area1_frame_indices = []
        self.area2_frame_indices = []
        self.current_area_index = 10
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
            self.contrast_slider = None
            self.brightness_slider = None
        
        if self.frame_slider:
            self.frame_slider.destroy()
        self.frame_slider = tk.Scale(self.root, from_=0, to=self.total_frames-1, orient=tk.HORIZONTAL,
                                    length=800, command=self.on_slider_change)
        self.frame_slider.pack(pady=10)
        
        if self.nav_frame:
            self.nav_frame.destroy()
        self.nav_frame = tk.Frame(self.root)
        self.nav_frame.pack(pady=5)
        tk.Label(self.nav_frame, text="Go to Frame:", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
        self.frame_entry = tk.Entry(self.nav_frame, width=10, font=("Arial", 12))
        self.frame_entry.pack(side=tk.LEFT, padx=5)
        self.frame_entry.bind('<Return>', self.goto_frame)
        tk.Button(self.nav_frame, text="Go", command=self.goto_frame, font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
        
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
                                        fill=False, edgecolor='red', linewidth=1)
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
            
            frame_idx1 = self.rectangles[0][4]
            frame_idx2 = self.rectangles[1][4]
            self.area1_frame_indices = list(range(max(0, frame_idx1 - 10), min(self.total_frames, frame_idx1 + 11)))
            self.area2_frame_indices = list(range(max(0, frame_idx2 - 10), min(self.total_frames, frame_idx2 + 11)))
            if len(self.area1_frame_indices) < 20:
                while len(self.area1_frame_indices) < 20 and self.area1_frame_indices:
                    self.area1_frame_indices += self.area1_frame_indices[:20 - len(self.area1_frame_indices)]
            if len(self.area2_frame_indices) < 20:
                while len(self.area2_frame_indices) < 20 and self.area2_frame_indices:
                    self.area2_frame_indices += self.area2_frame_indices[:20 - len(self.area2_frame_indices)]
            self.current_area_index = 10  # Set initial offset to 10
            print(f"Area 1 frame indices: {self.area1_frame_indices}")
            print(f"Area 2 frame indices: {self.area2_frame_indices}")
            
            nav_frame = tk.Frame(self.second_window)
            nav_frame.pack(pady=5)
            tk.Label(nav_frame, text="Go to Offset (0-19):", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            self.area_entry = tk.Entry(nav_frame, width=10, font=("Arial", 12))
            self.area_entry.pack(side=tk.LEFT, padx=5)
            self.area_entry.bind('<Return>', self.goto_area_frame)
            tk.Button(nav_frame, text="Go", command=self.goto_area_frame, font=("Arial", 12)).pack(side=tk.LEFT, padx=5)
            
            self.area_slider = tk.Scale(self.second_window, from_=0, to=19, orient=tk.HORIZONTAL,
                                       length=400, command=self.on_area_slider_change)
            self.area_slider.set(self.current_area_index)  # Set slider to 10 initially
            self.area_slider.pack(pady=10)
            
            contrast_frame = tk.Frame(self.second_window)
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
            self.green_area_button = tk.Button(self.second_window, text="Calculate Green Area", 
                                             command=self.calculate_green_area, font=("Arial", 12))
            self.green_area_button.pack(pady=5)
            
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
            self.contrast_slider = None
            self.brightness_slider = None
            self.green_area_button = None
            self.rectangles = []
            self.selected_areas = []
            self.points = []
            self.distances = []
            self.area1_frame_indices = []
            self.area2_frame_indices = []
            self.current_area_index = 10
            self.contrast_alpha = 1.0
            self.contrast_beta = 0.0
            self.should_apply_lut = False
            self.green_area_values = [None, None]
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

    def calculate_green_area(self):
        print("Calculating green area for both regions")
        start_time = time.time()
        
        # Ensure VideoCapture is valid
        if self.cap is None or not self.cap.isOpened():
            print("Error: VideoCapture not initialized or closed.")
            messagebox.showerror("Error", "VideoCapture not initialized or closed.")
            return
        
        # Show wait message
        messagebox.showinfo("Processing", "Please wait, calculating green area... This may take a moment.")
        
        # Define range for light green shades in HSV
        lower_green = np.array([40, 50, 120])  # Hue: 40-200, Saturation: 50-255, Value: 120-255
        upper_green = np.array([200, 255, 255])
        
        self.green_area_values = [0, 0]  # Reset values
        
        for area_idx in range(2):
            total_green_pixels = 0
            frame_indices = self.area1_frame_indices if area_idx == 0 else self.area2_frame_indices
            
            # Sum over all 20 frames
            for frame_idx in frame_indices:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = self.cap.read()
                if not ret:
                    print(f"Error: Could not read frame {frame_idx} for area {area_idx + 1}")
                    continue
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Get the region of interest
                x, y, w, h, _ = self.rectangles[area_idx]
                roi = frame[y:y+h, x:x+w]
                
                # Convert to HSV
                hsv_roi = cv2.cvtColor(roi, cv2.COLOR_RGB2HSV)
                
                # Create mask for light green shades
                mask = cv2.inRange(hsv_roi, lower_green, upper_green)
                
                # Debug: Display mask
                cv2.imshow(f"Mask Area {area_idx + 1}", cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR))
                cv2.waitKey(1)  # Small delay to update window
                
                # Count green pixels
                green_pixels = np.sum(mask > 0)
                total_green_pixels += green_pixels
                print(f"Frame {frame_idx}, Area {area_idx + 1} green pixels: {green_pixels}")
            
            self.green_area_values[area_idx] = total_green_pixels
            print(f"Area {area_idx + 1} total green pixel count: {total_green_pixels}")
        
        # Close debug windows after calculation
        cv2.destroyAllWindows()
        
        # Update display with green area values
        self.update_area_frames()
        print(f"Green area calculation completed in {time.time() - start_time:.3f}s")

    def extract_green_motion(self, image):
        start_time = time.time()
        h, w = image.shape[:2]
        if max(h, w) > 200:
            scale = 200 / max(h, w)
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        
        # Convert to HSV for green detection
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        lower_green = np.array([30, 30, 30])
        upper_green = np.array([90, 255, 255])
        mask_green = cv2.inRange(hsv, lower_green, upper_green)
        
        # Convert to grayscale and threshold for light areas
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, mask_prints = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)
        
        # Create a simple body mask (invert motion mask as a placeholder)
        background_subtractor = cv2.createBackgroundSubtractorMOG2(history=5, varThreshold=40, detectShadows=False)
        fg_mask2 = background_subtractor.apply(image)
        mask_body = cv2.bitwise_not(fg_mask2)
        
        # Combine masks
        mask_prints = cv2.bitwise_and(mask_prints, mask_green)
        mask_prints = cv2.bitwise_and(mask_prints, mask_body)
        
        # Morphological operations to remove noise
        kernel = np.ones((3, 3), np.uint8)
        final_mask = cv2.morphologyEx(mask_prints, cv2.MORPH_OPEN, kernel)
        final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_CLOSE, kernel)
        
        # Apply mask to image
        result = cv2.bitwise_and(image, image, mask=final_mask)
        
        green_pixel_count = np.sum(final_mask > 0)
        print(f"Green motion extracted in {time.time() - start_time:.3f}s, {green_pixel_count} green pixels")
        return result, green_pixel_count

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
                self.ax2[i].text(5, 10, f"Green: {self.green_area_values[i]} px", 
                                color='white', backgroundcolor='black', fontsize=10)
            self.selected_areas.append((x, y, w, h))
            print(f"Displayed area {i+1} at frame {frame_idx}: x={x}, y={y}, w={w}, h={h}, shape={area.shape}")
        
        for p1, p2, distance in self.distances:
            p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
            mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
            p1[2].text(mid_x, mid_y, f'{distance:.1f}', 
                      color='white', backgroundcolor='black')
            p1[2].axis('off')

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
            x, y, w, h, _ = rect
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
                self.ax2[i].text(5, 10, f"Green: {self.green_area_values[i]} px", 
                                color='white', backgroundcolor='black', fontsize=10)
            self.selected_areas.append((x, y, w, h))
            print(f"Updated area {i+1} at frame {frame_idx}: shape={area.shape}")
        
        for p1, p2, distance in self.distances:
            p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
            mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
            p1[2].text(mid_x, mid_y, f'{distance:.1f}', 
                      color='white', backgroundcolor='black')
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
                    distance = distance / 10  # Short digits; Del it if you want distance in pixels
                    p1[2].plot([p1[0], p2[0]], [p1[1], p2[1]], 'b-', linewidth=2)
                    mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
                    p1[2].text(mid_x, mid_y, f'{distance:.1f}', 
                              color='white', backgroundcolor='black')
                    self.distances.append((p1, p2, distance))
                    p1[2].axis('off')
                    self.draw_canvas()
                self.points = []
        
        elif event.button == 3:
            print("Clearing measurements in second window")
            self.distances = []
            self.points = []
            self.update_area_frames()
            print(f"Measurements cleared in {time.time() - start_time:.3f}s")

    def on_slider_change(self, value):
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping slider update: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.current_frame = int(value)
        print(f"Slider moved to frame: {self.current_frame}")
        if self.frame_entry:
            self.frame_entry.delete(0, tk.END)
            self.frame_entry.insert(0, str(self.current_frame))
        self.update_frame()

    def goto_frame(self, event=None):
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
        self.should_apply_lut = False  # Reset LUT application
        self.contrast_alpha = 1.0  # Reset contrast
        self.contrast_beta = 0.0   # Reset brightness
        if self.contrast_slider:
            self.contrast_slider.set(self.contrast_alpha)
        if self.brightness_slider:
            self.brightness_slider.set(self.contrast_beta)
        self.current_area_index = int(value)
        print(f"Area slider moved to offset: {self.current_area_index} (Area 1: Frame {self.area1_frame_indices[self.current_area_index]}, Area 2: Frame {self.area2_frame_indices[self.current_area_index]})")
        if self.area_entry:
            self.area_entry.delete(0, tk.END)
            self.area_entry.insert(0, str(self.current_area_index))
        self.update_area_frames()

    def goto_area_frame(self, event=None):
        try:
            offset = int(self.area_entry.get())
            max_offset = min(len(self.area1_frame_indices), len(self.area2_frame_indices)) - 1
            if 0 <= offset <= max_offset:
                current_time = time.time()
                if current_time - self.last_update_time < self.update_interval:
                    print(f"Skipping area frame jump: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
                    return
                self.last_update_time = current_time
                self.should_apply_lut = False  # Reset LUT application on frame change
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

    def next_area_frame(self, event):
        if not self.area1_frame_indices or not self.area2_frame_indices:
            print("No area frames available for navigation")
            return
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping next area frame: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.should_apply_lut = False  # Reset LUT application on frame change
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
        self.should_apply_lut = False  # Reset LUT application on frame change
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
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping contrast update: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.contrast_alpha = float(value)
        self.should_apply_lut = True  # Enable LUT application
        print(f"Contrast changed to alpha={self.contrast_alpha}, LUT will be applied")
        self.update_area_frames()

    def on_brightness_change(self, value):
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            print(f"Skipping brightness update: too soon (time since last update: {current_time - self.last_update_time:.3f}s)")
            return
        self.last_update_time = current_time
        self.contrast_beta = float(value)
        self.should_apply_lut = True  # Enable LUT application
        print(f"Brightness changed to beta={self.contrast_beta}, LUT will be applied")
        self.update_area_frames()

    def reset_lut(self):
        print("Resetting LUT parameters")
        self.contrast_alpha = 1.0
        self.contrast_beta = 0.0
        self.should_apply_lut = False  # Disable LUT application
        if self.contrast_slider:
            self.contrast_slider.set(self.contrast_alpha)
        if self.brightness_slider:
            self.brightness_slider.set(self.contrast_beta)
        self.update_area_frames()

if __name__ == "__main__":
    print("Starting application")
    app = Gait2SFI()
    app.run()
    print("Application ended")