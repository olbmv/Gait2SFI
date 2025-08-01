# SFI calc
# A script for calculating the Sciatic Functional Index (SFI) using data from Gait2SFI
# Author: PhD student Oleksandr Bomikhov
# Bogomoletz Institute of Physiology, National Academy of Sciences of Ukraine

import tkinter as tk
from PIL import Image, ImageTk
import re
import os
import base64
import io
import time
import pandas as pd
from tkinter import messagebox
import csv
from datetime import datetime, date, time


SFI_EXPL_IMAGE=r"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"
file_name="data.csv"

class Application(tk.Frame):

    def __init__(self, master=None):
        super().__init__(master)
        self.master = master
        self.pack()
        self.create_widgets()
        self.EPL,self.NPL,self.ETS,self.NTS,self.EIT,self.NIT=0,0,0,0,0,0
        
    def stringToRGB(self, base64_string):
        imgdata = base64.b64decode(str(SFI_EXPL_IMAGE))
        img = Image.open(io.BytesIO(imgdata))
        return img 
               
    def append_row_to_csv(self, filepath, row):
        file_exists = os.path.isfile(filepath)
        with open(filepath, mode='a', newline='', encoding='utf-8') as f:
          writer = csv.writer(f)
          if not file_exists:
            header = ['FILE','EPL','NPL','ETS','NTS','EIT','NIT', 'Date', 'Week', 'Group', 'RatId', 'SFI']
            writer.writerow(header)
          writer.writerow(row)

    def create_widgets(self):
        self.fields = []
        self.titles=['epl','npl','ets','nts','eit','nit','ratId','groupId','week']
        sfi_image = self.stringToRGB(SFI_EXPL_IMAGE)    
        self.photo = ImageTk.PhotoImage(sfi_image)
        self.canvas = tk.Canvas(self, width=280, height=160)
        self.canvas.grid()
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        label=tk.Label(self, text="(c) Image source:\n doi: 10.3389/fnins.2016.00557")
        label.grid()
        for i in range(9):
             label = tk.Label(self, text=f"{self.titles[i]}")
             label.grid()
             field = tk.Entry(self, justify='center', name=f"{self.titles[i]}")
             field.grid()
             self.fields.append(field)
                     
        label = tk.Label(self, text=f"SFI:", font=("Arial Bold", 20))
        label.grid()
        self.sfi_field = tk.Entry(self, justify='center', name="sFI")
        self.sfi_field.bind('<Button-1>', self.calc_sfi)
        self.sfi_field.insert(0, "Click here to calculate")
        self.sfi_field.grid()


    def bclear_field(self, event):
        self.EPL=0
        self.NPL=0
        self.ETS=0
        self.NTS=0
        self.EIT=0
        self.NIT=0
        self.sfi_field.delete(0, tk.END)
        self.sfi_field.insert(0, "Click here to calculate")
        
           
    def calc_sfi(self, event):
        try:
              for i in range(len(self.fields)):
                ename=self.fields[i].winfo_name()
                print(ename)
                
                if  ename=='epl':
                      self.EPL=float(self.fields[i].get())
                if  ename=='npl':
                      self.NPL=float(self.fields[i].get())
                if  ename=='ets':
                      self.ETS=float(self.fields[i].get())
                if  ename=='nts':
                      self.NTS=float(self.fields[i].get())
                if  ename=='eit':
                      self.EIT=float(self.fields[i].get())
                if  ename=='nit':
                      self.NIT=float(self.fields[i].get())
                if  ename=='ratId':
                      rat_field=str(self.fields[i].get())
                if  ename=='groupId':
                      group_field=str(self.fields[i].get())
                if  ename=='week':
                      week_field=str(self.fields[i].get())
                             
              print(self.EPL,self.NPL,self.ETS,self.NTS,self.EIT,self.NIT, week_field, rat_field, group_field )
              if (self.EPL and self.NPL and self.ETS and self.NTS and self.EIT and self.NIT and rat_field and group_field and week_field):
                         
                try:
                   with open('shared.txt', 'r', encoding='utf-8') as file:
                     received_text = file.read()
                     print(f"A video filename received: {received_text}")
                except FileNotFoundError:
                     print("No file with filename")
              
                x=(self.EPL-self.NPL)/self.NPL
                y=(self.ETS-self.NTS)/self.NTS
                z=(self.EIT-self.NIT)/self.NIT
                sfi=int(-(38.3*x)+(109.5*y)+(13.3*z)-8.8)
                print(f"SFI:{sfi}")
                self.sfi_field.delete(0, tk.END)
                self.sfi_field.insert(0,str(sfi))
                now = datetime.now()
                formatted = now.strftime("%Y-%m-%d %H:%M:%S")
                new_row = [received_text,self.EPL,self.NPL,self.ETS,self.NTS,self.EIT,self.NIT,formatted,week_field, group_field,rat_field,sfi]
                self.append_row_to_csv(file_name,new_row)
                
              else:
                self.sfi_field.delete(0, tk.END)
                self.sfi_field.insert(0, "Not enough data")
                time.sleep(3)
                self.sfi_field.insert(0, "Click here to calculate")
        except Exception as e:
              print(e)



if __name__ == '__main__':
    root = tk.Tk()
    root.title('SFI calc')
    root.wm_minsize(300, 600)
    app = Application(master=root)
    app.mainloop()