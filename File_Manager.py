import os
import sys
import time
import pickle
import threading
import queue
import subprocess
import re
import shutil
from pathlib import Path

# FILE FINDER
# nama di depan ".pkl" hanyalah nama variabel, ditambahkan "." untuk di-ignore filenya agar tidak menumpuk di folder user
ROOT = Path.home()
CACHE_DIR = Path.home()

CACHE_ALL = CACHE_DIR / ".keseluruhan_file.pkl"
CACHE_TEXT = CACHE_DIR / ".file_berbentuk_teks.pkl"

THREAD_COUNT = 4
MAX_FILE_SIZE = 50 * 1024 * 1024 

ALL_FILES = []
TEXT_FILES = []
# threading lock digunakan untuk mencegah tabrakan antara thread saat ia sedang mencari file
_lock = threading.Lock()

# menyimpan file ke dalam cache dengan cara mengubanya ke bentuk binary (wb) Agar pickle bisa menyimpannya
def save_cache():
    try:
        with open(CACHE_ALL, "wb") as file:
            pickle.dump(ALL_FILES, file)
        with open(CACHE_TEXT, "wb") as file:
            pickle.dump(TEXT_FILES, file)
    except Exception as error:
        print("Gagal menyimpan cache:", error)


def load_cache():
    global ALL_FILES, TEXT_FILES
    if CACHE_ALL.exists() and CACHE_TEXT.exists():
        try:
            with open(CACHE_ALL, "rb") as file:
                ALL_FILES = pickle.load(file)
            with open(CACHE_TEXT, "rb") as file:
                TEXT_FILES = pickle.load(file)
            return True
        except Exception:
            return False
    return False


# Menentukan apakah file termasuk file teks (Bisa dibaca) atau bukan.
# \x00 berarti null byte biasanya ada di file biner
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


def scan_adder(q, total_counter, text_counter):
    while True:
        try:
            path = q.get_nowait()
        except queue.Empty:
            return

        with _lock:
            ALL_FILES.append(path)
            total_counter[0] += 1

        if is_text_candidate(path):
            with _lock:
                TEXT_FILES.append(path)
                text_counter[0] += 1

        q.task_done()

# Membuat cache semimsal jika cache belum ada
def build_cache(root: str, thread_count: int = THREAD_COUNT, show_progress: bool = True):
    global ALL_FILES, TEXT_FILES
    ALL_FILES = []
    TEXT_FILES = []

    file_paths = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            file_paths.append(os.path.join(dirpath, fn))

    total = len(file_paths)

    q = queue.Queue()
    for path in file_paths:
        q.put(path)

    total_counter = [0]
    text_counter = [0]
    threads = []

    for _ in range(max(1, thread_count)):
        t = threading.Thread(target=scan_adder, args=(q, total_counter, text_counter), daemon=True)
        t.start()
        threads.append(t)

    last = 0
    while any(t.is_alive() for t in threads):
        if show_progress and time.time() - last > 0.25:
            print(f"\rScanning {total_counter[0]} dari {total} files... (file teks: {text_counter[0]})", end="")
            last = time.time()
        time.sleep(0.05)

    q.join()

    if show_progress:
        print(f"\rScanning {total_counter[0]} dari {total} files... (file teks: {text_counter[0]})")
        print("Scan selesai.")

    save_cache()


# Fungsi pencarian file bedasarkan judul/nama filenya
def search_name_contains(keyword: str):
    k = keyword.lower()
    found = []

    for file in ALL_FILES:
        if k in os.path.basename(file).lower():
            found.append(file)

    folder_matches = set()
    for file in ALL_FILES:
        parent = os.path.basename(os.path.dirname(file)).lower()
        if k in parent:
            folder_matches.add(os.path.dirname(file))

    return sorted(set(found) | folder_matches)

