# Gait2SFI
Gait2SFI scripts for automated SFI calculation from rodent walking videos (sciatic nerve injury model).
This script package allows researchers to analyze rodent gait from video recordings and compute the Sciatic Functional Index (SFI), a key metric in peripheral nerve injury studies. 
Ideal for neuroscience, preclinical trials, and behavioral analysis in lab animals.

# Getting Started

## Prerequisites
The system has been tested on windows and linux environments.

## Installing
The fastest way to run these scripts is from the Anaconda programming language distribution, after creating an environment with python >=3.9.
Then open the environment terminal and clone the git repository:

```
conda install -c anaconda git
git clone https://github.com/olbmv/Gait2SFI.git
```
**OR** download the files from this page manually and copy them to the environment directory.

Then open the environment terminal with Gait2SFI directory and install the libraries needed to run the scripts:

```
pip install -r requirements.txt
```

# How to Use

You need to run two scripts:

> **python SFI.py # A script for calculating the Sciatic Functional Index (SFI) using data from Gait2SFI**
> 
> **python Gait2SFI.py  # A script for frame-by-frame search for the necessary rodent footprints on video.**

## Gait2SFI.py
**To get started, you need to select a video recording of a rodent's gait in the Gait2SFI.py script dialog box.**
Next, you need to select the desired frame for analysis using the slider above the video. 
To calculate the SFI, you need two prints: the control hind paw (usually the right) and the paw with the damaged sciatic nerve (usually the left one).
If you find a suitable control paw print in the frame, select it with a frame by holding down the left mouse button, then find a frame with a suitable print of the damaged paw and repeat this action.

After selecting two areas with hind paw prints, a second window will open with enlarged images of the areas in a row. 
**Here you can take measurements between points in the image by clicking the left mouse button. To clear the measurements, click the right mouse button.** You can also change the frames of these specific areas within a range of 20 frames using the slider below the images.

**The distance between points = (distance_in_pixels / 10)** This coefficient is needed to reduce the order of digits when manually entering data into the SFI.py calculator. 
After all, for the SFI formula, the dimension of the parameters is irrelevant.

**All measurements obtained must be entered manually into the SFI.py calculator window.**

If the video image allows, you can also calculate the number of bright green pixels in the selected areas with prints **(Calculate Green Area button)**. **These values ​​can be used as a metric for limb restoration, since the area of ​​pressure against the glass will be higher on a healthy paw (and therefore the area of ​​green light)**. To use such a metric, you need to connect a green filter to the camera lens (it is shown in the screenshot below), or reduce the light sensitivity value in the camera settings (ISO)

## SFI.py

After entering the fingerprint parameters into the calculator script, click on the bottom field in the SFI header.
If all fields have correct numerical values, we will get the final SFI value. 
It is worth noting that the **calculator script logs all entered data in a text table** in the same directory under the name **data.csv**. 
This table is needed for further statistical calculations.

# Screenshots

![Gait2SFI window](/Screenshots/Gait2SFI.png)
![SFI calc window](/Screenshots/SFI_calc.png)

