import os
import sys
import time
import threading
import subprocess
import re
import shutil
import webbrowser
import concurrent.futures
import customtkinter as ctk

# --- GLOBAL CONFIG & DATA ---
MAX_FILE_SIZE = 50 * 1024 * 1024 

ALL_FILES = []
TEXT_FILES = []
_lock = threading.Lock()

# --- FUNGSI BACKEND ---
def is_text_candidate(path):
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE:
            return False
    except Exception:
        return False

    try:
        with open(path, "rb") as file:
            chunk = file.read(2048)
            if not chunk:
                return True
            if b"\x00" in chunk:
                return False
            try:
                chunk.decode("utf-8")
                return True
            except Exception:
                try:
                    chunk.decode("latin-1")
                    return True
                except Exception:
                    return False
    except Exception:
        return False

# --- SEARCH LOGIC (BACKEND) ---
def scan_directory(root_path, callback=None):
    all_files = []
    text_files = []
    count = 0
    
    for dirpath, _, filenames in os.walk(root_path):
        for fn in filenames:
            full_path = os.path.join(dirpath, fn)
            all_files.append(full_path)
            
            if is_text_candidate(full_path):
                text_files.append(full_path)
            
            count += 1
            # Update UI every 50 files to prevent lag
            if callback and count % 50 == 0:
                callback(count)
                
    if callback: callback(count) # Final update
    return all_files, text_files

def search_name_contains(keyword: str, file_list: list):
    k = keyword.lower()
    found = [f for f in file_list if k in os.path.basename(f).lower()]
    
    folder_matches = {
        os.path.dirname(f) 
        for f in file_list 
        if k in os.path.basename(os.path.dirname(f)).lower()
    }
    return sorted(set(found) | folder_matches)

def _check_file_content(path, keywords, mode_and):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read().lower()

        if mode_and:
            if all(token in data for token in keywords):
                return path
        else:
            if any(token in data for token in keywords):
                return path
    except Exception:
        pass
    return None

def search_content(keywords: list, file_list: list, mode_and: bool = True, callback=None):
    kw = [k.lower() for k in keywords]
    found = []
    total = len(file_list)
    completed = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_file = {
            executor.submit(_check_file_content, path, kw, mode_and): path 
            for path in file_list
        }
        
        for future in concurrent.futures.as_completed(future_to_file):
            result = future.result()
            if result:
                found.append(result)
            
            completed += 1
            if callback and completed % 5 == 0:
                callback(completed, total)
                
    if callback: callback(total, total)
    return sorted(found)

def open_path(path: str):
    try:
        if os.name == "nt":
            subprocess.Popen(["start", path], shell=True)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print("Gagal membuka path:", e)

def get_previews(path: str, keywords: list, context_lines: int = 1, max_snippets: int = 3):
    kws = [k.lower() for k in keywords]
    snippets = []
    
    def _highlight(text: str, keywords: list):
        def repl(m):
            return f"--> {m.group(0)} <--"
        for kw in keywords:
            try:
                text = re.sub(re.escape(kw), repl, text, flags=re.IGNORECASE)
            except re.error:
                continue
        return text

    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()
    except Exception:
        return snippets

    for i, line in enumerate(lines):
        low = line.lower()
        if any(kw in low for kw in kws):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            snippet = lines[start:end]
            snippet_hl = [_highlight(ln, keywords) for ln in snippet]
            snippets.append((i + 1, snippet_hl))

            if len(snippets) >= max_snippets:
                break
    return snippets        

FILE_CATEGORIES = {
    "Gambar": [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
        ".svg", ".webp", ".ico", ".heic", ".heif", ".raw",
        ".arw", ".cr2", ".nef", ".orf", ".rw2", ".psd", ".ai", ".eps"
    ],

    "Dokumen": [
        ".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt",
        ".xls", ".xlsx", ".csv", ".tsv", ".ppt", ".pptx",
        ".epub", ".md"
    ],

    "Video": [
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv",
        ".webm", ".mpeg", ".mpg", ".3gp", ".m4v"
    ],

    "Suara": [
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga",
        ".wma", ".m4a", ".amr", ".aiff"
    ],

    "Arsip": [
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
        ".xz", ".iso", ".lz", ".zst"
    ],

    "Kode": [
        ".py", ".js", ".ts", ".html", ".css", ".php",
        ".java", ".cpp", ".c", ".h", ".hpp", ".cs",
        ".rb", ".go", ".rs", ".kt", ".swift", ".m",
        ".lua", ".sql", ".xml", ".json", ".yaml", ".yml"
    ],

    "3DModel": [
        ".obj", ".fbx", ".stl", ".dae", ".blend",
        ".gltf", ".glb"
    ],

    "Aplikasi-Executable-Installer": [
        ".exe", ".msi", ".bat", ".cmd", ".sh", ".apk",
        ".app", ".deb", ".rpm"
    ],

    "Database": [
        ".db", ".sqlite", ".sqlite3", ".mdb",
        ".accdb", ".sql", ".dbf"
    ],

    "GIS-MapData": [
        ".shp", ".kml", ".kmz", ".geojson", ".gpx"
    ],

    "Font": [
        ".ttf", ".otf", ".woff", ".woff2"
    ],

    "EBook": [
        ".epub", ".mobi", ".azw3", ".fb2"
    ]
}

