# Zero Metrics Investigation Plan

## Executive Summary

Despite rebuilding the NEF emulator with fixes, metrics remain zero. New root cause identified: **Timer initialization bug** causing movement loop to fail silently. Additionally, no handover decisions are being triggered.

---

## 🔍 Findings from Latest Run

### 1. **Timer Error Storm** (CRITICAL)

- **Symptom**: Hundreds of "Timer error: Timer is not running. Use .start() to start it"
- **Location**: `ue_movement.py` line 157: `t.status()` called before `t.start()`
- **Impact**: Timer created at line 66 but never started for initial state
- **Evidence**: `/thesis_results/test_with_rebuilt_image/logs/ml_mode_docker.log`

### 2. **Topology Initialized Successfully** ✅

- 3 UEs created (202010000000001, 202010000000002, 202010000000003)
- 4 Cells created (AAAA1001-AAAA1004)
- Paths and associations configured
- **Conclusion**: Network elements exist, not a topology issue

### 3. **ML Service Started** ✅

- Model trained with synthetic data
- Workers listening on port 5050
- **But**: No handover prediction requests logged
- **Conclusion**: UE movement not triggering ML service calls

### 4. **UE Movement Threads Start** ⚠️

- Start-loop endpoints return HTTP 200
- Threads created and registered
- **But**: Timer errors prevent proper execution

---

## 🎯 Root Cause Analysis

### Primary Issue: Timer State Machine Bug

```python
# Line 66 - Timer created but NOT started
t = timer.SequencialTimer(logger=logging.critical)

# Line 157 - Timer.status() called (FAILS - not started)
elapsed_time = t.status()  # Raises TimerError

# Line 304 - Timer finally started (too late!)
t.start()
```

**The Flow Problem:**

1. Timer created in unstarted state
2. Code tries to check timer status before starting it
3. Exception caught and logged (hundreds of times)
4. Movement loop continues but timer-dependent features fail
5. This affects loss-of-connectivity detection which uses timer

### Secondary Issue: No Handover Triggers

- Movement loop updates UE coordinates
- `check_distance()` calculates nearest cell
- **Missing**: No evidence of handover decision logic execution
- **Missing**: No ML service prediction requests
- **Possible causes**:
  - UEs might be starting in cells where no movement triggers handover
  - Handover logic might be conditional on subscription states
  - Distance calculation not triggering cell changes

---

## 📋 Investigation Tasks (Prioritized)

### **Phase 1: Fix Timer Initialization** (High Priority)

**Why**: Blocks timer-dependent features; generates error storm

- [ ] **Task 1.1**: Add `t.start()` immediately after timer creation

  - File: `ue_movement.py` line ~67
  - Add after: `t = timer.SequencialTimer(logger=logging.critical)`
  - Change: Insert `t.start()` on next line
- [ ] **Task 1.2**: Review timer start/stop logic flow

  - Audit all conditional `t.start()` and `t.stop()` calls
  - Ensure timer state is valid before `.status()` calls
  - Lines to check: 209, 304, 417, 433
- [ ] **Task 1.3**: Test timer fix in isolation

  - Rebuild NEF emulator image
  - Run 5-min test
  - Verify timer errors disappear from logs

---

### **Phase 2: Trace UE Movement Execution** (High Priority)

**Why**: Understand if movement loop is actually running

- [ ] **Task 2.1**: Add debug logging to movement loop

  - Log when UE position updates
  - Log `cell_now` calculation results
  - Log handover decisions
  - File: `ue_movement.py` lines 145-150 (coordinate update section)
- [ ] **Task 2.2**: Check cell distance calculations

  - Log output of `check_distance()` function
  - Verify it returns valid cell IDs
  - Confirm UEs are actually changing cells
  - File: `ue_movement.py` line 147
- [ ] **Task 2.3**: Verify movement speed logic

  - Confirm `moving_position_index` increments correctly
  - Check LOW speed (+=1) vs HIGH speed (+=10)
  - Ensure sleep timing is correct
  - File: `ue_movement.py` lines ~330-340

---

### **Phase 3: Investigate Handover Decision Logic** (High Priority)

**Why**: No handover events = no metrics

- [ ] **Task 3.1**: Find where handover decisions are made

  - Search for ML service API calls in NEF code
  - Look for `/predict` or `/handover` endpoints
  - Check if handover is triggered by cell change
  - Possible files: `ue_movement.py`, separate handover module
- [ ] **Task 3.2**: Check handover triggering conditions

  - Does cell change automatically trigger handover?
  - Are there subscription requirements?
  - Is ML mode properly enabled?
  - Review environment variables and configuration
- [ ] **Task 3.3**: Verify ML service integration

  - Check NEF → ML service HTTP client code
  - Verify ML_LOCAL environment variable setting
  - Test ML service `/health` and `/predict` endpoints manually
  - File: Look for requests to `ml-service:5050`

