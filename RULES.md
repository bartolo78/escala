# Shift Scheduler Rules and Behavior

This document defines the expected behavior and rules for the Shift Scheduler application. Use this specification when prompting AI tools and when implementing or reviewing scheduling logic.

## Context for the Application
**Purpose:** The Python application generates a shift schedule for 15 workers across all ISO weeks (Monday to Sunday) that include any day of a selected month. For example, for September 2025, the program schedules all complete ISO weeks containing any day in September, including days outside September (e.g., the last week includes October 1–5, 2025, covering ISO week 40 from September 29 to October 5). The results are visualized based on the calendar weeks of the chosen month, but scheduling is strictly based on complete ISO weeks (Monday to Sunday).

**Handling Overlapping Weeks:** If a week (e.g., September 29–October 5, 2025) has already been scheduled in a previous run (e.g., when scheduling September 2025), the program must not reschedule that week when scheduling a subsequent month (e.g., October 2025). Instead, it loads the previously assigned shifts for that week and only schedules the remaining unscheduled ISO weeks for the new month (e.g., for October 2025, schedule ISO weeks starting from October 6, with the last week being October 27–November 2, 2025).

**Worker Types:** There are two types of workers:
- Workers with a standard weekly load of 12 hours.
- Workers with a standard weekly load of 18 hours.
- Both types can work overtime (hours beyond their standard weekly load).
- Some workers cannot work nights (they are identified).

**Shift Types:** There are three shifts per day:
- **M1:** 8:00 AM to 8:00 PM (12 hours).
- **M2:** 8:00 AM to 11:00 PM (15 hours).
- **N:** 8:00 PM to 8:00 AM (12 hours, night shift).

## Program Characteristics
**Vacation Weeks:** A week is considered a vacation week for a worker if they have no available weekdays (Monday to Friday) in that ISO week for scheduling.
- Special days (e.g., holidays) that fall on weekdays (Monday to Friday) are treated as weekend days when calculating long-term weekend shift equity across the year.

**Tracking Features:**
- The application tracks each worker’s shift history, overtime (hours worked beyond their standard weekly load of 12 or 18 hours), and undertime (hours worked below their standard weekly load of 12 or 18 hours).

## Critical Rules
These rules must be strictly enforced in the shift scheduling logic:

**Shift Assignment:**
- There are 3 shifts per day (M1, M2, N), and each shift must be assigned to exactly one worker.
- No shift can be left without a worker assigned.

**Worker Availability:**
- Workers’ unavailable days must be respected (i.e., they cannot be scheduled on those days).

**Shift Intervals:**
- There must be at least a 24-hour interval from the end of one shift to the start of the next shift assigned to the same worker.

**Night Shift Restrictions:**
- Workers who cannot work nights must never be assigned the night shift (N).

**Daily Shift Exclusions:**
- The same worker cannot be assigned more than one shift on the same day.

**Weekly Participation:**
- All workers who have at least one available weekday (Monday to Friday) in a given ISO week must be assigned at least one shift during that ISO week.

**Weekday Shift Distribution:**
- On weekdays (Monday to Friday), ensure that all workers with at least one available weekday in the ISO week are assigned at least one weekday shift before any worker is assigned a second weekday shift in that ISO week.

## Flexible Rules (In Order of Importance)
These rules should be satisfied as much as possible, in the order listed, but may be compromised if necessary to meet the critical rules:

1. **Saturday Priority for First Shift:**
   - Priority should be given to assigning each worker’s first shift of the ISO week on a weekday (Monday to Friday), even if it's a holiday. If this is not possible for some workers, prioritize assigning them a Saturday instead of Sunday, and a M1 or M2 shift instead of a N shift, as their first shift.

2. **Three-Day Weekend Worker Minimization:**
   - When a holiday on a Monday or Friday creates a three-day weekend (Friday-Saturday-Sunday or Saturday-Sunday-Monday), prioritize minimizing the number of different workers assigned shifts over those three days by favoring multiple shifts to the same worker, provided the 24-hour interval between shifts is respected.

3. **Weekend Shift Limits:**
   - Avoid assigning the same worker two shifts in the same weekend (Saturday and Sunday), even if "Shift Intervals" is not break, unless the "Three-Day Weekend Worker Minimization" rule applies.

4. **Consecutive Weekend Shift Avoidance:**
   - Avoid assigning a worker shifts on consecutive weekends if there are other workers who have not yet worked a weekend shift in that month.

