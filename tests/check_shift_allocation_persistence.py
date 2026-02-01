from scheduler_service import SchedulerService

# Initialize service and backup original shift_reduction_pct
s = SchedulerService()
orig = s._shift_reduction_pct.copy()

# Choose test values
worker1 = 'Sofia'
stat = 'sun_holiday_m2'
worker2 = 'Tome'

# Set allocation and save
s.set_shift_allocation_pct(worker1, stat, 50)
s.save_config()

# Reload service to ensure persistence
s2 = SchedulerService()
val1 = s2.get_shift_allocation_pct(worker1, stat)
val2 = s2.get_shift_allocation_pct(worker2, stat)
print({'persisted_for_sofia': val1, 'default_for_tome': val2})

# Restore original config
s2._shift_reduction_pct = orig
s2.save_config()
