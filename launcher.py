"""Simple local front end for the Rev.03 contract reading workflow."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk


SUPPORTED_SUFFIXES = {
    ".pdf", ".doc", ".docx", ".pptx", ".xls", ".xlsx",
    ".csv", ".txt", ".md", ".html", ".htm", ".xml", ".json",
}


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class ContractReaderApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_dir = app_root()
        self.title("Parsing for Easy Reading | Rev.2.2")
        self.geometry("820x650")
        self.minsize(760, 600)
        self.configure(bg="#F5F7F8")

        self.source_path: Path | None = None
        self.workspace: Path | None = None
        self.converter_var = tk.StringVar(value="Auto")
        self.browser_var = tk.StringVar(value="Microsoft Edge")
        self.source_var = tk.StringVar(value="No document selected")
        self.workspace_var = tk.StringVar(value="No contract workspace yet")
        self.status_var = tk.StringVar(value="Select a document to create and open its contract reader.")

        self._configure_style()
        self._build_ui()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#F5F7F8")
        style.configure("Panel.TFrame", background="#FFFFFF")
        style.configure("TLabel", background="#F5F7F8", foreground="#263746", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background="#FFFFFF", foreground="#263746", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#F5F7F8", foreground="#17344A", font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", background="#F5F7F8", foreground="#637584", font=("Segoe UI", 10))
        style.configure("Section.TLabel", background="#FFFFFF", foreground="#17344A", font=("Segoe UI", 12, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(15, 9))
        style.configure("TButton", font=("Segoe UI", 9), padding=(10, 7))
        style.configure("TCombobox", padding=5)

    def _build_ui(self) -> None:
        page = ttk.Frame(self, padding=(30, 24, 30, 22))
        page.pack(fill="both", expand=True)

        ttk.Label(page, text="PARSING FOR EASY READING", foreground="#287C78",
                  font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(page, text="Contract Reader", style="Title.TLabel").pack(anchor="w", pady=(5, 2))
        ttk.Label(
            page,
            text="Select a contract and create its Markdown, JSON, and linked HTML reader in one step.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(0, 18))

        panel = ttk.Frame(page, style="Panel.TFrame", padding=20)
        panel.pack(fill="x")
        ttk.Label(panel, text="1  Prepare source", style="Section.TLabel").pack(anchor="w")
        ttk.Label(panel, text="PDF, Word, PowerPoint, Excel, text, HTML, or existing Markdown.",
                  style="Panel.TLabel").pack(anchor="w", pady=(4, 12))

        source_row = ttk.Frame(panel, style="Panel.TFrame")
        source_row.pack(fill="x")
        self.source_entry = ttk.Entry(source_row, textvariable=self.source_var, state="readonly")
        self.source_entry.pack(side="left", fill="x", expand=True, ipady=5)
        ttk.Button(source_row, text="Browse...", command=self._choose_source).pack(side="left", padx=(8, 0))

        engine_row = ttk.Frame(panel, style="Panel.TFrame")
        engine_row.pack(fill="x", pady=(14, 0))
        ttk.Label(engine_row, text="Converter", style="Panel.TLabel").pack(side="left")
        self.converter_box = ttk.Combobox(
            engine_row,
            textvariable=self.converter_var,
            values=("Auto", "MarkItDown", "MinerU"),
            state="readonly",
            width=18,
        )
        self.converter_box.pack(side="left", padx=(12, 10))
        ttk.Label(
            engine_row,
            text="Auto uses MarkItDown for text PDFs and MinerU Basic OCR for scans.",
            style="Panel.TLabel",
        ).pack(side="left")

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.pack(fill="x", pady=(18, 0))
        self.one_stop_button = ttk.Button(
            actions, text="One-stop: Parse & Open", style="Primary.TButton",
            command=self._one_stop,
        )
        self.one_stop_button.pack(side="left")
        self.prepare_button = ttk.Button(
            actions, text="Prepare Markdown",
            command=self._prepare_markdown,
        )
        self.prepare_button.pack(side="left", padx=(8, 0))
        self.setup_mineru_button = ttk.Button(
            actions, text="Set up MinerU (one-time)",
            command=self._setup_mineru,
        )
        self.setup_mineru_button.pack(side="left", padx=(8, 0))
        self.open_workspace_button = ttk.Button(
            actions, text="Open workspace", state="disabled",
            command=self._open_workspace,
        )
        self.open_workspace_button.pack(side="left", padx=(8, 0))
        self.open_prompt_button = ttk.Button(
            actions, text="Open JSON prompt", state="disabled",
            command=self._open_prompt,
        )
        self.open_prompt_button.pack(side="left", padx=(8, 0))

        second = ttk.Frame(page, style="Panel.TFrame", padding=20)
        second.pack(fill="x", pady=(14, 0))
        ttk.Label(second, text="2  Build the reader", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            second,
            text="Manual route: inspect or replace parsed\\contract.json, then build the reader.",
            style="Panel.TLabel",
        ).pack(anchor="w", pady=(4, 10))
        ttk.Label(second, textvariable=self.workspace_var, style="Panel.TLabel",
                  wraplength=700).pack(anchor="w")
        build_row = ttk.Frame(second, style="Panel.TFrame")
        build_row.pack(fill="x", pady=(12, 0))
        self.build_button = ttk.Button(
            build_row, text="Build / open viewer",
            command=self._build_viewer,
        )
        self.build_button.pack(side="left")
        ttk.Label(build_row, text="Open in:", style="Panel.TLabel").pack(side="left", padx=(12, 6))
        self.browser_picker = ttk.Combobox(
            build_row,
            textvariable=self.browser_var,
            values=("Microsoft Edge", "Google Chrome"),
            state="readonly",
            width=17,
        )
        self.browser_picker.pack(side="left")
        self.choose_workspace_button = ttk.Button(
            build_row, text="Choose existing workspace...",
            command=self._choose_workspace,
        )
        self.choose_workspace_button.pack(side="left", padx=(8, 0))

        note = ttk.Frame(page, padding=(1, 11))
        note.pack(fill="x", pady=(10, 0))
        ttk.Label(
            note,
            text="Local processing only. Automatic structure and table extraction can need source review; "
                 "each workspace keeps the source, Markdown, JSON, HTML, and operation report.",
            style="Sub.TLabel",
            wraplength=740,
        ).pack(anchor="w")

        self.progress = ttk.Progressbar(page, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 6))
        ttk.Label(page, textvariable=self.status_var, style="Sub.TLabel",
                  wraplength=740).pack(anchor="w")

    def _choose_source(self) -> None:
        patterns = " ".join("*" + suffix for suffix in sorted(SUPPORTED_SUFFIXES))
        picked = filedialog.askopenfilename(
            title="Select a contract document",
            filetypes=[
                ("Supported documents", patterns),
                ("PDF", "*.pdf"),
                ("Word (DOC/DOCX)", "*.doc *.docx"),
                ("PowerPoint (PPTX)", "*.pptx"),
                ("Excel and CSV", "*.xls *.xlsx *.csv"),
                ("Text and Markdown", "*.txt *.md"),
                ("All files", "*.*"),
            ],
        )
        if not picked:
            return
        self.source_path = Path(picked)
        self.source_var.set(str(self.source_path))
        self.status_var.set("Ready. Select a converter and choose One-stop: Parse & Open.")
        self.one_stop_button.configure(state="normal")
        self.prepare_button.configure(state="normal")

    def _powershell(self) -> str:
        for name in ("powershell.exe", "pwsh.exe"):
            found = shutil_which(name)
            if found:
                return found
        raise FileNotFoundError("PowerShell was not found.")

    def _run_process(self, args: list[str], success_callback) -> None:
        self._busy(True)

        def worker() -> None:
            try:
                result = subprocess.run(
                    args, cwd=str(self.root_dir), capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "The operation failed.").strip()
                    raise RuntimeError(detail[-5000:])
                values = {}
                for line in result.stdout.splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        values[key.strip()] = value.strip()
                self.after(0, lambda: success_callback(values, result.stdout))
            except Exception as exc:
                message = str(exc)
                self.after(0, lambda msg=message: self._failed(msg))
        threading.Thread(target=worker, daemon=True).start()

    def _prepare_markdown(self) -> None:
        if not self.source_path or not self.source_path.is_file():
            messagebox.showerror("Source document", "Select an existing document first.")
            return
        if self.source_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            messagebox.showerror("Unsupported format", "Choose a supported PDF, Office, text, or Markdown file.")
            return
        script = self.root_dir / "Process-Contract.ps1"
        if not script.is_file():
            self._failed("Process-Contract.ps1 was not found beside this program.")
            return
        try:
            powershell = self._powershell()
        except Exception as exc:
            self._failed(str(exc))
            return
        converter = self.converter_var.get()
        self.status_var.set("Preparing source copy and Markdown extraction. Large PDFs may take a while.")
        args = [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-SourceFile", str(self.source_path), "-Converter", converter,
        ]
        self._run_process(args, self._prepared)

    def _one_stop(self) -> None:
        if not self.source_path or not self.source_path.is_file():
            messagebox.showerror("Source document", "Select an existing document first.")
            return
        script = self.root_dir / "OneStop-Contract.ps1"
        if not script.is_file():
            self._failed("OneStop-Contract.ps1 was not found beside this program.")
            return
        try:
            powershell = self._powershell()
        except Exception as exc:
            self._failed(str(exc))
            return
        self.status_var.set("Creating the contract workspace, structured JSON, and HTML reader.")
        args = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-SourceFile", str(self.source_path), "-Converter", self.converter_var.get()]
        if self.browser_var.get() == "Google Chrome":
            args.append("-OpenInChrome")
        self._run_process(args, self._one_stop_done)

    def _one_stop_done(self, values: dict, _stdout: str) -> None:
        self._busy(False)
        workspace = values.get("WORKSPACE")
        viewer = values.get("VIEWER")
        if not workspace or not viewer:
            self._failed("The one-stop process did not return its workspace and viewer paths.")
            return
        self.workspace = Path(workspace)
        self.workspace_var.set(workspace)
        self.open_workspace_button.configure(state="normal")
        self.open_prompt_button.configure(state="normal")
        self.build_button.configure(state="normal")
        self.status_var.set("Reader ready: " + viewer)

    def _setup_mineru(self) -> None:
        script = self.root_dir / "Setup-MinerU.ps1"
        if not script.is_file():
            self._failed("Setup-MinerU.ps1 was not found beside this program.")
            return
        try:
            powershell = self._powershell()
        except Exception as exc:
            self._failed(str(exc))
            return
        self.status_var.set(
            "Installing MinerU 4.1.2 into the Rev.03 folder. This one-time setup may take a few minutes."
        )
        args = [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        ]
        self._run_process(args, self._mineru_ready)

    def _mineru_ready(self, _values: dict, _stdout: str) -> None:
        self._busy(False)
        self.status_var.set(
            "MinerU 4.1.2 and its Basic OCR models are ready in the Rev.03 folder."
        )

    def _prepared(self, values: dict, _stdout: str) -> None:
        self._busy(False)
        self.workspace = Path(values.get("WORKSPACE", ""))
        if not values.get("WORKSPACE") or not values.get("MARKDOWN"):
            self._failed("The converter finished without returning the workspace and Markdown paths.")
            return
        self.workspace_var.set(values["WORKSPACE"])
        self.open_workspace_button.configure(state="normal")
        self.open_prompt_button.configure(state="normal")
        self.build_button.configure(state="normal")
        self.status_var.set(
            "Markdown ready via " + values.get("CONVERTER", "the selected converter") +
            ". Review the JSON prompt, create parsed\\contract.json with the source files, then build the reader."
        )

    def _choose_workspace(self) -> None:
        picked = filedialog.askdirectory(
            title="Choose a contract workspace",
            initialdir=str(self.root_dir / "Contracts"),
        )
        if not picked:
            return
        self.workspace = Path(picked)
        self.workspace_var.set(str(self.workspace))
        parsed = self.workspace / "parsed" / "contract.json"
        self.build_button.configure(state="normal" if parsed.is_file() else "disabled")
        if parsed.is_file():
            self.status_var.set("Structured JSON found. Build the reader when ready.")
        else:
            self.status_var.set("This workspace does not yet contain parsed\\contract.json.")

    def _build_viewer(self) -> None:
        if not self.workspace or not self.workspace.is_dir():
            self._choose_workspace()
            if not self.workspace:
                return
        parsed = self.workspace / "parsed" / "contract.json"
        if not parsed.is_file():
            messagebox.showerror(
                "Parsed JSON is missing",
                "Create parsed\\contract.json using JSON-PARSING-PROMPT.md and verify it against the source PDF first.",
            )
            return
        script = self.root_dir / "Process-Contract.ps1"
        try:
            powershell = self._powershell()
        except Exception as exc:
            self._failed(str(exc))
            return
        self.status_var.set(f"Building the HTML reader and opening it in {self.browser_var.get()}.")
        browser_switch = "-OpenInEdge" if self.browser_var.get() == "Microsoft Edge" else "-OpenInChrome"
        args = [
            powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-ContractFolder", str(self.workspace), browser_switch,
        ]
        self._run_process(args, self._built)

    def _built(self, values: dict, stdout: str) -> None:
        self._busy(False)
        viewer = ""
        for line in stdout.splitlines():
            if line.strip().startswith("Viewer:"):
                viewer = line.split(":", 1)[1].strip()
                break
        self.status_var.set("Reader build complete. " + (viewer or "The HTML reader was generated."))

    def _open_workspace(self) -> None:
        if self.workspace and self.workspace.is_dir():
            os.startfile(str(self.workspace))

    def _open_prompt(self) -> None:
        if not self.workspace:
            return
        prompt = self.workspace / "parsed" / "JSON-PARSING-PROMPT.md"
        if prompt.is_file():
            os.startfile(str(prompt))
        else:
            messagebox.showerror("Prompt missing", "JSON-PARSING-PROMPT.md was not found in parsed/.")

    def _busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.one_stop_button.configure(state=state)
        self.prepare_button.configure(state=state)
        self.setup_mineru_button.configure(state=state)
        self.converter_box.configure(state="disabled" if busy else "readonly")
        self.browser_picker.configure(state="disabled" if busy else "readonly")
        self.choose_workspace_button.configure(state=state)
        self.build_button.configure(state="disabled" if busy else (
            "normal" if self.workspace and (self.workspace / "parsed" / "contract.json").is_file() else "disabled"
        ))
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _failed(self, message: str) -> None:
        self._busy(False)
        self.status_var.set("Operation stopped. Check the details and source file.")
        messagebox.showerror("Contract Reader", message)


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    ContractReaderApp().mainloop()
