from pathlib import Path

def print_tree(path, prefix=""):
    # .venv is nu toegevoegd aan de lijst met te negeren mappen
    ignore_list = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "dist1", "Output", "Results_Dispatcher", "results", "log", "output", "report"}
    
    # Sorteer mappen eerst, daarna bestanden
    items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
    
    for i, item in enumerate(items):
        if item.name in ignore_list:
            continue
            
        is_last = (i == len(items) - 1)
        connector = "└── " if is_last else "├── "
        
        print(f"{prefix}{connector}{item.name}")
        
        if item.is_dir():
            extension = "    " if is_last else "│   "
            print_tree(item, prefix + extension)

if __name__ == "__main__":
    project_root = Path.cwd()
    print(f"Project structuur van: {project_root.name}/.venv/Lib/site-packages/degiro_portfolio\n")
    print_tree(project_root / ".venv" / "Lib" / "site-packages" / "degiro_portfolio")
