#!/usr/bin/env python3
"""
DSSErrors.log analyzer
=======================

Analyzes the memory lead-up to a MicroStrategy MCM (Memory Contract Manager)
denial event.

Workflow:
  1. Run the script and point it at a DSSErrors.log.
  2. The script pre-scans the log and presents a numbered list of distinct MCM
     denial events (grouped by recovery — a new event only counts after the
     I-Server has returned to State=normal).
  3. You pick which event to analyze.
  4. The script then shows how far back AvailableMCM headroom was at various
     thresholds, and lets you choose your analysis window. This replaces the
     old "manually pick a start line" approach and is adaptive to machine size
     (thresholds are expressed as % of the High Watermark, not absolute GB).
  5. Output: one text report + one CSV.

Report sections:
  SECTION 1 — Memory state at denial (physical/virtual breakdown, MCM settings)
  SECTION 2 — Per-OID memory granted in the chosen window, broken down by
               Source= request type so you can see what kind of operation each
               object was performing (XTabColumn, Cube, GovernedObject, etc.)
"""

import re
import csv
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

TIMESTAMP_RE  = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)')
SID_RE        = re.compile(r'\[SID:(0|[A-Fa-f0-9]{32})\]')
OID_RE        = re.compile(r'\[OID:(0|[A-Fa-f0-9]{32})\]')
SIZE_RE       = re.compile(r'\bSize=(\d+)')
SOURCE_RE     = re.compile(r'\bSource=([\w:]+)')
AVAIL_MCM_RE  = re.compile(r'\bAvailableMCM=(\d+)')
HWM_RE        = re.compile(r'\bHWM\(\w+\)=(\d+)')

SUCCESS_MARKER      = "Contract Request Succeeded"
DENIAL_MARKER       = "IServer enters MCM denial state"
NORMAL_MARKER       = "State=normal"
CURRENT_INFO_MARKER = "Current Memory Info:"
MCM_SETTINGS_MARKER = "MCM Settings:"

# "Label(UNIT): value" lines in the detailed breakdown block.
# The (.+?) before the unit is intentionally permissive — labels can contain
# parentheses themselves (e.g. "...Memory(Including MMF) For...").
DETAIL_LINE_RE = re.compile(r'^\t*(.+?)\((GB|MB|KB)\):\s*(-?\d+)\s*$')

# "Label = value (human UNIT)" lines in abbreviated blocks.
ABBREV_LINE_RE = re.compile(
    r'^([A-Za-z][A-Za-z0-9 /\-]*?)\s*=\s*(unlimited|true|false|-?\d+)\s*'
    r'(?:\(([\d.]+)\s*(TB|GB|MB|KB)\))?\s*$'
)

UNIT_TO_MB = {'KB': 1/1024, 'MB': 1, 'GB': 1024, 'TB': 1024*1024}

def to_mb(value, unit):
    return value * UNIT_TO_MB[unit]


# ---------------------------------------------------------------------------
# Thresholds (% of HWM, machine-independent)
# ---------------------------------------------------------------------------

# Windows presented to the user for the analysis scope (improvement 5).
# Expressed as % of HWM so they mean the same thing on a 62 GB box and a
# 1 TB box. Shown in descending order so the user sees widest → narrowest.
WINDOW_THRESHOLDS_PCT = [25, 15, 10, 5, 2]