def get_category(file):
    ext = os.path.splitext(file)[1].lower()
    for category, extensions in FILE_CATEGORIES.items():
        if ext in extensions:
            return category
    return "Lainnya"

def get_ext(file):
    ext = os.path.splitext(file)[1].lower()
    return ext

def organize(folder_path, isKelompok, isExt):
    if not os.path.isdir(folder_path):
        return
    # Menyesuaikan kelompok semua file yang ada di folder target
    for file in os.listdir(folder_path):
        filePath = os.path.join(folder_path, file)
        
        if os.path.isdir(filePath):
            continue
        
        kategori = get_category(file)
        ext = get_ext(file)
        
        # Membuat path baru untuk folder program file organizer
        organizedFolder = os.path.join(folder_path, "ORGANIZED FILES")
        folderKategori = os.path.join(organizedFolder, kategori) if isKelompok == "y" else organizedFolder
        folderExt = os.path.join(folderKategori, ext) if isExt == "y" else folderKategori

        # Buat folder kalau belum ada
        os.makedirs(organizedFolder, exist_ok=True)
        if isKelompok == "y": os.makedirs(folderKategori, exist_ok=True)
        if isExt == "y": os.makedirs(folderExt, exist_ok=True)
        
        #Pindahkan file/folder
        shutil.move(filePath, os.path.join(folderExt, file))

        #Hasil pemindahan/pengelompokan
        print(f"[OK] {file} -> {kategori} ({get_ext(file)})")


