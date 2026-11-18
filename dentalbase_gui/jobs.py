"""Plan processing jobs and build backend command lines. Pure Python: no Qt.

The GUI talks to the backend ONLY through the command line of make_base.py (and its printed output), so the two
stay completely decoupled."""
import json
import os
import sys
from dataclasses import dataclass, field

from .stl_io import output_path

DEFAULTS = dict(offset=4.5, smooth=6.0, loop_sigma=2.0, thickness=0.5, strip=0.0, follow_tips=False)   # strip 0 = automatic


@dataclass
class Options:
    offset: float = DEFAULTS['offset']          # gingiva margin height (mm)
    smooth: float = DEFAULTS['smooth']          # trim field smoothing
    loop_sigma: float = DEFAULTS['loop_sigma']  # trimline smoothing (mm)
    thickness: float = DEFAULTS['thickness']    # base thickness (mm)
    strip: float = DEFAULTS['strip']            # blend width along the cut edge (mm); 0 = automatic
    follow_tips: bool = DEFAULTS['follow_tips'] # base parallel to the tooth tips instead of the bite plane


@dataclass
class Job:
    kind: str                                   # 'single' | 'pair'
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)

    @property
    def label(self):
        names = ' + '.join(os.path.basename(p) for p in self.inputs)
        return ('Articulated pair: ' if self.kind == 'pair' else '') + names


def plan_jobs(files, pair):
    """files: list of (path, role) with role in {'single','upper','lower'}.
    If `pair` and there is exactly one upper and one lower, they form one articulated-pair job; everything else is a
    single job. Returns list[Job]."""
    uppers = [p for p, r in files if r == 'upper']
    lowers = [p for p, r in files if r == 'lower']
    use_pair = pair and len(uppers) == 1 and len(lowers) == 1
    jobs = []
    if use_pair:
        jobs.append(Job('pair', [uppers[0], lowers[0]], [output_path(uppers[0]), output_path(lowers[0])]))
    for p, r in files:
        if use_pair and r in ('upper', 'lower'):
            continue
        jobs.append(Job('single', [p], [output_path(p)]))
    return jobs


def build_args(job, opts, script, python=None):
    """Command line (list) that runs one job through the backend CLI."""
    py = python or sys.executable
    # packaged app: there is no separate Python, so the app re-runs itself in backend mode (see gui.py)
    head = [py, '--run-backend'] if getattr(sys, 'frozen', False) and python is None else [py, '-u', script]
    common = ['--offset', f'{opts.offset:g}', '--smooth', f'{opts.smooth:g}',
              '--loop-sigma', f'{opts.loop_sigma:g}', '--thickness', f'{opts.thickness:g}']
    if opts.strip > 0:
        common += ['--strip', f'{opts.strip:g}']
    if opts.follow_tips:
        common += ['--follow-tips']
    if job.kind == 'pair':
        return head + ['--pair', job.inputs[0], job.inputs[1], '--pair-out', job.outputs[0], job.outputs[1]] + common
    return head + [job.inputs[0], job.outputs[0]] + common


def parse_report(line):
    """Extract the JSON report the backend prints for each model, or None."""
    i = line.find('{')
    if i < 0 or '"watertight"' not in line:
        return None
    try:
        return json.loads(line[i:])
    except ValueError:
        return None


def parse_stage(line):
    """Parse the progress marker printed by the backend: '@@STAGE 3/7 Finding the teeth' -> (3, 7, 'Finding the teeth')."""
    line = line.strip()
    if not line.startswith('@@STAGE '):
        return None
    try:
        frac, _, label = line[len('@@STAGE '):].partition(' ')
        i, n = frac.split('/')
        return int(i), int(n), label.strip()
    except ValueError:
        return None


def classify(rep):
    """Outcome of a finished job from its backend report: ('ok' | 'warn' | 'bad', short reason).
    bad  = the teeth were NOT reproduced exactly. This must never happen, so it is a failure, never a warning.
    warn = finished, but worth a look: not watertight, or tunnels/handles in the surface.
    ok   = watertight, one solid (no tunnels) and the teeth exactly as scanned."""
    if rep is None:
        return 'ok', ''
    t = rep.get('crown_exact_pct')
    if t is not None and t < 100:
        return 'bad', 'tooth geometry differs from the scan'
    if not rep.get('watertight'):
        return 'warn', 'not watertight'
    if rep.get('euler') not in (None, 2):
        return 'warn', 'has tunnels (already in the scan)'
    return 'ok', ''


def summarize(rep):
    """One-line human summary of a backend report."""
    solid = 'watertight' if rep.get('watertight') else 'NOT watertight'
    if rep.get('euler') not in (None, 2):
        solid += f' (euler {rep["euler"]}: tunnels/handles)'
    t = rep.get('crown_exact_pct')
    tooth = f', teeth exact {t:g}%' if t is not None else ''
    return solid + tooth