---

### **Phase 4: Check Handover Metrics Export** (Medium Priority)

**Why**: Handovers might happen but not be counted

- [ ] **Task 4.1**: Verify Prometheus metrics registration

  - Check if handover counters are defined
  - Ensure metrics are exported by NEF/ML service
  - Look for `prometheus_client` usage in code
- [ ] **Task 4.2**: Check metrics collection timing

  - Verify experiment script waits long enough
  - Ensure Prometheus scrapes before shutdown
  - Check scrape interval configuration
- [ ] **Task 4.3**: Test metrics endpoint manually

  - `curl http://localhost:8080/metrics` (NEF)
  - `curl http://localhost:5050/metrics` (ML service)
  - Look for non-zero handover counters

---

### **Phase 5: Verify Cell Topology Correctness** (Low Priority)

**Why**: Sanity check - cells might be misconfigured

- [ ] **Task 5.1**: Check cell positions vs path positions

  - Ensure path points actually traverse multiple cells
  - Verify cell coverage areas overlap path
  - Review `init_simple_http.sh` cell definitions
- [ ] **Task 5.2**: Verify UE starting positions

  - Confirm UEs start in specific cells
  - Check if initial positions match path starting points
  - Review UE creation in topology script
- [ ] **Task 5.3**: Calculate expected handover count

  - Manual calculation: path length / cell coverage
  - Estimate handovers per minute
  - Set realistic expectations for 5-min test

---

## 🔧 Quick Fixes to Implement Now

### Fix 1: Timer Initialization

```python
# In ue_movement.py around line 66-67
t = timer.SequencialTimer(logger=logging.critical)
t.start()  # ← ADD THIS LINE
rt = None
```

### Fix 2: Add Movement Debug Logging

```python
# In ue_movement.py around line 145
ue_data["latitude"] = points[current_position_index]["latitude"]
ue_data["longitude"] = points[current_position_index]["longitude"]
cell_now = check_distance(ue_data["latitude"], ue_data["longitude"], json_cells)

# ADD THESE LINES:
logging.info(
    f"UE {supi} moved to ({ue_data['latitude']}, {ue_data['longitude']}), "
    f"nearest cell: {cell_now.get('id') if cell_now else 'NONE'}"
)
```

### Fix 3: Log Handover Attempts

```python
# Search for handover decision code and add:
logging.info(f"Handover decision for UE {supi}: old_cell={old_cell} → new_cell={new_cell}")
```

---

## 🧪 Test Strategy

### Minimal Test (10 minutes)

1. Apply timer fix only
2. Rebuild NEF image
3. Run 5-min experiment
4. Check logs for timer errors (should be gone)

### Movement Verification Test (15 minutes)

1. Add movement debug logging
2. Rebuild NEF image
3. Run 5-min experiment
4. Grep logs for "moved to" messages
5. Verify cell changes occur

### Full Integration Test (20 minutes)

1. Apply all fixes
2. Run 10-min experiment
3. Check for non-zero metrics
4. Verify ML service receives requests

---

## 📊 Success Criteria

### Phase 1 Success:

- ✅ No timer errors in logs
- ✅ Timer-dependent subscriptions work

### Phase 2 Success:

- ✅ UE position updates logged
- ✅ Cell changes detected
- ✅ Movement speed matches expectations

### Phase 3 Success:

- ✅ Handover decisions logged
- ✅ ML service receives prediction requests
- ✅ Handover success/failure recorded

### Phase 4 Success:

- ✅ `total_handovers` > 0
- ✅ ML-specific metrics populated
- ✅ Comparison report shows real data

---

## 🚨 If Metrics Still Zero After All Fixes

### Last Resort Debugging:

1. **Manual API Test**: Call ML `/predict` endpoint directly
2. **Trace Code Path**: Add logging at EVERY step from movement → handover → metrics
3. **Check Database**: Query NEF database for handover records
4. **Network Inspection**: Use tcpdump to verify ML service calls
5. **Simplified Test**: Create single-UE, two-cell minimal scenario

---

## 📝 Notes

- Timer bug definitely prevents loss-of-connectivity features
- Handover logic location still unclear - needs code search
- ML service is healthy but unused - integration gap likely
- Topology is correctly initialized - not the problem
- Movement threads start but execution path unclear

---

## Next Steps

**IMMEDIATELY**:

1. Apply timer fix (Task 1.1)
2. Add movement logging (Task 2.1)
3. Rebuild and test

**THEN**:
4. Find handover decision code (Task 3.1)
5. Verify ML integration (Task 3.3)
6. Test with verbose logging

**FINALLY**:
7. Once handovers work, verify metrics export
8. Run full experiment
9. Generate thesis results

---

*Generated: 2025-11-06*
*Context: test_with_rebuilt_image experiment - timer errors, zero metrics*