# --- UI ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class FileManagerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("File Manager")
        self.geometry("900x700")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.current_search_root = ""
        self.scanned_files = []      
        self.scanned_text_files = [] 
        self.search_results = []
        
        self.main_container = ctk.CTkFrame(self)
        self.main_container.grid(row=0, column=0, sticky="nsew")
        self.main_container.grid_rowconfigure(0, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        
        self.frames = {}
        
        self.frames["MainMenu"] = self._create_main_menu_frame(self.main_container)
        self.frames["FileFinder"] = self._create_file_finder_frame(self.main_container)
        self.frames["FileOrganizer"] = self._create_file_organizer_frame(self.main_container)
        
        for f in self.frames.values():
            f.grid(row=0, column=0, sticky="nsew")

        self.show_frame("MainMenu")

    def show_frame(self, page_name):
        frame = self.frames.get(page_name)
        if frame: frame.tkraise()

    def open_whatsapp_Wirya(self):
        webbrowser.open("https://wa.me/6281803061922")

    def open_whatsapp_Maven(self):
        webbrowser.open("https://wa.me/6281231301294")    

    # --- MAIN MENU ---
    def _create_main_menu_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid_rowconfigure((1, 3), weight=1) 
        frame.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(frame, fg_color="transparent", height=70)
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        ctk.CTkLabel(header, text="File Manager", font=("Arial", 30, "bold"), text_color="white").pack(side="left"), 
        ctk.CTkButton(header, text="Hubungi Wirya", command=self.open_whatsapp_Wirya, fg_color="red", hover_color="#CC0000").pack(side="right")
        ctk.CTkButton(header, text="Hubungi Maven", command=self.open_whatsapp_Maven, fg_color="red", hover_color="#CC0000").pack(side="right")
        
        # Hero
        ctk.CTkLabel(frame, text="FILE MANAGER", font=("Arial", 60, "bold"), text_color="red").grid(row=1, column=0, pady=(50, 10))
        ctk.CTkLabel(frame, text="Kelola, cari, dan rapikan file Anda. \nDibuat oleh Wiryateja Pamungkas X RPL 3 ((+62) 818-0306-1922), \ndan Maven Helios Agathon Yesstian X RPL 8 ((+62) 812-3130-1294)", font=("Arial", 16), text_color="gray70").grid(row=2, column=0, pady=(0, 50))

        btn_box = ctk.CTkFrame(frame, fg_color="transparent")
        btn_box.grid(row=3, column=0, pady=20)
        
        ctk.CTkButton(btn_box, text="🔎 File Finder", command=lambda: self.show_frame("FileFinder"), 
                      width=200, height=50, font=("Arial", 18, "bold"), fg_color="red", hover_color="#CC0000").pack(side="left", padx=20)

        ctk.CTkButton(btn_box, text="🗂️ File Organizer", command=lambda: self.show_frame("FileOrganizer"), 
                      width=200, height=50, font=("Arial", 18, "bold"), fg_color="red", hover_color="#CC0000").pack(side="left", padx=20)
        
        return frame

    # --- FILE FINDER ---
    def _create_file_finder_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid_columnconfigure((0, 1), weight=1)
        frame.grid_rowconfigure(3, weight=1)

        # Top Bar
        top_bar = ctk.CTkFrame(frame, fg_color="transparent")
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=10)
        ctk.CTkButton(top_bar, text="< Menu Utama", command=lambda: self.show_frame("MainMenu"), width=100, fg_color="gray").pack(side="left")
        ctk.CTkLabel(top_bar, text="Pencarian File", font=("Arial", 20, "bold")).pack(side="left", padx=20)

        control_frame = ctk.CTkFrame(frame)
        control_frame.grid(row=1, column=0, rowspan=3, padx=20, pady=10, sticky="nsew")
        
        # Select Folder
        ctk.CTkLabel(control_frame, text="1. Pilih Lokasi Pencarian:", font=("Arial", 14, "bold")).pack(pady=(10, 5), anchor="w", padx=10)
        
        path_box = ctk.CTkFrame(control_frame, fg_color="transparent")
        path_box.pack(fill="x", padx=10)
        
        self.entry_finder_path = ctk.CTkEntry(path_box, placeholder_text="Pilih folder root...")
        self.entry_finder_path.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(path_box, text="📂", width=40, command=self._select_finder_root).pack(side="left", padx=(5,0))

        # Keywords
        ctk.CTkLabel(control_frame, text="2. Kriteria Pencarian:", font=("Arial", 14, "bold")).pack(pady=(20, 5), anchor="w", padx=10)
        
        ctk.CTkLabel(control_frame, text="Nama File (Opsional):").pack(anchor="w", padx=10)
        self.entry_name_kw = ctk.CTkEntry(control_frame, placeholder_text="misal: skripsi")
        self.entry_name_kw.pack(fill="x", padx=10, pady=(0, 10))

        ctk.CTkLabel(control_frame, text="Isi Teks (Opsional):").pack(anchor="w", padx=10)
        self.entry_content_kw = ctk.CTkTextbox(control_frame, height=80)
        self.entry_content_kw.pack(fill="x", padx=10, pady=(0, 10))
        
        # Search Mode
        self.search_mode = ctk.StringVar(value="and")
        row_radio = ctk.CTkFrame(control_frame, fg_color="transparent")
        row_radio.pack(fill="x", padx=10)
        ctk.CTkRadioButton(row_radio, text="AND", variable=self.search_mode, value="and", fg_color="red").pack(side="left", padx=10)
        ctk.CTkRadioButton(row_radio, text="OR", variable=self.search_mode, value="or", fg_color="red").pack(side="left")

        # Start Button
        self.btn_search = ctk.CTkButton(control_frame, text="MULAI PENCARIAN", command=self._start_search_thread, 
                                        height=40, font=("Arial", 14, "bold"), fg_color="red", hover_color="#CC0000")
        self.btn_search.pack(fill="x", padx=10, pady=20)
        
        # --- PROGRESS BAR SECTION ---
        self.progress_label = ctk.CTkLabel(control_frame, text="Status: Siap", text_color="gray")
        self.progress_label.pack(pady=(0, 5))

        result_frame = ctk.CTkFrame(frame)
        result_frame.grid(row=1, column=1, rowspan=3, padx=20, pady=10, sticky="nsew")
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(result_frame, text="Hasil Pencarian:", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=10)
        
        self.results_textbox = ctk.CTkTextbox(result_frame)
        self.results_textbox.grid(row=1, column=0, sticky="nsew", padx=10)
        self.results_textbox.configure(state="disabled")

        # Action Buttons
        action_box = ctk.CTkFrame(result_frame, fg_color="transparent")
        action_box.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        
        self.entry_result_number = ctk.CTkEntry(action_box, placeholder_text="No.", width=50)
        self.entry_result_number.pack(side="left")
        
        ctk.CTkButton(action_box, text="Buka File", command=lambda: self._action_on_result("open"), width=80, fg_color="#3498DB").pack(side="left", padx=5)
        ctk.CTkButton(action_box, text="Buka Folder", command=lambda: self._action_on_result("folder"), width=80, fg_color="#2ECC71").pack(side="left", padx=5)
        ctk.CTkButton(action_box, text="Preview Teks", command=lambda: self._action_on_result("preview"), width=80, fg_color="#F39C12").pack(side="left", padx=5)

        return frame

    def _select_finder_root(self):
        folder = ctk.filedialog.askdirectory()
        if folder:
            self.entry_finder_path.delete(0, "end")
            self.entry_finder_path.insert(0, folder)
            self.current_search_root = ""
            self.scanned_files = []
            self.scanned_text_files = []
            self.progress_label.configure(text="Lokasi berubah. Klik Cari untuk memindai.", text_color="yellow")
            self.progress_bar.set(0)

    def _update_scan_progress(self, count):
        self.progress_label.configure(text=f"Scanning... Found {count} files", text_color="yellow")
    
    def _update_search_progress(self, current, total):
        if total > 0:
            val = current / total
            self.progress_bar.set(val)
            self.progress_label.configure(text=f"Checking content: {current} out of {total} files", text_color="yellow")

    # --- MAIN SEARCH LOGIC ---
    def _start_search_thread(self):
        root_path = self.entry_finder_path.get().strip()
        if not root_path or not os.path.exists(root_path):
            self.progress_label.configure(text="Error: Pilih folder yang valid!", text_color="red")
            return

        name_kw = self.entry_name_kw.get().strip()
        content_kw_raw = self.entry_content_kw.get("1.0", "end").strip()
        content_kws = [k.strip() for k in content_kw_raw.split('\n') if k.strip()]
        mode_and = (self.search_mode.get() == "and")

        if not name_kw and not content_kws:
            self.progress_label.configure(text="Error: Masukkan kata kunci.", text_color="red")
            return

        # Prepare UI
        self.btn_search.configure(state="disabled")
        self.results_textbox.configure(state="normal")
        self.results_textbox.delete("0.0", "end")
        self.results_textbox.insert("0.0", "Memulai proses...\n")
        self.results_textbox.configure(state="disabled")
        
        threading.Thread(target=self._run_search_logic, 
                         args=(root_path, name_kw, content_kws, mode_and), 
                         daemon=True).start()

    def _run_search_logic(self, root_path, name_kw, content_kws, mode_and):
        start_time = time.time()
        
        def scan_cb(count):
            self.after(0, lambda: self._update_scan_progress(count))
            
        def search_cb(curr, tot):
            self.after(0, lambda: self._update_search_progress(curr, tot))

        # 1. SCANNING WHEN ROOT IS CHANGED
        if root_path != self.current_search_root:
            self.after(0, lambda: self.progress_bar.configure(mode="indeterminate"))
            self.after(0, lambda: self.progress_bar.start())
            
            try:
                self.scanned_files, self.scanned_text_files = scan_directory(root_path, callback=scan_cb)
                self.current_search_root = root_path
            except Exception as e:
                self.after(0, lambda: self.progress_label.configure(text=f"Error Scan: {e}", text_color="red"))
                self.after(0, lambda: self.btn_search.configure(state="normal"))
                self.after(0, lambda: self.progress_bar.stop())
                return
            
            self.after(0, lambda: self.progress_bar.stop())

        # 2. FILTERING
        self.after(0, lambda: self.progress_bar.configure(mode="determinate"))
        self.after(0, lambda: self.progress_bar.set(0))
        
        results_name = []
        if name_kw:
            results_name = search_name_contains(name_kw, self.scanned_files)
            
        results_content = []
        if content_kws:
            target_list = self.scanned_text_files
            results_content = search_content(content_kws, target_list, mode_and=mode_and, callback=search_cb)

        # 3. MERGE RESULTS
        if name_kw and content_kws:
            final = set(results_name) | set(results_content)
        elif name_kw:
            final = set(results_name)
        elif content_kws:
            final = set(results_content)
        else:
            final = set()
            
        self.search_results = sorted(list(final))
        duration = time.time() - start_time
        
        self.after(0, lambda: self._update_results_ui(len(self.scanned_files), duration))

    def _update_results_ui(self, total_scanned, duration):
        self.btn_search.configure(state="normal")
        self.progress_bar.set(1)
        
        count = len(self.search_results)
        msg = f"Selesai: {count} hasil dari {total_scanned} file ({duration:.2f}s)"
        self.progress_label.configure(text=msg, text_color="green")
        
        self.results_textbox.configure(state="normal")
        self.results_textbox.delete("0.0", "end")
        
        if count == 0:
            self.results_textbox.insert("0.0", "Tidak ditemukan hasil.")
        else:
            for idx, p in enumerate(self.search_results, 1):
                self.results_textbox.insert("end", f"[{idx}] {p}\n")
        
        self.results_textbox.configure(state="disabled")

    def _action_on_result(self, action):
        try:
            sel_str = self.entry_result_number.get().strip()
            if not sel_str.isdigit(): raise ValueError
            i = int(sel_str)
            if not (1 <= i <= len(self.search_results)): raise IndexError
            path = self.search_results[i - 1]
            
            if action == "open":
                open_path(path)
            elif action == "folder":
                target = os.path.dirname(path) if os.path.isfile(path) else path
                open_path(target)
            elif action == "preview":
                self._show_preview(path)
        except:
            self.progress_label.configure(text="Error: Cek nomor hasil.", text_color="red")

    def _show_preview(self, path):
        if os.path.isdir(path): return
        
        name_kw = self.entry_name_kw.get().strip()
        content_kw_raw = self.entry_content_kw.get("1.0", "end").strip()
        kws = [k.strip() for k in content_kw_raw.split('\n') if k.strip()]
        if name_kw and not kws: kws = [name_kw]
        
        snippets = get_previews(path, kws, max_snippets=5)
        
        top = ctk.CTkToplevel(self)
        top.title(f"Preview: {os.path.basename(path)}")
        top.geometry("600x400")
        txt = ctk.CTkTextbox(top)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        
        if not snippets:
            txt.insert("0.0", "Tidak ada preview (keyword tidak ditemukan di teks).")
        else:
            for l, lines in snippets:
                txt.insert("end", f"Line {l}:\n", "bold")
                for line in lines: txt.insert("end", line + "\n")
                txt.insert("end", "\n")
        txt.configure(state="disabled")

    # --- FILE ORGANIZER ---
    def _create_file_organizer_frame(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkButton(frame, text="< Menu Utama", command=lambda: self.show_frame("MainMenu"), width=100, fg_color="gray").grid(row=0, column=0, sticky="w", padx=20, pady=10)
        ctk.CTkLabel(frame, text="Organizer File", font=("Arial", 20, "bold")).grid(row=1, column=0, pady=10)
        
        input_frame = ctk.CTkFrame(frame)
        input_frame.grid(row=2, column=0, padx=20, sticky="ew")
        
        self.entry_organizer_path = ctk.CTkEntry(input_frame, placeholder_text="Folder Target...")
        self.entry_organizer_path.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        ctk.CTkButton(input_frame, text="📂", width=40, command=self._select_organizer_folder).pack(side="left", padx=10)
        
        self.check_kelompok = ctk.BooleanVar(value=True)
        self.check_ext = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(frame, text="Kelompokkan (Fungsi)", variable=self.check_kelompok, fg_color="red").grid(row=3, column=0, sticky="w", padx=30, pady=5)
        ctk.CTkCheckBox(frame, text="Sub-folder (Ekstensi)", variable=self.check_ext, fg_color="red").grid(row=4, column=0, sticky="w", padx=30, pady=5)
        
        self.btn_organize = ctk.CTkButton(frame, text="Mulai Rapikan", command=self._action_organize, fg_color="red", height=40)
        self.btn_organize.grid(row=5, column=0, pady=20)
        
        self.status_organizer = ctk.CTkLabel(frame, text="")
        self.status_organizer.grid(row=6, column=0)
        
        return frame

    def _select_organizer_folder(self):
        f = ctk.filedialog.askdirectory()
        if f:
            self.entry_organizer_path.delete(0, "end")
            self.entry_organizer_path.insert(0, f)

    def _action_organize(self):
        folder = self.entry_organizer_path.get()
        if not folder: return
        self.btn_organize.configure(state="disabled")
        self.status_organizer.configure(text="Memproses...", text_color="yellow")
        
        threading.Thread(target=self._run_organize, args=(folder,), daemon=True).start()

    def _run_organize(self, folder):
        try:
            organize(folder, "y" if self.check_kelompok.get() else "n", "y" if self.check_ext.get() else "n")
            self.after(0, lambda: self.status_organizer.configure(text="Selesai!", text_color="green"))
        except Exception as e:
            self.after(0, lambda: self.status_organizer.configure(text=f"Error: {e}", text_color="red"))
        self.after(0, lambda: self.btn_organize.configure(state="normal"))

if __name__ == "__main__":
    app = FileManagerApp()
    app.mainloop()