5. **M2 Priority:**
   - Prioritize M2 shifts over M1 shifts for workers with a standard weekly load of 18 hours.

6. **Weekend Equity:**
   - Shifts on weekends (Saturday and Sunday) and special days (holidays, including those on weekdays counted as weekend days) should be distributed equitably among workers over the year.

7. **Saturday and Sunday Equity:**
   - Shifts on Saturdays and Sundays should be distributed equitably among workers over the year.

8. **Weekend Night and Day Shift Equity:**
   - On weekends (Saturday and Sunday), night shifts (N) and day shifts (M1 and M2) should be distributed equitably among workers over the year.

9. **Weekday Night and Day Shift Equity:**
   - On weekdays (Monday to Friday), night shifts (N) and day shifts (M1 and M2) should be distributed equitably among workers over the year.

10. **Equitable Day-of-Week Distribution:**
    - Shifts should be distributed equitably across different days of the week (e.g., avoid having some workers only working Mondays while others only work Tuesdays) by the end of the year.

11. **Consecutive Shifts:**
    - Aim to schedule shifts such that the time interval between the end of one shift and the start of the next shift for the same worker is greater than 48 hours, whenever this does not conflict with any critical rules or higher-priority flexible rules (like the "Three-Day Weekend Worker Minimization").

## Implementation Clarifications

To avoid ambiguity, the following clarifications define how the rules should be operationalized in the application:

- **Holidays Treatment:**
   - For equity metrics: holidays that fall on weekdays are counted as weekend days.
   - For first-shift preference and availability checks: holidays that fall on weekdays are treated as weekdays.

- **Weekly Participation:**
   - Applies only to workers who have at least one available weekday (Mon–Fri) in the ISO week.
   - Workers with zero weekday availability are exempt from weekly participation, but may still be assigned weekend shifts if needed to satisfy critical rules.

- **First-Shift Preference Fallback Order (highest to lowest):**
   1) Weekday day shift (M1/M2), even if it’s a holiday.
   2) Weekday night shift (N), even if it’s a holiday.
   3) Saturday day shift (M1/M2).
   4) Saturday night shift (N).
   5) Sunday day shift (M1/M2).
   6) Sunday night shift (N).

- **24-Hour Interval Calculation:**
   - The interval is measured from the actual end time of one shift to the start time of the next shift for the same worker.
   - Examples:
      - N (20:00–08:00) → next-day M1/M2/N is allowed (≥24h rest).
      - M1 (08:00–20:00) → next-day N (20:00–08:00) is allowed (exactly 24h rest).
      - M1 (08:00–20:00) → next-day M1/M2 is not allowed (12–15h rest).

- **Overlapping ISO Weeks:**
   - “Already scheduled” means any assignment exists for an ISO week (year, week) in persistent history.
   - Such weeks are excluded from optimization and their historical assignments are merged into the output for visualization within the selected month.

- **Equity Scope and Accounting:**
   - Equity metrics are computed over the entire year-to-date, incorporating historical assignments from previous months.
   - Holidays on weekdays contribute to weekend-equity counters.

- **M2 Priority:**
   - Prefer assigning M2 over M1 to workers with an 18-hour weekly load when both are feasible.
   - This does not prohibit assigning M2 to 12-hour workers, especially when needed to satisfy critical rules.

- **Vacation Week Determination:**
   - A worker’s vacation week is when they have zero available weekdays (Mon–Fri) in that ISO week.
   - Holidays on weekdays are still considered weekdays for this determination.

- **Infeasibility Handling:**
   - If critical rules cannot be satisfied (e.g., insufficient available workers), the solver reports the instance as infeasible rather than violating critical rules. Flexible rules may be relaxed, but critical rules must always hold.

- **Deterministic Tie-Breaks:**
   - When multiple assignments have equal cost, prefer a stable tie-break (e.g., fixed worker order by `id`, then by `name`) to avoid oscillations across runs.

- **Timezone and DST:**
   - Assume local timezone and fixed shift durations. Ignore DST anomalies (e.g., 23- or 25-hour nights); treat N as 12 hours consistently.

- **Data Schema Recommendations:**
   - Worker: { id, name, weekly_load: 12|18, can_night: bool, unavailable_dates: Set[YYYY-MM-DD] }
   - Shift: { date: YYYY-MM-DD, type: M1|M2|N, start: HH:MM, end: HH:MM }
   - History: keyed by (iso_year, iso_week), storing assigned shifts per day and per worker, plus weekly hour totals, overtime, and undertime.
