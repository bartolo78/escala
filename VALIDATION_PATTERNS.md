# Input Validation Quick Reference

Quick reference for the validation patterns implemented in the scheduling app.

## Pattern 1: List Processing with Validation

```python
def process_entries(entries):
    """Process entries with validation."""
    results = set()
    for entry in entries:
        try:
            # Parse entry
            result = parse_entry(entry)
            results.add(result)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse entry '{entry}': {e}")
            continue  # Skip invalid, continue with rest
    return results
```

**Key Points:**
- ✅ Continue processing after errors
- ✅ Log specific error with context
- ✅ Return partial results

## Pattern 2: Dict Structure Validation

```python
def process_dict(data):
    """Validate dict structure before use."""
    if not isinstance(data, dict):
        logger.error(f"Expected dict, got {type(data)}")
        return None
    
    required_keys = ['key1', 'key2']
    for key in required_keys:
        if key not in data:
            logger.error(f"Missing required key '{key}'")
            return None
    
    # Safe to use data now
    return process_valid_data(data)
```

**Key Points:**
- ✅ Check type first
- ✅ Validate required keys
- ✅ Return early on errors

## Pattern 3: List of Dicts Validation

```python
def process_list(items):
    """Validate list of dicts."""
    if not isinstance(items, list):
        logger.error(f"Expected list, got {type(items)}")
        return {}
    
    results = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning(f"Item {i} is not a dict: {item}")
            continue
        
        if 'required_key' not in item:
            logger.warning(f"Item {i} missing 'required_key': {item}")
            continue
        
        # Process valid item
        results[item['required_key']] = item
    
    return results
```

**Key Points:**
- ✅ Validate container type
- ✅ Validate each item
- ✅ Skip invalid items, keep valid ones

## Pattern 4: Date Range Validation

```python
def parse_date_range(start_str, end_str):
    """Parse and validate date range."""
    try:
        start = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
    except ValueError as e:
        logger.warning(f"Invalid date format: {e}")
        return None
    
    if end < start:
        logger.warning(f"End date {end} before start date {start}")
        return None
    
    return start, end
```

**Key Points:**
- ✅ Validate format first
- ✅ Validate logic (ordering)
- ✅ Return None on error

## Pattern 5: Bounds Checking

```python
def safe_array_access(array, index):
    """Safe array access with bounds check."""
    if not (0 <= index < len(array)):
        logger.warning(f"Index {index} out of bounds (0-{len(array)-1})")
        return None
    
    return array[index]
```

**Key Points:**
- ✅ Check bounds before access
- ✅ Log when out of bounds
- ✅ Return safe default

## Pattern 6: Enum/Set Validation

```python
VALID_VALUES = {'M1', 'M2', 'N'}

def validate_value(value):
    """Validate value against allowed set."""
    if value not in VALID_VALUES:
        logger.warning(
            f"Invalid value '{value}'. Valid options: {VALID_VALUES}"
        )
        return False
    return True
```

**Key Points:**
- ✅ Check membership
- ✅ Show valid options in error
- ✅ Return boolean

## Pattern 7: Early Return on Validation Failure

```python
def generate_schedule(workers, ...):
    """Generate schedule with input validation."""
    # Validate critical inputs first
    if not workers:
        logger.error("No workers provided")
        return {}, {}, [], {"error": "No workers"}, {}
    
    # Validate structure
    for i, worker in enumerate(workers):
        if not isinstance(worker, dict):
            logger.error(f"Worker {i} is not a dict")
            return {}, {}, [], {"error": "Invalid worker"}, {}
        
        if 'name' not in worker:
            logger.error(f"Worker {i} missing 'name'")
            return {}, {}, [], {"error": "Missing name"}, {}
    
    # All validation passed, proceed with logic
    return do_schedule(workers, ...)
```

**Key Points:**
- ✅ Validate at function entry
- ✅ Return early on errors
- ✅ Include error in return value

## Pattern 8: Context in Error Messages

```python
# ❌ BAD - No context
logger.warning("Invalid date")

# ✅ GOOD - Full context
logger.warning(
    f"Invalid date format in unavailability for {worker_name}: "
    f"'{date_str}' - {error}"
)
```

**Key Points:**
- ✅ Include entity name (worker, shift, etc.)
- ✅ Include the invalid value
- ✅ Include the error details
- ✅ Make it actionable

## Logging Best Practices

### When to Log

- **ERROR**: System cannot continue, operation failed
- **WARNING**: Data issue, but can continue with partial results  
- **INFO**: Normal operations, milestones
- **DEBUG**: Detailed diagnostic information

### Example

```python
# ERROR - operation failed completely
logger.error("Cannot generate schedule: no workers provided")

# WARNING - partial failure, can continue
logger.warning(f"Skipping invalid entry '{entry}': invalid date format")

# INFO - normal operation milestone
logger.info(f"Processing {len(workers)} workers for {year}-{month}")

# DEBUG - detailed diagnostics
logger.debug(f"Parsed unavailability: {unav_parsed}")
```

## Testing Validation

```python
def test_validation_with_logging(caplog):
    """Test that validation logs warnings."""
    result = process_invalid_data()
    
    # Check result handled gracefully
    assert result is not None  # or == expected_value
    
    # Check warning was logged
    assert "Expected warning message" in caplog.text
```

## Checklist for New Functions

When writing new functions that process user input:

- [ ] Validate input types (list, dict, etc.)
- [ ] Check for None/empty values
- [ ] Validate required keys in dicts
- [ ] Validate data ranges (dates, numbers)
- [ ] Validate enum/set membership
- [ ] Wrap parsing in try-except
- [ ] Log warnings with context
- [ ] Continue with valid data after errors
- [ ] Return safe defaults on errors
- [ ] Add tests for invalid inputs
- [ ] Add tests that warnings are logged

## Common Pitfalls to Avoid

### ❌ Silent Failures
```python
# BAD
if value not in VALID_VALUES:
    pass  # Silent failure
```

### ✅ Logged Failures
```python
# GOOD
if value not in VALID_VALUES:
    logger.warning(f"Invalid value '{value}'. Valid: {VALID_VALUES}")
    return None
```

### ❌ Crash on Bad Data
```python
# BAD
result = data['required_key']  # May crash
```

### ✅ Safe Access
```python
# GOOD
if 'required_key' not in data:
    logger.warning("Missing required_key")
    return None
result = data['required_key']
```

### ❌ Generic Errors
```python
# BAD
logger.error("Error occurred")
```

### ✅ Specific Errors
```python
# GOOD
logger.error(f"Failed to parse date '{date_str}' for worker {name}: {error}")
```