# Section 1 diagnostic thresholds
THRESHOLDS = {
    'other_processes_pct_physical':   (10, 20),   # (watch, review)
    'working_set_pct_iserver_max':    20,          # single upper bound
    'other_memory_pct_iserver_flag':  50,          # single flag
    'cube_pct_iserver_flag':          40,          # cube cache % of IServer virtual that warrants MMF check
    'mmf_pct_of_cube_low':            10,          # MMF covering <10% of cube cache = underutilized
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt(num_bytes):
    """Format a byte count in the most readable unit."""
    gb = num_bytes / (1024**3)
    if gb >= 1:   return f"{gb:.2f} GB"
    mb = num_bytes / (1024**2)
    if mb >= 1:   return f"{mb:.2f} MB"
    return f"{num_bytes / 1024:.2f} KB"

def fmt_mb(mb):
    if mb >= 1024: return f"{mb/1024:.2f} GB"
    return f"{mb:.1f} MB"

def pct(part, whole):
    return 0.0 if not whole else (part / whole) * 100


# ---------------------------------------------------------------------------
# Pre-scan: find distinct MCM events
# ---------------------------------------------------------------------------

def prescan(lines):
    """
    Single pass to identify all distinct MCM denial episodes.

    A 'distinct event' is a denial episode separated from the next either by a
    State=normal recovery line OR by new Contract Request Succeeded activity
    appearing between two denial lines (indicating partial recovery even without
    an explicit State=normal). Same-burst repeated denial lines within the same
    second with no intervening Succeeded lines are collapsed into one event.

    Returns a list of event dicts, one per distinct episode, each carrying:
      - denial_lineno   : line number of the FIRST denial line in this episode
      - denial_ts       : timestamp of that line
      - recovery_lineno : line number of the State=normal that ended it
                          (None if the log ends mid-episode)
      - hwm_bytes       : High Watermark in bytes from the last succeeded line
                          before denial (used to scale threshold menus)
      - avail_timeline  : list of (lineno, avail_mcm_bytes, hwm_bytes) for
                          succeeded lines between this event's previous recovery
                          (or file start) and this event's denial line — i.e.
                          only the activity that belongs to this episode's
                          lead-up, not prior episodes.
    """
    events      = []
    in_denial   = False
    current_event_start_line = None
    current_event_start_ts   = None
    prev_recovery_lineno     = 0   # lines at or before this belong to prior events

    # (lineno, avail_mcm_bytes, hwm_bytes) for all succeeded lines
    succeeded_timeline = []

    for i, raw in enumerate(lines):
        lineno = i + 1
        line   = raw.strip()

        if SUCCESS_MARKER in line:
            avail_m = AVAIL_MCM_RE.search(line)
            hwm_m   = HWM_RE.search(line)
            if avail_m and hwm_m:
                succeeded_timeline.append(
                    (lineno, int(avail_m.group(1)), int(hwm_m.group(1)))
                )

        if DENIAL_MARKER in line:
            if not in_denial:
                # Start of a new distinct episode
                ts_m = TIMESTAMP_RE.match(line)
                current_event_start_line = lineno
                current_event_start_ts   = ts_m.group(1) if ts_m else None
                in_denial = True
            else:
                # Already in denial — this is either a repeated banner within
                # the same burst (same second) OR a genuinely new denial episode
                # that started without a State=normal recovery in between.
                # Distinguish by checking if any Succeeded lines appeared since
                # the current denial started — if yes, the server partially
                # recovered and this is a new episode; if no, it's still the
                # same burst.
                new_activity = any(
                    ln > current_event_start_line
                    for ln, _, _ in succeeded_timeline
                )
                if new_activity:
                    # Close the current episode (no recovery line, but clearly ended)
                    denial_lineno  = current_event_start_line
                    avail_timeline = [
                        (ln, av, hw) for ln, av, hw in succeeded_timeline
                        if prev_recovery_lineno < ln < denial_lineno
                    ]
                    hwm_bytes = avail_timeline[-1][2] if avail_timeline else None
                    events.append({
                        'denial_lineno':   denial_lineno,
                        'denial_ts':       current_event_start_ts,
                        'recovery_lineno': None,
                        'recovery_implicit': True,   # closed by resumed activity, not State=normal
                        'hwm_bytes':       hwm_bytes,
                        'avail_timeline':  avail_timeline,
                    })
                    prev_recovery_lineno     = current_event_start_line
                    # Start the new episode
                    ts_m = TIMESTAMP_RE.match(line)
                    current_event_start_line = lineno
                    current_event_start_ts   = ts_m.group(1) if ts_m else None
                # else: same burst, keep in_denial=True and ignore this line

        if NORMAL_MARKER in line and in_denial:
            denial_lineno = current_event_start_line
            # Only include succeeded lines that belong to THIS event's lead-up:
            # after the previous recovery and before this denial.
            avail_timeline = [
                (ln, av, hw) for ln, av, hw in succeeded_timeline
                if prev_recovery_lineno < ln < denial_lineno
            ]
            hwm_bytes = avail_timeline[-1][2] if avail_timeline else None

            events.append({
                'denial_lineno':   denial_lineno,
                'denial_ts':       current_event_start_ts,
                'recovery_lineno': lineno,
                'recovery_implicit': False,
                'hwm_bytes':       hwm_bytes,
                'avail_timeline':  avail_timeline,
            })
            prev_recovery_lineno     = lineno
            in_denial                = False
            current_event_start_line = None
            current_event_start_ts   = None

    # Open episode at EOF
    if in_denial:
        denial_lineno  = current_event_start_line
        avail_timeline = [
            (ln, av, hw) for ln, av, hw in succeeded_timeline
            if prev_recovery_lineno < ln < denial_lineno
        ]
        hwm_bytes = avail_timeline[-1][2] if avail_timeline else None
        events.append({
            'denial_lineno':   denial_lineno,
            'denial_ts':       current_event_start_ts,
            'recovery_lineno': None,
            'recovery_implicit': False,   # genuinely open — log ended mid-denial
            'hwm_bytes':       hwm_bytes,
            'avail_timeline':  avail_timeline,
        })

    return events




# ---------------------------------------------------------------------------
# Block parsers (unchanged from v3)
# ---------------------------------------------------------------------------

def parse_detail_block(lines, start_idx):
    data = {}
    idx  = start_idx
    while idx < len(lines):
        line = lines[idx].rstrip('\n')
        if (line.strip().startswith("Note:") or
                line.strip().startswith("Working set includes") or
                line.strip().startswith("SmartHeap cache memory")):
            break
        m = DETAIL_LINE_RE.match(line)
        if m:
            label, unit, value = m.groups()
            data[label.strip()] = (to_mb(int(value), unit), unit)
            idx += 1
        elif TIMESTAMP_RE.match(line) or line.strip() == "":
            break
        else:
            idx += 1
            if idx - start_idx > 60:
                break
    return data, idx


def parse_abbrev_block(lines, start_idx):
    data = {}
    idx  = start_idx
    while idx < len(lines):
        line = lines[idx].rstrip('\n')
        if TIMESTAMP_RE.match(line):
            break
        m = ABBREV_LINE_RE.match(line.strip())
        if m:
            label, raw, human, unit = m.groups()
            data[label.strip()] = (raw, human, unit)
            idx += 1
        elif line.strip() == "":
            idx += 1
        else:
            break
    return data, idx


# ---------------------------------------------------------------------------
# Main parse
# ---------------------------------------------------------------------------

def parse_log(lines, start_line, denial_lineno):
    """
    Forward pass from start_line to denial_lineno.

    Accumulates Contract Request Succeeded entries. At denial_lineno captures
    the detail block, Current Memory Info, and MCM Settings.

    New in v4:
      - Captures Source= per request, stored in oid_sources[oid][source] = bytes
      - Captures AvailableMCM per request for the window summary header
    """
    oid_size    = {}
    oid_count   = {}
    oid_sids    = {}
    oid_sources = {}   # oid -> {source_name -> bytes}
    total_requests = 0
    unmatched   = []

    detail_block = {}
    current_info = {}
    mcm_settings = {}
    denial_ts    = None
    first_success_ts  = None
    last_avail_mcm_gb = None

    n   = len(lines)
    idx = 0
    while idx < n:
        lineno = idx + 1
        line   = lines[idx].strip()

        if lineno < start_line:
            idx += 1
            continue

        ts_m = TIMESTAMP_RE.match(line)
        ts   = ts_m.group(1) if ts_m else None

        # ---- Stop: denial line reached ----
        if lineno == denial_lineno:
            denial_ts    = ts
            detail_block, idx = parse_detail_block(lines, idx + 1)
            while idx < n:
                line2 = lines[idx].strip()
                if CURRENT_INFO_MARKER in line2 and not current_info:
                    current_info, idx = parse_abbrev_block(lines, idx + 1)
                elif MCM_SETTINGS_MARKER in line2 and not mcm_settings:
                    mcm_settings, idx = parse_abbrev_block(lines, idx + 1)
                else:
                    idx += 1
                if current_info and mcm_settings:
                    break
            break

        # ---- Accumulate successful requests ----
        if SUCCESS_MARKER in line:
            if ts and first_success_ts is None:
                first_success_ts = ts
            sid_m    = SID_RE.search(line)
            oid_m    = OID_RE.search(line)
            size_m   = SIZE_RE.search(line)
            source_m = SOURCE_RE.search(line)
            avail_m  = AVAIL_MCM_RE.search(line)

            if avail_m:
                last_avail_mcm_gb = int(avail_m.group(1)) / 1024**3

            if sid_m and oid_m and size_m:
                sid    = sid_m.group(1)
                oid    = oid_m.group(1)
                size   = int(size_m.group(1))
                source = source_m.group(1) if source_m else "Unknown"

                oid_size[oid]  = oid_size.get(oid, 0) + size
                oid_count[oid] = oid_count.get(oid, 0) + 1
                oid_sids.setdefault(oid, set()).add(sid)

                if oid not in oid_sources:
                    oid_sources[oid] = {}
                oid_sources[oid][source] = oid_sources[oid].get(source, 0) + size

                total_requests += 1
            else:
                unmatched.append((lineno, line))

        idx += 1

    return {
        'oid_size':          oid_size,
        'oid_count':         oid_count,
        'oid_sids':          oid_sids,
        'oid_sources':       oid_sources,
        'total_requests':    total_requests,
        'unmatched':         unmatched,
        'detail_block':      detail_block,
        'current_info':      current_info,
        'mcm_settings':      mcm_settings,
        'denial_lineno':     denial_lineno,
        'denial_ts':         denial_ts,
        'first_success_ts':  first_success_ts,
        'last_avail_mcm_gb': last_avail_mcm_gb,
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_report(result, window_label, output_txt, output_csv):
    d = result

    with open(output_txt, 'w') as f:
        f.write("DSSErrors.log — MCM Lead-Up Analysis\n")
        f.write(f"Generated      : {datetime.now().isoformat(timespec='seconds')}\n")
        f.write(f"Analysis window: {window_label}\n")
        if d['first_success_ts']:
            f.write(f"               : {d['first_success_ts']}  ->  "
                    f"{d['denial_ts']}  (line {d['denial_lineno']})\n")
        f.write(f"Requests parsed: {d['total_requests']}\n")
        if d['last_avail_mcm_gb'] is not None:
            f.write(f"AvailableMCM at last succeeded request: {d['last_avail_mcm_gb']:.3f} GB\n")
        if d['unmatched']:
            f.write(f"WARNING: {len(d['unmatched'])} lines matched the success marker "
                    f"but could not be parsed — check log format.\n")
        f.write("\n")

        # Section 1
        f.write("=" * 70 + "\n")
        f.write("SECTION 1: MEMORY STATE AT MCM DENIAL\n")
        f.write("=" * 70 + "\n\n")
        if not d['detail_block'] and not d['current_info'] and not d['mcm_settings']:
            f.write("No MCM denial state block found.\n\n")
        else:
            _write_detail(f, d['detail_block'])
            # SmartHeap flag: only meaningful when SmartHeap Cache Releasable = false,
            # meaning MCM cannot reclaim it under pressure. If releasable=true the pool
            # releases automatically and its size is not actionable.
            sh_releasable = d['mcm_settings'].get('SmartHeap Cache Releasable')
            if sh_releasable and sh_releasable[0].lower() == 'false':
                smartheap = _get(d['detail_block'], "Unused Memory Pool In SmartHeap")
                virt_isvr = _get(d['detail_block'], "Total In Use Virtual Memory")
                if smartheap and virt_isvr:
                    p = pct(smartheap, virt_isvr)
                    f.write(f"  [REVIEW] SmartHeap Cache Releasable = false: SmartHeap unused pool "
                            f"({fmt_mb(smartheap)}, {p:.1f}% of IServer virtual) cannot be reclaimed "
                            f"by MCM under pressure. Consider enabling SmartHeap cache release.\n\n")
            _write_current_info(f, d['current_info'])
            _write_mcm_settings(f, d['mcm_settings'])

        # Section 2
        f.write("=" * 70 + "\n")
        f.write("SECTION 2: MEMORY CONSUMED BY OBJECT IN THE LEAD-UP\n")
        f.write("=" * 70 + "\n\n")

        total_size = sum(d['oid_size'].values())
        f.write(f"Total memory granted in window : {fmt(total_size)}\n")
        f.write(f"Unique objects (OIDs)          : {len(d['oid_size'])}\n\n")

        for oid, size in sorted(d['oid_size'].items(), key=lambda x: -x[1]):
            p    = pct(size, total_size)
            note = "  (system/background — no session)" if oid == "0" else ""
            f.write(f"  OID: {oid}{note}\n")
            f.write(f"    Total:    {fmt(size):>10}  ({p:.1f}% of window total)"
                    f"  —  {d['oid_count'][oid]} request(s)\n")

            # Source breakdown — only if more than one source type
            sources = d['oid_sources'].get(oid, {})
            if len(sources) > 1:
                f.write(f"    By type:\n")
                max_src_len = max(len(s) for s in sources)
                col = max(max_src_len, 10) + 2  # at least 2 spaces of padding
                for src, src_size in sorted(sources.items(), key=lambda x: -x[1]):
                    src_pct = pct(src_size, size)
                    f.write(f"      {src:<{col}} {fmt(src_size):>10}  ({src_pct:.1f}%)\n")
            elif sources:
                src_name = next(iter(sources))
                f.write(f"    Type:     {src_name}\n")
            f.write("\n")

        if d['unmatched']:
            f.write(f"  Unmatched lines (first 10):\n")
            for lineno, text in d['unmatched'][:10]:
                f.write(f"    line {lineno}: {text[:120]}\n")

    total_size = sum(d['oid_size'].values())
    with open(output_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(["OID", "Source Type", "Sessions (SIDs)",
                    "Size (bytes)", "Size", "% of window total"])
        for oid, oid_total in sorted(d['oid_size'].items(), key=lambda x: -x[1]):
            sids    = ', '.join(sorted(d['oid_sids'][oid]))
            sources = d['oid_sources'].get(oid, {})
            for src, src_size in sorted(sources.items(), key=lambda x: -x[1]):
                w.writerow([
                    oid,
                    src,
                    sids,
                    src_size,
                    fmt(src_size),
                    f"{pct(src_size, total_size):.1f}%",
                ])


# ---------------------------------------------------------------------------
# Section 1 sub-writers (unchanged from v3 except minor label tweaks)
# ---------------------------------------------------------------------------

def _get(data, substr):
    for label, (value_mb, unit) in data.items():
        if substr.lower() in label.lower():
            return value_mb
    return None


def _write_detail(f, data):
    if not data:
        return
    f.write("  Physical memory snapshot\n")
    f.write("  " + "-" * 50 + "\n")

    phys_total = _get(data, "Total System Physical Memory")
    phys_isvr  = _get(data, "Total In Use Physical Memory For Intelligence Server")
    phys_other = _get(data, "Total In Use Physical Memory For Other Processes")

    if phys_total:
        phys_total_mb = phys_total
        for label, val in [("IServer in-use",  phys_isvr),
                            ("Other processes", phys_other)]:
            if val is None:
                continue
            p    = pct(val, phys_total_mb)
            flag = ""
            if label == "Other processes":
                lo, hi = THRESHOLDS['other_processes_pct_physical']
                flag = "  [REVIEW]" if p >= hi else ("  [WATCH]" if p >= lo else "")
            f.write(f"    {label:30} {fmt_mb(val):>10}  ({p:5.1f}%){flag}\n")
        accounted = sum(v for v in [phys_isvr, phys_other] if v)
        free = phys_total_mb - accounted
        f.write(f"    {'Free / unaccounted':30} {fmt_mb(free):>10}  ({pct(free, phys_total_mb):5.1f}%)\n")
    f.write("\n")

    f.write("  IServer virtual memory breakdown\n")
    f.write("  (Note: 'Total Buffer Size Used' is a separate accounting metric,\n")
    f.write("   not an additive component — excluded from percentages below.)\n")
    f.write("  " + "-" * 50 + "\n")

    virt_isvr    = _get(data, "Total In Use Virtual Memory")
    cube         = _get(data, "Cube Caches In Memory")
    cube_idx     = _get(data, "Cube Size Growth In Memory Including Indexes")
    mmf          = _get(data, "MMF Virtual Memory Size")
    working_set  = _get(data, "Working Set Cache RAM Usage")
    smartheap    = _get(data, "Unused Memory Pool In SmartHeap")
    sh_util      = _get(data, "Total SmartHeap Cached Memory Utilization")
    obj_cache    = _get(data, "Object Server Caches In Memory")
    report_cache = _get(data, "Report Caches In Memory")
    doc_cache    = _get(data, "Document Caches In Memory")
    elem_cache   = _get(data, "Element Server Caches In Memory")
    stack        = _get(data, "Total Stack Size")
    other_mem    = _get(data, "Other Memory In Intelligence Server")

    if virt_isvr:
        rows = [
            ("Cube caches (in-memory cubes)",        cube),
            ("  -> of which cube index/growth",      cube_idx),
            ("  -> of which MMF", mmf),
            ("Working set",                          working_set),
            ("SmartHeap unused pool",                smartheap),
            ("  -> of which SmartHeap cache util",   sh_util),
            ("Object server cache",                  obj_cache),
            ("Report cache",                         report_cache),
            ("Document cache",                       doc_cache),
            ("Element server cache",                 elem_cache),
            ("Stack",                                stack),
            ("Other memory  (unaccountable / jobs)", other_mem),
        ]
        for label, val in rows:
            if val is None:
                continue
            p    = pct(val, virt_isvr)
            flag = "  <-- see Section 2" if "Other memory" in label and p >= THRESHOLDS['other_memory_pct_iserver_flag'] else ""
            f.write(f"    {label:42} {fmt_mb(val):>10}  ({p:5.1f}%){flag}\n")

        flags = []
        if working_set and pct(working_set, virt_isvr) > THRESHOLDS['working_set_pct_iserver_max']:
            flags.append(f"  [REVIEW] Working set is {pct(working_set,virt_isvr):.1f}% of IServer virtual "
                         f"(guideline: <{THRESHOLDS['working_set_pct_iserver_max']}%)")

        # SmartHeap: only flag if not releasable (caller must pass mcm_settings context)
        # Flag handled in write_report where we have access to mcm_settings.

        # MMF flag: when cube cache is a significant portion of memory and MMF
        # is covering less than 10% of it, the customer is not meaningfully
        # leveraging MMF to offload cube data to disk.
        if cube and pct(cube, virt_isvr) >= THRESHOLDS['cube_pct_iserver_flag']:
            mmf_val = mmf if mmf is not None else 0
            mmf_pct_of_cube = pct(mmf_val, cube)
            if mmf_val == 0:
                flags.append(
                    f"  [REVIEW] Cube cache is {pct(cube,virt_isvr):.1f}% of IServer virtual memory "
                    f"and MMF is not in use (MMF=0). Enabling Memory Mapped Files would allow "
                    f"cube data to be offloaded to disk, directly reducing in-memory cube footprint."
                )
            elif mmf_pct_of_cube < THRESHOLDS['mmf_pct_of_cube_low']:
                flags.append(
                    f"  [REVIEW] Cube cache is {pct(cube,virt_isvr):.1f}% of IServer virtual memory "
                    f"but MMF covers only {mmf_pct_of_cube:.1f}% of it ({fmt_mb(mmf_val)}). "
                    f"Consider expanding MMF usage to offload more cube data to disk."
                )

        if flags:
            f.write("\n")
            for flag in flags:
                f.write(f"  {flag}\n")
    f.write("\n")


def _write_current_info(f, data):
    if not data:
        return
    f.write("  Current Memory Info (abbreviated snapshot)\n")
    f.write("  " + "-" * 50 + "\n")
    for label, (raw, human, unit) in data.items():
        human_str = f"{human} {unit}" if human else ""
        f.write(f"    {label:40} = {human_str if human_str else raw}\n")
    total = data.get("System Total") or data.get("System Total Physical Memory")
    avail = data.get("System Available") or data.get("System Available Physical Memory")
    if total and avail:
        try:
            p = pct(int(avail[0]), int(total[0]))
            f.write(f"\n    --> {p:.1f}% of system memory was free at denial time.\n")
            if p < 5:
                f.write(f"        [REVIEW] Very little headroom — system was nearly full.\n")
        except (ValueError, TypeError):
            pass
    f.write("\n")


def _write_mcm_settings(f, data):
    if not data:
        return
    f.write("  MCM Settings\n")
    f.write("  " + "-" * 50 + "\n")
    for label, (raw, human, unit) in data.items():
        human_str = f"{human} {unit}" if human else ""
        f.write(f"    {label:40} = {human_str if human_str else raw}\n")
    f.write("\n")


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def prompt_event(events):
    """Present the event menu and return the chosen event dict."""
    print(f"\nFound {len(events)} distinct MCM denial event(s):\n")
    last_idx = len(events) - 1
    for i, ev in enumerate(events, 1):
        if ev['recovery_lineno']:
            recovery = f"recovered at line {ev['recovery_lineno']}"
        elif ev['recovery_implicit']:
            recovery = "recovered (resumed contract requests)"
        elif i - 1 == last_idx:
            recovery = "no recovery found (log may be truncated)"
        else:
            recovery = "recovered (resumed contract requests)"
        print(f"  [{i}] {ev['denial_ts']}  (line {ev['denial_lineno']})  —  {recovery}")

    print()
    while True:
        raw = input("Which event to analyze? Enter a number"
                    " (or a raw start line number for a custom window): ").strip()
        if not raw:
            continue
        try:
            choice = int(raw)
        except ValueError:
            print("  Please enter a number.")
            continue
        if 1 <= choice <= len(events):
            return events[choice - 1], None   # (event, custom_start_line)
        # Treat as a raw line number if out of menu range
        print(f"  (Treating {choice} as a custom start line.)")
        return None, choice


def prompt_window(event, lines):
    """
    Show the AvailableMCM threshold menu for the chosen event and return
    (start_line, window_label).

    Uses "last crossing downward" logic: for each threshold, find the last
    time AvailableMCM was ABOVE the threshold before denial, then take the
    first line after that where it dropped below. This anchors windows to the
    final pressure descent rather than the first time the threshold was ever
    crossed (which on machines that run near-capacity all day would always be
    line 1 of the log).

    Thresholds that were never reached from above (machine was already below
    them at the start of the log) are shown as "always below" with a note,
    and are included so the user can still choose the full available window.

    Duplicate start lines (multiple thresholds resolving to the same line)
    are collapsed into one option to avoid clutter.
    """
    timeline  = event['avail_timeline']
    hwm_bytes = event['hwm_bytes']

    if not timeline or not hwm_bytes:
        print("  No AvailableMCM data found before this event — defaulting to line 1.")
        return 1, "full log"

    hwm_gb = hwm_bytes / 1024**3
    print(f"\n  HWM at denial: {hwm_gb:.1f} GB\n")
    print("  AvailableMCM pressure windows (final descent before denial):\n")
    print(f"    {'#':>3}  {'Threshold':>18}  {'Window starts':22}  {'Requests in window':>18}")
    print("    " + "-" * 70)

    options = []
    seen_start_lines = set()

    for pct_val in WINDOW_THRESHOLDS_PCT:
        threshold_bytes = hwm_bytes * pct_val / 100
        threshold_gb    = threshold_bytes / 1024**3

        # Find the last sample that was still ABOVE the threshold
        last_above = None
        for ln, avail, _ in timeline:
            if avail >= threshold_bytes:
                last_above = ln

        if last_above is not None:
            # Final descent: first sample after last_above that is below threshold
            first_below = next(
                ((ln, av) for ln, av, _ in timeline if ln > last_above and av < threshold_bytes),
                None
            )
            if first_below is None:
                # last_above was the final sample above, then log ends — use next line
                start_lineno = last_above + 1
                note = ""
            else:
                start_lineno, _ = first_below
                note = ""
        else:
            # Was always below this threshold — use the very first timeline line
            start_lineno = timeline[0][0]
            note = " (always below — machine ran near-capacity throughout)"

        # Deduplicate: skip if this start line is identical to a prior option
        if start_lineno in seen_start_lines:
            continue
        seen_start_lines.add(start_lineno)

        ts_m     = TIMESTAMP_RE.match(lines[start_lineno - 1].strip())
        start_ts = ts_m.group(1) if ts_m else '?'
        count    = sum(1 for ln, _, _ in timeline if ln >= start_lineno)
        label    = (f"AvailableMCM < {pct_val}% of HWM ({threshold_gb:.1f} GB) "
                    f"from {start_ts}{note}")
        options.append((start_lineno, label, start_ts, count))
        print(f"    [{len(options)}]  < {pct_val:2d}% of HWM ({threshold_gb:.1f} GB)  "
              f"  {start_ts}  {count:>18} requests{note}")

    if not options:
        print("  No AvailableMCM data — defaulting to line 1.")
        return 1, "full log"

    print()
    while True:
        raw = input("  Choose a window (number), or press Enter for the widest: ").strip()
        if not raw:
            start_line, label, _, _ = options[0]
            return start_line, label
        try:
            choice = int(raw)
        except ValueError:
            print("  Please enter a number.")
            continue
        if 1 <= choice <= len(options):
            start_line, label, _, _ = options[choice - 1]
            return start_line, label
        print(f"  Please enter a number between 1 and {len(options)}.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    path = input("Log file path [default: DSSErrors.log]: ").strip() or "DSSErrors.log"

    print("\nScanning log for MCM events...")
    try:
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"ERROR: '{path}' not found.")
        sys.exit(1)
    except IOError as e:
        print(f"ERROR: {e.strerror}")
        sys.exit(1)

    events = prescan(lines)

    if not events:
        print("No MCM denial events found in this log.")
        sys.exit(0)

    # Event selection
    event, custom_start = prompt_event(events)

    if custom_start is not None:
        # User entered a raw line number — find the next denial after it
        denial_lineno = next(
            (ev['denial_lineno'] for ev in events if ev['denial_lineno'] > custom_start),
            None
        )
        if denial_lineno is None:
            print("No MCM denial event found after that line.")
            sys.exit(0)
        start_line   = custom_start
        window_label = f"custom start line {custom_start}"
    else:
        # Window selection for the chosen event
        start_line, window_label = prompt_window(event, lines)
        denial_lineno = event['denial_lineno']

    print(f"\nParsing from line {start_line} to denial at line {denial_lineno}...")
    result = parse_log(lines, start_line, denial_lineno)

    if not result['total_requests'] and not result['detail_block']:
        print("Nothing found in that range. Check your selections.")
        sys.exit(0)

    output_txt = "mcm_analysis.txt"
    output_csv = "mcm_oid_summary.csv"

    write_report(result, window_label, output_txt, output_csv)

    print(f"\nDone.")
    print(f"  MCM denial : {result['denial_ts']} (line {denial_lineno})")
    print(f"  Window     : {window_label}")
    print(f"  Requests   : {result['total_requests']}")
    print(f"  Report     : {output_txt}")
    print(f"  CSV        : {output_csv}")


if __name__ == "__main__":
    main()
