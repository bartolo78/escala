#!/usr/bin/env python3
"""Debug script to understand June 2026 infeasibility."""

import sys
from datetime import date, timedelta
from ortools.sat.python import cp_model

# Import from the project
from scheduler_service import SchedulerService
from history_view import HistoryView
from constants import SHIFTS, MIN_REST_HOURS

def main():
    service = SchedulerService()
    service.load_config("config.yaml")
    
    year, month = 2026, 6
    
    # Get history
    history = service._history
    hv = HistoryView(history)
    
    print("=" * 60)
    print("HISTORY ANALYSIS FOR JUNE 2026")
    print("=" * 60)
    
    # Check what's scheduled in May 30-31 (days before June 1)
    first_day = date(2026, 6, 1)
    print(f"\nFirst day of scheduling window: {first_day} ({first_day.strftime('%A')})")
    
    days_before = [first_day - timedelta(days=i) for i in range(1, 8)]
    print(f"\nHistory from days before June 1:")
    for d in reversed(days_before):
        print(f"\n  {d} ({d.strftime('%A')}):")
        found = False
        for worker in service.workers:
            shift = hv.fixed_shift_for(worker.name, d)
            if shift:
                found = True
                shift_cfg = SHIFTS.get(shift, {})
                end_hour = shift_cfg.get('end_hour', 0)
                print(f"    {worker.name}: {shift} (ends at hour {end_hour})")
        if not found:
            print(f"    (no assignments)")
    
    # Check which workers are blocked from June 1 shifts
    print(f"\n{'=' * 60}")
    print("BLOCKED SHIFTS ON JUNE 1 (due to 24h rest from history)")
    print("=" * 60)
    
    june1 = date(2026, 6, 1)
    shift_types = ['M1', 'M2', 'N']
    
    blocked_workers = {st: [] for st in shift_types}
    
    for worker in service.workers:
        for hist_day in [june1 - timedelta(days=1), june1 - timedelta(days=2)]:
            hist_shift = hv.fixed_shift_for(worker.name, hist_day)
            if hist_shift:
                hist_cfg = SHIFTS.get(hist_shift)
                if not hist_cfg:
                    continue
                
                import datetime as dt
                hist_end = dt.datetime.combine(hist_day, dt.time()) + timedelta(hours=hist_cfg['end_hour'])
                
                for st in shift_types:
                    shift_cfg = SHIFTS[st]
                    shift_start = dt.datetime.combine(june1, dt.time()) + timedelta(hours=shift_cfg['start_hour'])
                    
                    if shift_start <= hist_end:
                        blocked_workers[st].append((worker.name, hist_day, hist_shift, "overlap"))
                    else:
                        delta_hours = (shift_start - hist_end).total_seconds() / 3600
                        if delta_hours < MIN_REST_HOURS:
                            blocked_workers[st].append((worker.name, hist_day, hist_shift, f"{delta_hours:.1f}h rest"))
    
    for st in shift_types:
        print(f"\n  {st} shift on June 1 (starts at hour {SHIFTS[st]['start_hour']}):")
        if blocked_workers[st]:
            for name, hday, hshift, reason in blocked_workers[st]:
                print(f"    BLOCKED: {name} (worked {hshift} on {hday}, {reason})")
        else:
            print(f"    (no workers blocked)")
    
    # Check night-incapable workers
    print(f"\n{'=' * 60}")
    print("NIGHT-INCAPABLE WORKERS")
    print("=" * 60)
    for worker in service.workers:
        if not worker.can_night:
            print(f"  {worker.name} cannot work nights")
    
    # Count available workers per shift on June 1
    print(f"\n{'=' * 60}")
    print("AVAILABLE WORKERS PER SHIFT ON JUNE 1")
    print("=" * 60)
    
    for st in shift_types:
        blocked_names = {b[0] for b in blocked_workers[st]}
        if st == 'N':
            # Also exclude night-incapable
            blocked_names |= {w.name for w in service.workers if not w.can_night}
        available = [w.name for w in service.workers if w.name not in blocked_names]
        print(f"\n  {st}: {len(available)} available workers")
        print(f"      Available: {available}")
        print(f"      Blocked: {list(blocked_names)}")
    
    # Test simple feasibility
    print(f"\n{'=' * 60}")
    print("SIMPLE FEASIBILITY TEST FOR WEEK 23 ONLY")
    print("=" * 60)
    
    # Build a minimal model for just week 23
    model = cp_model.CpModel()
    num_workers = len(service.workers)
    workers = [w.to_dict() for w in service.workers]
    
    # Week 23: June 1-7 (Mon-Sun)
    week_days = [date(2026, 6, 1) + timedelta(days=i) for i in range(7)]
    shifts_per_day = 3
    num_shifts = len(week_days) * shifts_per_day
    
    # assigned[w][s] = 1 if worker w is assigned shift s
    assigned = [[model.NewBoolVar(f"a_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
    
    # Each shift exactly one worker
    for s in range(num_shifts):
        model.AddExactlyOne(assigned[w][s] for w in range(num_workers))
    
    # One shift per day per worker
    for w in range(num_workers):
        for d_idx in range(len(week_days)):
            day_shifts = [d_idx * 3 + i for i in range(3)]
            model.Add(sum(assigned[w][s] for s in day_shifts) <= 1)
    
    # Night restrictions
    for w in range(num_workers):
        if not workers[w]["can_night"]:
            for d_idx in range(len(week_days)):
                night_shift = d_idx * 3 + 2  # N is the third shift
                model.Add(assigned[w][night_shift] == 0)
    
    # 24h rest constraint (simplified for this week)
    # After a shift ends, can't start another within 24h
    import datetime as dt
    shift_times = []
    for d_idx, day in enumerate(week_days):
        for st_idx, st in enumerate(['M1', 'M2', 'N']):
            cfg = SHIFTS[st]
            start = dt.datetime.combine(day, dt.time()) + timedelta(hours=cfg['start_hour'])
            end = dt.datetime.combine(day, dt.time()) + timedelta(hours=cfg['end_hour'])
            shift_times.append((start, end))
    
    for w in range(num_workers):
        for i in range(num_shifts):
            for j in range(i + 1, num_shifts):
                start_i, end_i = shift_times[i]
                start_j, end_j = shift_times[j]
                
                if max(start_i, start_j) < min(end_i, end_j):
                    model.AddBoolOr([assigned[w][i].Not(), assigned[w][j].Not()])
                elif start_j >= end_i:
                    delta = (start_j - end_i).total_seconds() / 3600
                    if delta < MIN_REST_HOURS:
                        model.AddBoolOr([assigned[w][i].Not(), assigned[w][j].Not()])
                elif start_i >= end_j:
                    delta = (start_i - end_j).total_seconds() / 3600
                    if delta < MIN_REST_HOURS:
                        model.AddBoolOr([assigned[w][i].Not(), assigned[w][j].Not()])
    
    # Apply history-based blocks for June 1
    for w, worker in enumerate(workers):
        w_name = worker["name"]
        for hist_day in [june1 - timedelta(days=1), june1 - timedelta(days=2)]:
            hist_shift = hv.fixed_shift_for(w_name, hist_day)
            if not hist_shift:
                continue
            hist_cfg = SHIFTS.get(hist_shift)
            if not hist_cfg:
                continue
            
            hist_end = dt.datetime.combine(hist_day, dt.time()) + timedelta(hours=hist_cfg['end_hour'])
            
            # Block conflicting shifts on June 1 (day index 0)
            for st_idx, st in enumerate(['M1', 'M2', 'N']):
                shift_idx = st_idx  # First day
                shift_start = shift_times[shift_idx][0]
                
                if shift_start <= hist_end:
                    model.Add(assigned[w][shift_idx] == 0)
                else:
                    delta = (shift_start - hist_end).total_seconds() / 3600
                    if delta < MIN_REST_HOURS:
                        model.Add(assigned[w][shift_idx] == 0)
    
    # Weekly participation: each worker gets at least 1 shift
    for w in range(num_workers):
        model.Add(sum(assigned[w][s] for s in range(num_shifts)) >= 1)
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    status = solver.Solve(model)
    
    status_names = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }
    
    print(f"\n  Status: {status_names.get(status, status)}")
    
    if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        print("\n  WEEK 23 IS FEASIBLE! Issue is elsewhere.")
        # Print the solution
        for d_idx, day in enumerate(week_days):
            print(f"\n  {day} ({day.strftime('%A')}):")
            for st_idx, st in enumerate(['M1', 'M2', 'N']):
                shift_idx = d_idx * 3 + st_idx
                for w in range(num_workers):
                    if solver.Value(assigned[w][shift_idx]) == 1:
                        print(f"    {st}: {workers[w]['name']}")
                        break
    else:
        print("\n  WEEK 23 IS INFEASIBLE!")
        print("\n  Testing without weekly participation...")
        
        # Remove weekly participation and try again
        model2 = cp_model.CpModel()
        assigned2 = [[model2.NewBoolVar(f"a2_w{w}_s{s}") for s in range(num_shifts)] for w in range(num_workers)]
        
        for s in range(num_shifts):
            model2.AddExactlyOne(assigned2[w][s] for w in range(num_workers))
        
        for w in range(num_workers):
            for d_idx in range(len(week_days)):
                day_shifts = [d_idx * 3 + i for i in range(3)]
                model2.Add(sum(assigned2[w][s] for s in day_shifts) <= 1)
        
        for w in range(num_workers):
            if not workers[w]["can_night"]:
                for d_idx in range(len(week_days)):
                    night_shift = d_idx * 3 + 2
                    model2.Add(assigned2[w][night_shift] == 0)
        
        for w in range(num_workers):
            for i in range(num_shifts):
                for j in range(i + 1, num_shifts):
                    start_i, end_i = shift_times[i]
                    start_j, end_j = shift_times[j]
                    
                    if max(start_i, start_j) < min(end_i, end_j):
                        model2.AddBoolOr([assigned2[w][i].Not(), assigned2[w][j].Not()])
                    elif start_j >= end_i:
                        delta = (start_j - end_i).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model2.AddBoolOr([assigned2[w][i].Not(), assigned2[w][j].Not()])
                    elif start_i >= end_j:
                        delta = (start_i - end_j).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model2.AddBoolOr([assigned2[w][i].Not(), assigned2[w][j].Not()])
        
        # Apply history blocks
        for w, worker in enumerate(workers):
            w_name = worker["name"]
            for hist_day in [june1 - timedelta(days=1), june1 - timedelta(days=2)]:
                hist_shift = hv.fixed_shift_for(w_name, hist_day)
                if not hist_shift:
                    continue
                hist_cfg = SHIFTS.get(hist_shift)
                if not hist_cfg:
                    continue
                hist_end = dt.datetime.combine(hist_day, dt.time()) + timedelta(hours=hist_cfg['end_hour'])
                for st_idx in range(3):
                    shift_idx = st_idx
                    shift_start = shift_times[shift_idx][0]
                    if shift_start <= hist_end:
                        model2.Add(assigned2[w][shift_idx] == 0)
                    else:
                        delta = (shift_start - hist_end).total_seconds() / 3600
                        if delta < MIN_REST_HOURS:
                            model2.Add(assigned2[w][shift_idx] == 0)
        
        status2 = solver.Solve(model2)
        print(f"  Without weekly participation: {status_names.get(status2, status2)}")

if __name__ == "__main__":
    main()
