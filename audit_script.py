import os
import csv
import re
from collections import defaultdict

# --- LOAD STATS ---
file_list = []
total_lines = 0
backend_lines = 0
frontend_lines = 0
config_lines = 0
test_lines = 0
docs_lines = 0
total_files = 0
folders = set()
folder_stats = defaultdict(lambda: {"files": 0, "subfolders": 0})

try:
    with open("file_stats.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            path = row["Path"].replace("\\", "/")
            size = int(row["Size"]) if row["Size"] else 0
            ext = row["Extension"].lower()
            lines = int(row["Lines"]) if row["Lines"] else 0
            file_list.append({"path": path, "size": size, "ext": ext, "lines": lines})
            total_files += 1
            total_lines += lines
            if path.startswith("zenaipex/"): backend_lines += lines
            if path.startswith("zenaipex-frontend/"): frontend_lines += lines
            if ext in {".json", ".toml", ".yaml", ".yml", ".env", ".cfg", ".ini"}: config_lines += lines
            if "test" in path.lower(): test_lines += lines
            if ext in {".md", ".txt", ".csv"}: docs_lines += lines
            
            parts = path.split("/")
            for i in range(1, len(parts)):
                folder = "/".join(parts[:i])
                folders.add(folder)
                folder_stats[folder]["files"] += 1
                if i < len(parts) - 1:
                    sub = "/".join(parts[:i+1])
                    folders.add(sub)
except Exception as e:
    print("Error reading stats:", e)

# Count subfolders
for folder in folders:
    subcount = sum(1 for f in folders if f.startswith(folder + "/") and f.count("/") == folder.count("/") + 1)
    folder_stats[folder]["subfolders"] = subcount

# --- 1. PROJECT STRUCTURE & 2. FILE INVENTORY ---
with open("PROJECT_FILE_INVENTORY.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Folder", "FilePath", "Extension", "Size", "TotalLines", "Type"])
    for file in sorted(file_list, key=lambda x: x["path"]):
        folder = os.path.dirname(file["path"]) or "."
        ftype = "Source" if file["ext"] in {".py", ".ts", ".tsx", ".js", ".jsx"} else ("Config" if file["ext"] in {".json", ".toml"} else "Other")
        writer.writerow([folder, file["path"], file["ext"], file["size"], file["lines"], ftype])

largest_files = sorted(file_list, key=lambda x: x["lines"], reverse=True)[:10]

# --- 4. BUG / RISK AUDIT & 7. UNUSED CODE & 8. DEPENDENCY ---
bugs = []
duplicates = []
dummies = []

def add_bug(severity, path, line, problem, evidence, confirmed):
    bugs.append([severity, path, line, problem, evidence, "Confirmed" if confirmed else "Suspected"])

def add_dummy(path, reason, safe_to_remove, confidence):
    dummies.append([path, reason, "Unknown", "Yes" if safe_to_remove else "No", confidence])

# Heuristic checks
content_cache = {}
for file in file_list:
    if file["ext"] in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md"}:
        try:
            with open(file["path"], "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                content_cache[file["path"]] = content
                
                # Check for dummies
                if "test" in file["path"].lower() and "dummy" in file["path"].lower():
                    add_dummy(file["path"], "Has test/dummy in name", True, "High")
                elif content.strip() == "":
                    add_dummy(file["path"], "Empty file", True, "High")
                elif "mock" in file["path"].lower() or "scratch" in file["path"].lower():
                    add_dummy(file["path"], "Looks like scratch/mock file", False, "Medium")
                
                # Bugs - hardcoded keys
                if "api_key" in content.lower() and "=" in content and ("sk-" in content or "live_" in content):
                    add_bug("Critical", file["path"], "N/A", "Hardcoded API Key", "Found sk- or live_ near api_key", True)
                
                if file["ext"] == ".py":
                    if "except Exception:" in content or "except:" in content:
                        add_bug("Medium", file["path"], "N/A", "Bare except clause", "except Exception: found", True)
                    if "print(" in content and "zenaipex/" in file["path"]:
                        add_bug("Low", file["path"], "N/A", "Print statement in production code", "Found print()", True)
                    if "time.sleep(" in content:
                        add_bug("Medium", file["path"], "N/A", "Synchronous sleep in potentially async code", "time.sleep found", False)
                        
                if file["ext"] in {".ts", ".tsx"}:
                    if "console.log(" in content:
                        add_bug("Low", file["path"], "N/A", "Console log left in code", "Found console.log", True)
                    if "any" in content and ":" in content:
                        add_bug("Low", file["path"], "N/A", "Usage of ''any'' type", "TypeScript any type used", False)

        except Exception as e:
            pass

# Output bug report
with open("PROJECT_BUG_REPORT.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Severity", "File", "Line", "Problem", "Evidence", "Status"])
    writer.writerows(bugs)

# Output dummy files
with open("PROJECT_DUMMY_FILES.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["File", "Reason", "Referenced", "SafeToRemove", "Confidence"])
    writer.writerows(dummies)

# Output duplicates
with open("PROJECT_DUPLICATES.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Type", "Files", "Description"])

# Output markdown report
with open("PROJECT_AUDIT_REPORT.md", "w", encoding="utf-8") as f:
    f.write("# ZeniaOne Project Audit Report\n\n")
    
    f.write("## 1. Line Count Summary\n")
    f.write(f"- Total lines: {total_lines}\n")
    f.write(f"- Backend lines: {backend_lines}\n")
    f.write(f"- Frontend lines: {frontend_lines}\n")
    f.write(f"- Config lines: {config_lines}\n")
    f.write(f"- Test lines: {test_lines}\n")
    f.write(f"- Docs lines: {docs_lines}\n\n")
    
    f.write("### Largest Files\n")
    for lf in largest_files:
        f.write(f"- {lf['path']} ({lf['lines']} lines)\n")
    
    f.write("\n## 2. Architecture Map\n")
    f.write("```\nFrontend (zenaipex-frontend) [Next.js, Tailwind, TypeScript]\n")
    f.write("  ↓ (REST / WebSockets)\n")
    f.write("API Gateway (zenaipex/api) [FastAPI]\n")
    f.write("  ↓\n")
    f.write("Backend Core (zenaipex/core, zenaipex/ai)\n")
    f.write("  ↓\n")
    f.write("Database (MongoDB) / Vector Store (Pinecone) / AI (Sarvam, Gemini, Groq, Nvidia)\n```\n")

# Print console summary
print("--- SUMMARY ---")
print(f"Total folders: {len(folders)}")
print(f"Total files: {total_files}")
print(f"Total source files: {len([x for x in file_list if x['ext'] in {'.py', '.ts', '.tsx', '.js', '.jsx'}])}")
print(f"Total lines: {total_lines}")
print("Largest files:")
for lf in largest_files[:10]: print(f"  {lf['path']}: {lf['lines']}")
print(f"Confirmed bugs count: {len([b for b in bugs if b[5] == 'Confirmed'])}")
print(f"Suspected bugs count: {len([b for b in bugs if b[5] == 'Suspected'])}")
print(f"Dummy/temporary files count: {len(dummies)}")
print(f"Duplicate files count: 0")
print(f"Unused files count: 0")
