import tkinter as tk
import customtkinter as ctk

def interpolate_color(color1, color2, ratio):
    """
    ผสมสี RGB ระหว่าง color1 และ color2 ตามอัตราส่วน ratio (0.0 ถึง 1.0)
    color1, color2: tuple (r, g, b)
    คืนค่า: hex string เช่น '#2ECC71'
    """
    r = int(color1[0] + (color2[0] - color1[0]) * ratio)
    g = int(color1[1] + (color2[1] - color1[1]) * ratio)
    b = int(color1[2] + (color2[2] - color1[2]) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"

def get_gradient_color(value, min_val, max_val):
    """
    คำนวณรหัสสีแท่งกราฟไล่เฉด:
    - ค่าน้อยสุด -> สีแดงสด (#E74C3C)
    - ค่ากึ่งกลาง -> สีเหลือง/ส้ม (#F1C40F)
    - ค่าสูงสุด -> สีเขียวสด (#2ECC71)
    """
    RED = (231, 76, 60)      # #E74C3C
    YELLOW = (241, 196, 15)  # #F1C40F
    GREEN = (46, 204, 113)   # #2ECC71

    if max_val <= min_val:
        return interpolate_color(GREEN, GREEN, 1.0)

    ratio = max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))
    if ratio <= 0.5:
        # แดง -> เหลือง
        sub_ratio = ratio / 0.5
        return interpolate_color(RED, YELLOW, sub_ratio)
    else:
        # เหลือง -> เขียว
        sub_ratio = (ratio - 0.5) / 0.5
        return interpolate_color(YELLOW, GREEN, sub_ratio)

class GradientBarChart(ctk.CTkFrame):
    """
    วิดเจ็ตกราฟแท่งเปรียบเทียบสถิติรายปีบน Tkinter Canvas
    - เรียงลำดับปีจาก ปัจจุบัน ➔ อดีต
    - สีแท่งกราฟไล่เฉด: แดง (น้อย) ➔ เหลือง (กลาง) ➔ เขียว (มาก)
    - รองรับการคลิกที่แท่งเพื่อ Filter ข้อมูลตามปี
    """
    def __init__(self, parent, on_bar_click=None, **kwargs):
        super().__init__(parent, fg_color="#0A111A", corner_radius=8, **kwargs)
        self.on_bar_click = on_bar_click
        self.bar_data = [] # [(year, count), ...]
        
        # Canvas สำหรับวาดกราฟ
        self.canvas = tk.Canvas(self, bg="#0A111A", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.canvas.bind("<Configure>", self._on_resize)

    def set_data(self, yearly_stats):
        """
        yearly_stats: list ของ tuple หรือ dict เช่น [('2569', 54), ('2568', 38), ...]
        """
        parsed_data = []
        for item in yearly_stats:
            if isinstance(item, (list, tuple)):
                y = str(item[0])
                c = int(item[1])
            elif isinstance(item, dict):
                y = str(item.get("year", ""))
                c = int(item.get("photo_count", 0))
            else:
                continue
            parsed_data.append((y, c))

        # เรียงลำดับจาก ปัจจุบัน ➔ อดีต (DESC)
        def year_sort_key(entry):
            y_str = entry[0]
            try:
                return int(y_str)
            except ValueError:
                return -1

        parsed_data.sort(key=year_sort_key, reverse=True)
        self.bar_data = parsed_data
        self.draw_chart()

    def _on_resize(self, event):
        self.draw_chart()

    def draw_chart(self):
        self.canvas.delete("all")
        if not self.bar_data:
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            self.canvas.create_text(
                w / 2 if w > 0 else 150, h / 2 if h > 0 else 80,
                text="[ ไม่มีข้อมูลสถิติรายปี ]", fill="#7F8C8D", font=("Tahoma", 11)
            )
            return

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 50 or h < 50:
            return

        pad_left = 30
        pad_right = 30
        pad_top = 35
        pad_bottom = 35

        plot_w = w - pad_left - pad_right
        plot_h = h - pad_top - pad_bottom

        counts = [c for _, c in self.bar_data]
        min_c = min(counts) if counts else 0
        max_c = max(counts) if counts else 1
        if max_c == 0:
            max_c = 1

        n_bars = len(self.bar_data)
        bar_gap = 12
        total_gaps = (n_bars - 1) * bar_gap
        bar_width = max(24, min(65, (plot_w - total_gaps) / n_bars))
        total_chart_w = n_bars * bar_width + total_gaps
        start_x = pad_left + max(0, (plot_w - total_chart_w) / 2)

        # วาดเส้นฐาน Baseline
        baseline_y = h - pad_bottom
        self.canvas.create_line(pad_left - 10, baseline_y, w - pad_right + 10, baseline_y, fill="#2C3E50", width=2)

        for i, (year, count) in enumerate(self.bar_data):
            x0 = start_x + i * (bar_width + bar_gap)
            x1 = x0 + bar_width

            # คำนวณความสูงแท่งกราฟ
            bar_h = (count / max_c) * plot_h if max_c > 0 else 0
            bar_h = max(4, bar_h) if count > 0 else 2 # อย่างน้อยให้เห็นฐาน 2px
            y0 = baseline_y - bar_h
            y1 = baseline_y

            # คำนวณสี Gradient
            color = get_gradient_color(count, min_c, max_c)

            # วาดแท่งกราฟ
            tag_name = f"bar_{i}"
            rect = self.canvas.create_rectangle(
                x0, y0, x1, y1,
                fill=color, outline="#111B27", width=1, tags=(tag_name, "bar")
            )

            # วาดตัวเลขบนหัวแท่ง
            self.canvas.create_text(
                (x0 + x1) / 2, y0 - 12,
                text=f"{count}", fill="#ECEFF1", font=("Consolas", 10, "bold")
            )

            # วาดป้ายชื่อปีด้านล่างแท่ง
            label_color = "#5CACEE" if i == 0 else "#BDC3C7" # เน้นปีล่าสุดด้วยสีฟ้า
            self.canvas.create_text(
                (x0 + x1) / 2, baseline_y + 15,
                text=year, fill=label_color, font=("Tahoma", 10, "bold" if i == 0 else "normal")
            )

            # ผูกคลิกอีเวนต์
            if self.on_bar_click:
                self.canvas.tag_bind(tag_name, "<Button-1>", lambda e, y=year: self.on_bar_click(y))
                self.canvas.tag_bind(tag_name, "<Enter>", lambda e: self.canvas.config(cursor="hand2"))
                self.canvas.tag_bind(tag_name, "<Leave>", lambda e: self.canvas.config(cursor=""))
