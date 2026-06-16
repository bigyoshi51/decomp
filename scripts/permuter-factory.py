#!/usr/bin/env python3
"""permuter-factory: unattended decomp-permuter queue-runner for the 1080 long tail.

Runs the decomp-permuter over every 90-99% near-miss in a worktree's objdiff
report, harvesting exact (objdiff-verified 100.0) matches with zero babysitting.

WHY: the permuter cracks single-operand / single-choice allocator gates (~250k
iterations each, ~50% hit rate on the few-diff band) but had only ever been
hand-managed 3-4 functions at a time. This wires up auto-discovery + per-fn
import + bounded run + objdiff-verify + commit, robust to crashes/resume, so it
can chew through the whole band on all cores unattended.

See docs/IDO_CODEGEN.md (2026-06-11 permuter calibration) and
docs/TOOLING_DECOMP.md ("permuter-factory") for the rules this encodes:
  - import.py per-fn scratch is what unlocked the regalloc gates (scoping fix).
  - The permuter's own score LIES vs objdiff fuzzy -> objdiff-verify EVERYTHING.
  - ~250k iters / ~12 min budget for a single-diff gate; multi-diff residuals
    descend fast then plateau and DON'T fall (concede them).
  - permuter base-score-0 can be a FALSE POSITIVE (symbolic cross-symbol
    branch) -> the objdiff re-verify is the real gate.
  - Kill stray procs by PID, never pkill -f (matches our own argv).

USAGE (from the worktree dir, or pass --worktree):
  python3 /path/to/decomp/scripts/permuter-factory.py \
      --worktree "/path/to/decomp/projects/1080-agent-h" \
      [--jobs 6] [--budget-secs 720] [--limit N] [--min 90 --max 100] \
      [--only fn1,fn2] [--no-commit] [--no-rediscover]

State/logs (under <worktree>/.permuter-factory/):
  progress.log     append-only timeline
  checkpoint.json  per-fn status (done/attempted) -> re-run resumes
  scoreboard.json  final tally
"""

import argparse
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

# ---- cap markers: skip functions whose wrap comment already concedes them ----
CAP_MARKERS = [
    "cap stands",
    "no c handle",
    "allocator-internal",
    "allocator internal",
    "permuter-immune",
    "permuter resists",
    "permuter-proof",
    "permuter-class",
    "permuter floors",
    "genuine cap",
    "scheduling cap",
    "scheduling swap",
    "uopt-internal",
    "not c-reachable",
    "not c-flippable",
    "regalloc-renumber",
]