# Mencari baris yang mana yang memiliki keyword yang diminta lalu menampilkan 1 baris sebelum, baris yang menagndung keyword, dan baris sesudahnya.
def search_content(keywords: list, mode_and: bool = True, use_stream: bool = True):
    kw = [k.lower() for k in keywords]
    found = []
    total = len(TEXT_FILES)
    scanned = 0
    last_print = 0

    for path in TEXT_FILES:
        scanned += 1
        if time.time() - last_print > 0.2:
            print(f"\rScanning {scanned} dari {total} text files...", end="")
            last_print = time.time()

        try:
            if use_stream:
                matched = False
                if mode_and:
                    remaining = set(kw)
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            low = line.lower()
                            for token in list(remaining):
                                if token in low:
                                    remaining.discard(token)
                            if not remaining:
                                matched = True
                                break
                else:
                    with open(path, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            lw = line.lower()
                            if any(token in lw for token in kw):
                                matched = True
                                break
                if matched:
                    found.append(path)

            else:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    data = f.read().lower()

                if mode_and:
                    if all(token in data for token in kw):
                        found.append(path)
                else:
                    if any(token in data for token in kw):
                        found.append(path)

        except Exception:
            continue

    print()
    return sorted(found)


def _highlight(text: str, keywords: list):
    def repl(m):
        return f"--> {m.group(0)} <--"
    for kw in keywords:
        try:
            text = re.sub(re.escape(kw), repl, text, flags=re.IGNORECASE)
        except re.error:
            continue
    return text


def get_previews(path: str, keywords: list, context_lines: int = 1, max_snippets: int = 3):
    kws = [k.lower() for k in keywords]
    snippets = []
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

# Os.startfile untuk windows, open untuk macos, xd g-open untuk linux
def open_path(path: str):
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        print("Gagal membuka path:", e)


def prompt_choice(prompt: str, choices: list):
    while True:
        ch = input(prompt).strip().lower()
        if ch in choices:
            return ch
        print("Pilihan tidak valid.")


def build_if_needed():
    ok = load_cache()
    if ok:
        print("Cache ditemukan.")
    else:
        print("Menyiapkan program...")
        build_cache(str(ROOT), THREAD_COUNT)


def flow_search():
    print("\n== Pencarian ==")
    name_kw = input("Keyword judul/nama file (Kosongkan apabila tidak mengingat judul/nama file) : ").strip()

    print("Masukkan keyword isi file (satu keyword per baris). Tekan ENTER pada baris kosong untuk selesai.")
    kws = []
    while True:
        ln = input().strip()
        if ln == "":
            break
        kws.append(ln)

    mode_and = True
    if kws:
        mode_and = (prompt_choice("Mode pencarian : AND(a) mode dimana semua keyword harus ditemukan di satu file/folder / OR(o) mode dimana cukup salah satu keyword yang ditemukan : ", ["a", "o"]) == "a")

    print("\nMulai mencari...\n")

    results_name = search_name_contains(name_kw) if name_kw else []
    results_content = search_content(kws, mode_and=mode_and) if kws else []

    if name_kw and kws:
        final = set(results_name) & set(results_content)
    else:
        final = set(results_name) | set(results_content)

    final_sorted = sorted(final)
    print("\n=== HASIL ===")
    if not final_sorted:
        print("Tidak ditemukan hasil.")
        input("\nTekan Enter untuk kembali...")
        return

    for idx, p in enumerate(final_sorted, 1):
        typ = "(folder)" if os.path.isdir(p) else "(file)"
        print(f"[{idx}] {p} {typ}")

    while True:
        sel = input("\nPilih nomor file untuk aksi lebih lanjut (preview/open/folder) atau kosong untuk kembali: ").strip()
        if sel == "":
            break
        if not sel.isdigit():
            print("Masukan angka valid.")
            continue

        i = int(sel)
        if not (1 <= i <= len(final_sorted)):
            print("Nomor di luar rentang.")
            continue

        path = final_sorted[i - 1]

        if os.path.isdir(path):
            if prompt_choice("Buka folder? Buka (1) / kembali (2): ", ["1", "2"]) == "1":
                open_path(path)
            continue

        if os.path.isfile(path):
            if path not in TEXT_FILES:
                print("File bukan berupa teks, tidak ada preview.")
            else:
                snippets = get_previews(path, kws if kws else [name_kw],
                                        context_lines=1, max_snippets=3)
                if not snippets:
                    print("Tidak ada preview.")
                else:
                    print(f"\nPreview untuk: {path}")
                    for lineno, snip in snippets:
                        print(f"  Line {lineno}:")
                        for line in snip:
                            print("    " + line)
                        print()

            act = prompt_choice("Buka file (1) / Buka folder (2) / Back (3): ", 
                                ["1", "2", "3"])
            if act == "1":
                open_path(path)
            elif act == "2":
                open_path(os.path.dirname(path))
            else:
                continue

    input("\nTekan Enter untuk kembali...")


def run_finder():
    build_if_needed()
    flow_search()

# FILE ORGANIZER
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

def organize(folder_path,isKelompok,isExt):
    if not os.path.isdir(folder_path):
        return
    # Menyesuaikan kelompok semua file yang ada di folder target
    for file in os.listdir(folder_path):
        filePath = os.path.join(folder_path, file)
        
        # Lewati folder
        if os.path.isdir(filePath):
            continue
        
        # Menentukan kategori dan ekstensi file
        kategori = get_category(file)
        ext = get_ext(file)
        
        # Membuat path baru untuk folder program file organizer
        organizedFolder = os.path.join(folder_path, "ORGANIZED FILES")
        folderKategori = os.path.join(organizedFolder, kategori) if isKelompok == "y" else organizedFolder
        folderExt = os.path.join(folderKategori, ext) if isExt == "y" else folderKategori

        # Buat folder kalau belum ada
        os.makedirs(organizedFolder, exist_ok=True)
        if isKelompok == "y": {os.makedirs(folderKategori, exist_ok=True)}
        if isExt == "y": {os.makedirs(folderExt, exist_ok=True)}
        
        #Pindahkan file/folder
        shutil.move(filePath, os.path.join(folderExt, file))

        #Hasil pemindahan/pengelompokan
        print(f"[OK] {file} -> {kategori} ({get_ext(file)})")


def run_organizer():
    print("""
======= FILE ORGANIZER =======
Masukkan nama folder yang berisi file yang belum terorganisir.
File akan dikelompokkan berdasarkan kategori (Gambar, Video, Kode, dll.)
Enter tanpa masukan ke salah satu input untuk batal.
""")
    target_folder = input("Masukkan path folder target: ").strip()
    while not os.path.isdir(target_folder) and target_folder!="":
        print("Path tidak valid.")
        target_folder = input("Masukkan path folder target: ").strip()
    if target_folder == "":
        print("Dibatalkan.")
        return
    
    iskelompok = input("Pengelompokan berdasarkan fungsi file (y/n): ").strip().lower()
    while iskelompok!="y" and iskelompok!="n" and iskelompok!="":
        print("Pilihan tidak valid.")
        iskelompok = input("Pengelompokan berdasarkan fungsi file (y/n): ").strip().lower()
    
    if iskelompok=="y":
        isext = input("Pengelompokan berdasarkan ekstensi file (y/n): ").strip().lower()
        while isext!="y" and isext!="n" and isext!="":
            print("Pilihan tidak valid.")
            isext = input("Pengelompokan berdasarkan ekstensi file (y/n): ").strip().lower()
        if isext == "":
            print("Dibatalkan.")
            return
    else:
        isext = "y"
    
    if iskelompok == "":
        print("Dibatalkan.")
        return
    
    organize(target_folder,iskelompok,isext)
    print(f"\nSemua file di {target_folder} sudah terorganisir.")


def main_menu():
    while True:
        print("\n===================================")
        print("         FILE MANAGER MENU         ")
        print("===================================\n")
        print("1) File Finder")
        print("2) File Organizer")
        print("3) Keluar\n")

        choice = input("Pilih opsi: ").strip()

        if choice == "1":
            run_finder()
        elif choice == "2":
            run_organizer()
        elif choice == "3":
            print("Terima kasih sudah menggunakan File Manager!")
            break
        else:
            print("Pilihan tidak valid.")


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\nDikeluarkan oleh user.")
        sys.exit(0) 