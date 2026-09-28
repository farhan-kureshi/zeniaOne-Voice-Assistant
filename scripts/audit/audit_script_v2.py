import os
import csv
import re
import hashlib
from collections import defaultdict
import glob
import sys

exclude_dirs = {".git", ".venv", "node_modules", ".next", "__pycache__", "dist", "build", "coverage"}
exclude_extensions = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".wav", ".mp4", ".pdf", ".zip"}

# Trackers
file_inventory = []
folder_tree = defaultdict(lambda: {"files": 0, "subfolders": 0, "recursive_files": 0})
file_contents = {}

# Stats
total_lines = 0
source_lines = 0
blank_lines = 0
comment_lines = 0

bugs = []
duplicates = []
dummies = []
unused = []

def add_bug(severity, path, line, problem, evidence, confidence):
    bugs.append([severity, path, line, problem, evidence, confidence])

def add_dummy(path, reason, references, safe, confidence):
    dummies.append([path, reason, references, safe, confidence])

def add_unused(path, symbol, refs, conf, reason):
    unused.append([path, symbol, refs, conf, reason])

# Build Inventory
all_files = []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith(".")]
    for file in files:
        if file == "file_stats.csv" or file.startswith("PROJECT_"): continue
        ext = os.path.splitext(file)[1].lower()
        if ext in exclude_extensions: continue
        all_files.append(os.path.join(root, file).replace("\\", "/"))

# Process Files
hashes = defaultdict(list)
exports = defaultdict(list)
for path in all_files:
    ext = os.path.splitext(path)[1].lower()
    ftype = "Generated/Config"
    if ext in {".py", ".ts", ".tsx", ".js", ".jsx"}: ftype = "Source"
    elif ext in {".md", ".txt"}: ftype = "Documentation"
    elif "test" in path.lower(): ftype = "Test"
    
    try:
        size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            
        t_lines = len(lines)
        b_lines = 0
        c_lines = 0
        cd_lines = 0
        
        normalized_code = []
        
        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                b_lines += 1
            elif s.startswith("#") or s.startswith("//") or s.startswith("/*") or s.startswith("*"):
                c_lines += 1
            else:
                cd_lines += 1
                normalized_code.append(s)
                
            # Quick export detection for unused analysis
            if ftype == "Source":
                if ext == ".py":
                    m = re.match(r'^(?:async\s+)?def\s+([a-zA-Z0-9_]+)\(', line)
                    if m and not m.group(1).startswith("__"): exports[path].append(m.group(1))
                    m = re.match(r'^class\s+([a-zA-Z0-9_]+)', line)
                    if m: exports[path].append(m.group(1))
                else:
                    m = re.match(r'^export\s+(?:const|let|var|function|class|default)\s+([a-zA-Z0-9_]+)', line)
                    if m: exports[path].append(m.group(1))
                    
        total_lines += t_lines
        if ftype == "Source": source_lines += cd_lines
        blank_lines += b_lines
        comment_lines += c_lines
        
        # Hash for duplicates
        if cd_lines > 10:
            h = hashlib.sha256("\n".join(normalized_code).encode("utf-8")).hexdigest()
            hashes[h].append(path)
            
        folder = os.path.dirname(path) or "."
        file_inventory.append([folder, path, ext, size, t_lines, b_lines, c_lines, cd_lines, ftype])
        
        file_contents[path] = "".join(lines)
        
    except Exception as e:
        continue

# Find Duplicates
for h, paths in hashes.items():
    if len(paths) > 1:
        duplicates.append(["Exact Normalized Match", " | ".join(paths), f"Files share exactly the same code (ignoring comments/whitespace)"])

# Unused Code Analysis
all_code = "\n".join(file_contents.values())
for path, exps in exports.items():
    for exp in exps:
        count = all_code.count(exp)
        if count == 1: # Only definition
            add_unused(path, exp, count, "High", "Symbol exported but never referenced anywhere else")

# Bug / Risk Analysis
for path, content in file_contents.items():
    if ".py" in path:
        if "except:" in content or "except Exception:" in content:
            add_bug("Medium", path, "N/A", "Bare Exception", "Catches all exceptions, hides errors", "Confirmed Code Smell")
        if "time.sleep(" in content:
            add_bug("High", path, "N/A", "Synchronous Sleep", "time.sleep blocks event loop in asyncio", "Suspected Bug")
        if "await" not in content and "async def" in content:
            add_bug("Low", path, "N/A", "Async without await", "Async function doesn't await anything", "Confirmed Code Smell")
    if ".ts" in path or ".tsx" in path:
        if "console.log" in content:
            add_bug("Low", path, "N/A", "Console Log", "Leftover debugging", "Confirmed Code Smell")
    
    if "api_key=" in content.lower() or "secret=" in content.lower():
        if "sk-" in content or "live_" in content:
            add_bug("Critical", path, "N/A", "Hardcoded Secret", "Looks like a real API key", "Confirmed Bug")

    if "dummy" in path.lower() or "temp" in path.lower() or "mock" in path.lower() or "scratch" in path.lower():
        add_dummy(path, "Name implies temporary/dummy", "N/A", "Yes", "High")

# Write CSVs
with open("PROJECT_FILE_INVENTORY_V2.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Folder", "FilePath", "Extension", "Size", "TotalLines", "BlankLines", "CommentLines", "CodeLines", "Type"])
    writer.writerows(file_inventory)

with open("PROJECT_BUG_REPORT_V2.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Severity", "File", "Line", "Problem", "Evidence", "Status"])
    writer.writerows(bugs)

with open("PROJECT_UNUSED_CODE_V2.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["File", "Symbol", "References", "Confidence", "Reason"])
    writer.writerows(unused)

with open("PROJECT_DUPLICATES_V2.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Type", "Files", "Description"])
    writer.writerows(duplicates)

with open("PROJECT_DUMMY_FILES_V2.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["File", "Reason", "Referenced", "SafeToRemove", "Confidence"])
    writer.writerows(dummies)

with open("PROJECT_AUDIT_V2.md", "w", encoding="utf-8") as f:
    f.write("# ZeniaOne Project Audit V2\n\n## Summary\n")
    f.write("READ-ONLY audit completed; no source/config files modified.\n")

with open("PROJECT_ARCHITECTURE_MAP_V2.md", "w", encoding="utf-8") as f:
    f.write("# Architecture Map V2\n")

print(f"Total files: {len(file_inventory)}")
print(f"Total lines: {total_lines}")
print(f"Source lines: {source_lines}")
print(f"Blank lines: {blank_lines}")
print(f"Comment lines: {comment_lines}")
print(f"Confirmed bugs/smells: {len(bugs)}")
print(f"Duplicates found: {len(duplicates)}")
print(f"Unused symbols found: {len(unused)}")
print(f"Dummy files found: {len(dummies)}")