SCORE_RE = re.compile(r"score\s*=\s*(-?\d+)")
ITER_RE = re.compile(r"iteration\s+(\d+)")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Factory:
    def __init__(self, args):
        self.args = args
        self.worktree = os.path.abspath(args.worktree)
        # repo root = the monorepo that holds tools/decomp-permuter
        self.repo_root = self._find_repo_root()
        self.permuter_dir = os.path.join(self.repo_root, "tools", "decomp-permuter")
        self.import_py = os.path.join(self.permuter_dir, "import.py")
        self.permuter_py = os.path.join(self.permuter_dir, "permuter.py")
        self.state_dir = os.path.join(self.worktree, ".permuter-factory")
        os.makedirs(self.state_dir, exist_ok=True)
        self.log_path = os.path.join(self.state_dir, "progress.log")
        self.ckpt_path = os.path.join(self.state_dir, "checkpoint.json")
        self.scoreboard_path = os.path.join(self.state_dir, "scoreboard.json")
        self.checkpoint = self._load_checkpoint()
        self.report_path = os.path.join(self.state_dir, "report.json")
        self._active_proc = None  # current permuter Popen, for clean shutdown
        for p in (self.import_py, self.permuter_py):
            if not os.path.isfile(p):
                self.die(f"permuter tool not found: {p}")
        # On SIGTERM/SIGINT, kill the active permuter process group before exit
        # (the finally: cleanup doesn't run when the signal kills us mid-readline).
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)

    def _on_signal(self, signum, frame):
        self.log(f"received signal {signum} -> killing active permuter and exiting")
        if self._active_proc is not None:
            self._kill_proc_tree(self._active_proc)
        sys.exit(143)

    def _find_repo_root(self):
        # worktree is .../decomp/projects/<x>; walk up until tools/decomp-permuter
        d = self.worktree
        for _ in range(6):
            if os.path.isdir(os.path.join(d, "tools", "decomp-permuter")):
                return d
            d = os.path.dirname(d)
        # fallback: monorepo is two levels above projects/<x>
        return os.path.abspath(os.path.join(self.worktree, "..", ".."))

    def die(self, msg):
        self.log(f"FATAL: {msg}")
        sys.exit(1)

    def log(self, msg):
        line = f"[{now()}] {msg}"
        print(line, flush=True)
        with open(self.log_path, "a") as f:
            f.write(line + "\n")

    def _load_checkpoint(self):
        if os.path.isfile(self.ckpt_path):
            try:
                return json.load(open(self.ckpt_path))
            except Exception:
                pass
        return {}

    def _save_checkpoint(self):
        tmp = self.ckpt_path + ".tmp"
        json.dump(self.checkpoint, open(tmp, "w"), indent=2)
        os.replace(tmp, self.ckpt_path)

    # ---------------------------------------------------------------- discovery
    def generate_report(self):
        self.log("generating fresh objdiff report ...")
        subprocess.run(
            ["make", "non_matching_objects"],
            cwd=self.worktree,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["objdiff-cli", "report", "generate", "-o", self.report_path],
            cwd=self.worktree,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def discover(self):
        """Return list of dicts: {name, size, fuzzy, unit, src, asm}."""
        if self.args.no_rediscover and os.path.isfile(self.report_path):
            self.log("reusing existing report (--no-rediscover)")
        else:
            self.generate_report()
        report = json.load(open(self.report_path))
        # map unit name -> source .c (from objdiff.json metadata)
        unit_src = {}
        objdiff_cfg = os.path.join(self.worktree, "objdiff.json")
        if os.path.isfile(objdiff_cfg):
            cfg = json.load(open(objdiff_cfg))
            for u in cfg.get("units", []):
                sp = (u.get("metadata") or {}).get("source_path")
                if sp:
                    unit_src[u["name"]] = sp
        lo, hi = self.args.min, self.args.max
        cands = []
        only = (
            set(s.strip() for s in self.args.only.split(","))
            if self.args.only
            else None
        )
        for u in report["units"]:
            uname = u["name"]
            for f in u.get("functions") or []:
                fz = f.get("fuzzy_match_percent", 0.0)
                name = f["name"]
                if only is not None:
                    if name not in only:
                        continue
                elif not (lo <= fz < hi):
                    continue
                size = int(f.get("size", 0))
                src = unit_src.get(uname)
                if not src:
                    src = uname + ".c" if not uname.endswith(".c") else uname
                cands.append(
                    {
                        "name": name,
                        "size": size,
                        "fuzzy": fz,
                        "unit": uname,
                        "src": src,
                    }
                )
        # ordering: "size" desc (most code to gain first, default/spec) or
        # "fuzzy" desc (closest-to-100 first = fewest diffs = highest crack
        # yield per minute; the permuter cracks single-diff gates, not the big
        # multi-diff structural ones).
        if self.args.sort == "fuzzy":
            cands.sort(key=lambda c: (-c["fuzzy"], -c["size"]))
        else:
            cands.sort(key=lambda c: -c["size"])
        # resolve asm path + cap-filter
        out = []
        for c in cands:
            asm = self._find_asm(c["name"])
            if not asm:
                self.log(f"skip {c['name']}: no asm .s found")
                continue
            c["asm"] = asm
            if self._is_capped(c):
                self.log(f"skip {c['name']}: cap marker in wrap comment")
                self.checkpoint.setdefault(c["name"], {})["status"] = "capped-precheck"
                continue
            out.append(c)
        self._save_checkpoint()
        return out

    def _find_asm(self, fn):
        try:
            r = subprocess.run(
                ["find", "asm", "-name", f"{fn}.s"],
                cwd=self.worktree,
                capture_output=True,
                text=True,
                check=True,
            )
            paths = [p for p in r.stdout.splitlines() if p.strip()]
            return paths[0] if paths else None
        except Exception:
            return None

    def _read_src(self, src):
        p = os.path.join(self.worktree, src)
        return open(p).read() if os.path.isfile(p) else ""

    def _is_capped(self, c):
        """Look at the function's NM wrap block for a cap concession comment."""
        body = self._extract_nm_body(c["src"], c["name"])
        if body is None:
            # no #ifdef NON_MATCHING body -> import.py can't see it; skip.
            self.log(
                f"skip {c['name']}: no #ifdef NON_MATCHING body (import.py needs one)"
            )
            return True
        low = body.lower()
        return any(m in low for m in CAP_MARKERS)

    # -------------------------------------------------- NM-body splice helpers
    def _locate_nm_block(self, text, fn):
        """Find (def_start, body_start, else_idx) line indices of the fn's
        #ifdef NON_MATCHING { body } #else block. Returns None if not found."""
        lines = text.splitlines(keepends=True)
        # find the definition line for this fn that is preceded by #ifdef NON_MATCHING
        def_re = re.compile(r"\b" + re.escape(fn) + r"\s*\(")
        for i, ln in enumerate(lines):
            if "#ifdef NON_MATCHING" in ln:
                # scan forward a few lines for the def
                for j in range(i + 1, min(i + 6, len(lines))):
                    if def_re.search(lines[j]) and "INCLUDE_ASM" not in lines[j]:
                        # find the matching #else after the def
                        for k in range(j + 1, len(lines)):
                            if (
                                lines[k].startswith("#else")
                                or lines[k].strip() == "#else"
                            ):
                                return (i, j, k, lines)
                            if "#ifdef NON_MATCHING" in lines[k]:
                                break  # ran into next fn; abort
                        break
        return None

    def _extract_nm_body(self, src, fn):
        text = self._read_src(src)
        loc = self._locate_nm_block(text, fn)
        if not loc:
            return None
        i, j, k, lines = loc
        return "".join(lines[i:k])

    def _extract_func_brace_body(self, text, fn):
        """From C text, return the brace-balanced body INCLUDING the outer { }
        of the definition of `fn` (the first def, not a prototype). None if not
        found. Skips prototype lines ending in ';' before the '{'."""
        m = re.search(r"\b" + re.escape(fn) + r"\s*\(", text)
        if not m:
            return None
        # find the opening brace after the signature (skip ');' prototype)
        idx = m.end()
        depth_paren = 1
        n = len(text)
        # walk past the arg-list parens
        while idx < n and depth_paren > 0:
            ch = text[idx]
            if ch == "(":
                depth_paren += 1
            elif ch == ")":
                depth_paren -= 1
            idx += 1
        # now skip whitespace; if next non-ws is ';' it's a prototype -> search next
        j2 = idx
        while j2 < n and text[j2] in " \t\r\n":
            j2 += 1
        if j2 < n and text[j2] == ";":
            # prototype; recurse on the remainder
            rest = self._extract_func_brace_body(text[idx:], fn)
            return rest
        # find the opening brace
        while idx < n and text[idx] != "{":
            idx += 1
        if idx >= n:
            return None
        start = idx
        depth = 0
        while idx < n:
            ch = text[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : idx + 1]
            idx += 1
        return None

    def splice_body(self, src, fn, new_func_c):
        """Replace ONLY the brace body of fn inside the #ifdef NON_MATCHING block,
        keeping the original signature line. The permuter's source.c carries a
        preamble (typedef u32/s32, struct defs, externs) that would collide with
        the full TU, so we splice only the { ... } body. Returns the original
        full text (for revert), or None on failure."""
        p = os.path.join(self.worktree, src)
        text = open(p).read()
        loc = self._locate_nm_block(text, fn)
        if not loc:
            return None
        new_body = self._extract_func_brace_body(new_func_c, fn)
        if not new_body:
            return None
        orig_body = self._extract_func_brace_body(text, fn)
        if not orig_body:
            return None
        # replace the first occurrence of the original brace body with the new one
        new_text = text.replace(orig_body, new_body, 1)
        if new_text == text:
            return None
        open(p, "w").write(new_text)
        return text

    def restore(self, src, original_text):
        open(os.path.join(self.worktree, src), "w").write(original_text)

    # ---------------------------------------------- permuter winning-output read
    def _scratch_dir(self, fn):
        # import.py creates nonmatchings/<fn> (or <fn>-<n> on collision)
        base = os.path.join(self.worktree, "nonmatchings")
        exact = os.path.join(base, fn)
        if os.path.isdir(exact):
            return exact
        # pick newest matching prefix
        cands = [
            d
            for d in (os.listdir(base) if os.path.isdir(base) else [])
            if d == fn or d.startswith(fn + "-")
        ]
        if not cands:
            return None
        cands.sort(key=lambda d: os.path.getmtime(os.path.join(base, d)))
        return os.path.join(base, cands[-1])

    def _best_output_source(self, scratch):
        """Return path to best (lowest-score) output source.c, score-0 first."""
        if not scratch or not os.path.isdir(scratch):
            return None, None
        outs = []
        for d in os.listdir(scratch):
            m = re.match(r"output-(-?\d+)-", d)
            if m:
                sc = int(m.group(1))
                sp = os.path.join(scratch, d, "source.c")
                if os.path.isfile(sp):
                    outs.append((sc, sp))
        if not outs:
            return None, None
        outs.sort(key=lambda x: x[0])
        return outs[0][1], outs[0][0]

    # ------------------------------------------------------------- objdiff verify
    def verify_fuzzy(self, fn):
        """Rebuild + objdiff; return the function's current fuzzy %, or None."""
        r = subprocess.run(
            ["make", "non_matching_objects"],
            cwd=self.worktree,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            return None  # build broke -> treat as failure
        rep = os.path.join(self.state_dir, "verify.json")
        v = subprocess.run(
            ["objdiff-cli", "report", "generate", "-o", rep],
            cwd=self.worktree,
            capture_output=True,
            text=True,
        )
        if v.returncode != 0:
            return None
        report = json.load(open(rep))
        for u in report["units"]:
            for f in u.get("functions") or []:
                if f["name"] == fn:
                    return f.get("fuzzy_match_percent", 0.0)
        return None

    # ------------------------------------------------------------------- run one
    def run_one(self, c):
        fn = c["name"]
        self.log(f">>> {fn} (size={c['size']} fuzzy={c['fuzzy']:.2f} unit={c['unit']})")
        st = self.checkpoint.setdefault(fn, {})
        st["status"] = "running"
        st["started"] = now()
        st["fuzzy_before"] = c["fuzzy"]
        self._save_checkpoint()

        # 1) import scratch (fresh)
        scratch_existing = self._scratch_dir(fn)
        if scratch_existing:
            shutil.rmtree(scratch_existing, ignore_errors=True)
        imp = subprocess.run(
            [
                "python3",
                self.import_py,
                c["src"],
                c["asm"],
                "CPPFLAGS=-I include -I src -DNON_MATCHING",
            ],
            cwd=self.worktree,
            capture_output=True,
            text=True,
        )
        scratch = self._scratch_dir(fn)
        if imp.returncode != 0 or not scratch:
            self.log(
                f"    import FAILED: {imp.stderr.strip().splitlines()[-1] if imp.stderr.strip() else imp.returncode}"  # noqa: E501
            )
            st["status"] = "import-error"
            self._save_checkpoint()
            return "errored"

        # 2) bounded permuter run
        best_score = self._permute(fn, scratch)
        st["best_permuter_score"] = best_score

        # 3) pick best output, splice, objdiff-verify
        src_out, out_score = self._best_output_source(scratch)
        if src_out is None:
            self.log(f"    no improved output (best permuter score={best_score})")
            st["status"] = "no-improvement"
            self._save_checkpoint()
            return "capped"

        with open(src_out) as f:
            new_c = f.read()
        original = self.splice_body(c["src"], fn, new_c)
        if original is None:
            self.log("    splice FAILED (NM block not located)")
            st["status"] = "splice-error"
            self._save_checkpoint()
            return "errored"

        verified = self.verify_fuzzy(fn)
        if verified is None:
            self.log("    verify build/objdiff FAILED -> reverting")
            self.restore(c["src"], original)
            self.verify_fuzzy(fn)  # rebuild clean
            st["status"] = "verify-build-broke"
            self._save_checkpoint()
            return "errored"

        st["fuzzy_after"] = verified
        st["permuter_output_score"] = out_score
        self.log(
            f"    permuter best={best_score} output_score={out_score} -> objdiff fuzzy={verified:.4f} (was {c['fuzzy']:.4f})"  # noqa: E501
        )

        if verified >= 100.0 - 1e-6:
            self.log("    *** VERIFIED 100.0 — crack ***")
            st["status"] = "cracked"
            self._save_checkpoint()
            if not self.args.no_commit:
                self._commit(fn, c["src"])
            return "cracked"
        elif verified > c["fuzzy"] + 1e-6:
            # genuine improvement but not a match: keep the better NM body, commit
            self.log(
                f"    improved {c['fuzzy']:.2f} -> {verified:.2f} (not 100) — keeping NM body"  # noqa: E501
            )
            st["status"] = "improved"
            self._save_checkpoint()
            if not self.args.no_commit:
                self._commit(fn, c["src"], matched=False)
            return "improved"
        else:
            self.log(
                f"    no objdiff gain ({verified:.2f} <= {c['fuzzy']:.2f}) -> reverting"
            )
            self.restore(c["src"], original)
            self.verify_fuzzy(fn)  # rebuild clean
            st["status"] = "capped"
            self._save_checkpoint()
            return "capped"

    def _permute(self, fn, scratch):
        """Run permuter with a wall-clock cap; return best score seen.
        Stops early on score 0. Kills children by PID (never pkill -f)."""
        out_path = os.path.join(self.state_dir, f"perm_{fn}.out")
        cmd = [
            "python3",
            self.permuter_py,
            scratch,
            "--best-only",
            "-j",
            str(self.args.jobs),
            "--stop-on-zero",
        ]
        self.log(
            f"    permuting (budget {self.args.budget_secs}s, -j{self.args.jobs}) ..."
        )
        best = None
        deadline = time.time() + self.args.budget_secs
        with open(out_path, "wb") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=self.worktree,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # own process group for clean kill
            )
            self._active_proc = proc
            last_iter = 0
            fd = proc.stdout.fileno()
            try:
                while True:
                    if proc.poll() is not None:
                        # drain any remaining buffered output
                        rest = proc.stdout.read() or b""
                        if rest:
                            logf.write(rest)
                            best, last_iter = self._scan(rest, best, last_iter)
                        break
                    if time.time() > deadline:
                        self.log(f"    budget reached (iter~{last_iter}) -> stopping")
                        break
                    # poll the pipe with a 1s timeout so the deadline is enforced
                    # even when --best-only keeps the permuter silent for minutes
                    # (a blocking readline would never return -> budget ignored).
                    ready, _, _ = select.select([fd], [], [], 1.0)
                    if not ready:
                        continue
                    line = proc.stdout.readline()
                    if not line:
                        if proc.poll() is not None:
                            break
                        continue
                    logf.write(line)
                    logf.flush()
                    best, last_iter = self._scan(line, best, last_iter)
                    if best is not None and best <= 0:
                        # found a score-0 candidate; let stop-on-zero finish
                        time.sleep(2)
                        if proc.poll() is not None:
                            break
            finally:
                self._kill_proc_tree(proc)
                self._active_proc = None
        return best

    def _scan(self, raw, best, last_iter):
        """Update (best, last_iter) from a raw bytes chunk of permuter output."""
        txt = raw.decode("utf-8", "replace")
        for chunk in txt.replace("\r", "\n").split("\n"):
            m = SCORE_RE.search(chunk)
            if m:
                sc = int(m.group(1))
                if best is None or sc < best:
                    best = sc
            mi = ITER_RE.search(chunk)
            if mi:
                last_iter = int(mi.group(1))
        return best, last_iter

    def _kill_proc_tree(self, proc):
        """Kill the permuter process group by PID. NEVER pkill -f (it would
        match this script's own argv)."""
        if proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            proc.wait(timeout=10)
        except Exception:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _commit(self, fn, src, matched=True):
        msg = (
            f"{fn} permuter-factory crack to 100.0 (NM body, pending land)"
            if matched
            else f"{fn} permuter-factory improve NM body (pending land)"
        )
        # stage ONLY the edited source file (never the gitignored-or-not state
        # dir / logs / nonmatchings scratch).
        subprocess.run(["git", "add", "--", src], cwd=self.worktree, check=False)
        r = subprocess.run(
            [
                "git",
                "commit",
                "-m",
                msg,
                "-m",
                "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
            ],
            cwd=self.worktree,
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            self.log(f"    committed: {msg}")
            self.checkpoint[fn]["committed"] = True
        else:
            self.log(
                f"    commit skipped/failed: {r.stdout.strip()} {r.stderr.strip()}"
            )
        self._save_checkpoint()

    # ------------------------------------------------------------------- driver
    def run(self):
        self.log(f"=== permuter-factory start (worktree={self.worktree}) ===")
        self.log(
            f"repo_root={self.repo_root} jobs={self.args.jobs} budget={self.args.budget_secs}s"  # noqa: E501
        )
        cands = self.discover()
        self.log(
            f"discovered {len(cands)} candidates in band [{self.args.min},{self.args.max})"  # noqa: E501
        )
        if self.args.limit:
            cands = cands[: self.args.limit]
            self.log(f"limited to first {len(cands)}")

        tally = {
            "attempted": 0,
            "cracked": 0,
            "improved": 0,
            "capped": 0,
            "errored": 0,
            "skipped-done": 0,
        }
        cracked, improved, newcaps = [], [], []
        overall_deadline = (
            time.time() + self.args.total_budget_secs
            if self.args.total_budget_secs
            else None
        )

        for c in cands:
            fn = c["name"]
            prev = self.checkpoint.get(fn, {})
            if prev.get("status") in ("cracked", "improved") and prev.get("committed"):
                self.log(f"--- {fn}: already done ({prev['status']}), skipping")
                tally["skipped-done"] += 1
                continue
            if overall_deadline and time.time() > overall_deadline:
                self.log("=== total budget exhausted, stopping queue ===")
                break
            tally["attempted"] += 1
            try:
                result = self.run_one(c)
            except KeyboardInterrupt:
                self.log("interrupted by user")
                break
            except Exception as e:
                self.log(f"    EXCEPTION on {fn}: {e!r}")
                self.checkpoint.setdefault(fn, {})["status"] = "exception"
                self._save_checkpoint()
                result = "errored"
            if result == "cracked":
                tally["cracked"] += 1
                cracked.append(fn)
            elif result == "improved":
                tally["improved"] += 1
                improved.append(fn)
            elif result == "capped":
                tally["capped"] += 1
                newcaps.append(fn)
            else:
                tally["errored"] += 1
            self._write_scoreboard(tally, cracked, improved, newcaps)

        self._write_scoreboard(tally, cracked, improved, newcaps)
        self.log("=== SCOREBOARD ===")
        self.log(json.dumps(tally))
        self.log(f"CRACKED (commit for land): {cracked}")
        self.log(f"IMPROVED (non-100 NM, committed): {improved}")
        self.log(f"NEW CAPS (no objdiff gain): {newcaps}")
        return tally

    def _write_scoreboard(self, tally, cracked, improved, newcaps):
        json.dump(
            {
                "updated": now(),
                "tally": tally,
                "cracked": cracked,
                "improved": improved,
                "new_caps": newcaps,
            },
            open(self.scoreboard_path, "w"),
            indent=2,
        )


def main():
    ap = argparse.ArgumentParser(description="Unattended decomp-permuter factory.")
    ap.add_argument(
        "--worktree", default=os.getcwd(), help="project worktree dir (default: cwd)"
    )
    ap.add_argument("--jobs", "-j", type=int, default=6, help="permuter threads")
    ap.add_argument(
        "--budget-secs",
        type=int,
        default=720,
        help="per-function wall-clock cap (~250k iters @ -j6 ~= 720s)",
    )
    ap.add_argument(
        "--total-budget-secs",
        type=int,
        default=0,
        help="overall wall-clock cap for the whole queue (0=unbounded)",
    )
    ap.add_argument("--limit", type=int, default=0, help="max functions to attempt")
    ap.add_argument(
        "--sort",
        choices=["size", "fuzzy"],
        default="size",
        help="queue order: 'size' desc (default/spec) or 'fuzzy' desc "
        "(closest-to-100 first = fewest diffs = highest crack yield/min)",
    )
    ap.add_argument("--min", type=float, default=90.0, help="band lower bound")
    ap.add_argument(
        "--max", type=float, default=100.0, help="band upper bound (exclusive)"
    )
    ap.add_argument("--only", default="", help="comma-separated explicit function list")
    ap.add_argument("--no-commit", action="store_true", help="don't git-commit cracks")
    ap.add_argument(
        "--no-rediscover",
        action="store_true",
        help="reuse existing report.json instead of rebuilding",
    )
    args = ap.parse_args()
    Factory(args).run()


if __name__ == "__main__":
    main()
